# test_causal_chain_builder.py
# =============================
# Comprehensive tests for domain/causality/causal_chain_builder.py.
# Covers enums, BuildResult, all build methods, traceability, validation, history, and statistics.

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from domain.causality.causal_chain_builder import (
    BuildResult,
    CausalChainBuilder,
    ChainBuildStatus,
    ChainDirection,
    get_causal_chain_builder,
)
from domain.causality.causal_node import CausalNode, CausalNodeType


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------
@pytest.fixture
def mock_node_service():
    """Mock the causal node service."""
    with patch("domain.causality.causal_chain_builder.get_causal_node_service") as mock:
        service = MagicMock()
        mock.return_value = service
        yield service


@pytest.fixture
def mock_intent_service():
    """Mock intent service."""
    with patch("domain.causality.causal_chain_builder.get_immutable_intent_record_service") as mock:
        service = MagicMock()
        mock.return_value = service
        yield service


@pytest.fixture
def mock_event_service():
    """Mock economic event service."""
    with patch("domain.causality.causal_chain_builder.get_economic_event_service") as mock:
        service = MagicMock()
        mock.return_value = service
        yield service


@pytest.fixture
def causal_builder(mock_node_service, mock_intent_service, mock_event_service) -> CausalChainBuilder:
    """Reset singleton and return fresh builder with mocked dependencies."""
    CausalChainBuilder._instance = None
    builder = CausalChainBuilder()
    # Override the node service with the mock
    builder._node_service = mock_node_service
    builder._intent_service = mock_intent_service
    builder._event_service = mock_event_service
    builder._build_history = []
    return builder


@pytest.fixture
def sample_intent_node() -> CausalNode:
    return CausalNode(
        node_id=uuid4(),
        node_type=CausalNodeType.INTENT,
        entity_id=uuid4(),
        entity_type="intent",
        timestamp=datetime.now(UTC),
        created_by="alice",
        previous_node_id=None,
        next_node_id=None,
        metadata={},
        version=1,
    )


@pytest.fixture
def sample_event_node() -> CausalNode:
    return CausalNode(
        node_id=uuid4(),
        node_type=CausalNodeType.ECONOMIC_EVENT,
        entity_id=uuid4(),
        entity_type="economic_event",
        timestamp=datetime.now(UTC),
        created_by="alice",
        previous_node_id=None,
        next_node_id=None,
        metadata={},
        version=1,
    )


@pytest.fixture
def sample_journal_node() -> CausalNode:
    return CausalNode(
        node_id=uuid4(),
        node_type=CausalNodeType.JOURNAL_ENTRY,
        entity_id=uuid4(),
        entity_type="journal",
        timestamp=datetime.now(UTC),
        created_by="alice",
        previous_node_id=None,
        next_node_id=None,
        metadata={},
        version=1,
    )


# ----------------------------------------------------------------------
# Enums
# ----------------------------------------------------------------------
class TestChainBuildStatus:
    def test_members_exist(self):
        assert hasattr(ChainBuildStatus, "SUCCESS")
        assert hasattr(ChainBuildStatus, "PARTIAL")
        assert hasattr(ChainBuildStatus, "FAILED")

    def test_member_is_instance(self):
        assert isinstance(ChainBuildStatus.SUCCESS, ChainBuildStatus)


class TestChainDirection:
    def test_members_exist(self):
        assert hasattr(ChainDirection, "FORWARD")
        assert hasattr(ChainDirection, "BACKWARD")

    def test_member_is_instance(self):
        assert isinstance(ChainDirection.FORWARD, ChainDirection)


# ----------------------------------------------------------------------
# BuildResult
# ----------------------------------------------------------------------
class TestBuildResult:
    def test_construction(self):
        nodes = [MagicMock(spec=CausalNode), MagicMock(spec=CausalNode)]
        result = BuildResult(
            status=ChainBuildStatus.SUCCESS,
            nodes=nodes,
            errors=["error1"],
            warnings=["warning1"],
            duration_ms=12.5,
        )
        assert result.status == ChainBuildStatus.SUCCESS
        assert len(result.nodes) == 2
        assert result.errors == ["error1"]
        assert result.warnings == ["warning1"]
        assert result.duration_ms == 12.5


# ----------------------------------------------------------------------
# CausalChainBuilder
# ----------------------------------------------------------------------
class TestCausalChainBuilder:
    def test_singleton(self):
        b1 = get_causal_chain_builder()
        b2 = get_causal_chain_builder()
        assert b1 is b2

    def test_initialization(self, causal_builder):
        assert causal_builder._node_service is not None
        assert causal_builder._build_history == []

    # ---- build_from_intent_to_event ----
    def test_build_from_intent_to_event_both_new(self, causal_builder, mock_node_service):
        intent_id = uuid4()
        event_id = uuid4()
        created_by = "alice"

        # Mock node creation
        intent_node = MagicMock(spec=CausalNode)
        intent_node.node_id = uuid4()
        intent_node.next_node_id = None
        event_node = MagicMock(spec=CausalNode)
        event_node.node_id = uuid4()
        event_node.previous_node_id = None
        event_node.next_node_id = None

        mock_node_service.get_node_by_entity.side_effect = [None, None]
        mock_node_service.create_node.side_effect = [intent_node, event_node]
        mock_node_service._nodes = {}  # We'll update manually

        # Mock link_to_next to return updated intent node
        updated_intent = MagicMock(spec=CausalNode)
        updated_intent.node_id = intent_node.node_id
        updated_intent.next_node_id = event_node.node_id
        intent_node.link_to_next.return_value = updated_intent

        result = causal_builder.build_from_intent_to_event(
            intent_id=intent_id,
            event_id=event_id,
            created_by=created_by,
            metadata={"source": "test"},
        )

        assert result.status == ChainBuildStatus.SUCCESS
        assert len(result.nodes) == 2
        assert result.errors == []
        assert len(result.warnings) == 2  # both nodes created automatically
        assert result.duration_ms > 0

        # Verify create_node calls
        assert mock_node_service.create_node.call_count == 2
        mock_node_service.create_node.assert_any_call(
            node_type=CausalNodeType.INTENT,
            entity_id=intent_id,
            entity_type="intent",
            created_by=created_by,
            metadata={"source": "test"},
        )
        mock_node_service.create_node.assert_any_call(
            node_type=CausalNodeType.ECONOMIC_EVENT,
            entity_id=event_id,
            entity_type="economic_event",
            created_by=created_by,
            previous_node_id=intent_node.node_id,
            metadata={"source": "test"},
        )

    def test_build_from_intent_to_event_intent_exists(self, causal_builder, mock_node_service):
        intent_id = uuid4()
        event_id = uuid4()
        created_by = "alice"

        intent_node = MagicMock(spec=CausalNode)
        intent_node.node_id = uuid4()
        intent_node.next_node_id = None
        event_node = MagicMock(spec=CausalNode)
        event_node.node_id = uuid4()
        event_node.previous_node_id = None
        event_node.next_node_id = None

        mock_node_service.get_node_by_entity.side_effect = [intent_node, None]
        mock_node_service.create_node.side_effect = [None, event_node]

        updated_intent = MagicMock(spec=CausalNode)
        updated_intent.node_id = intent_node.node_id
        updated_intent.next_node_id = event_node.node_id
        intent_node.link_to_next.return_value = updated_intent

        result = causal_builder.build_from_intent_to_event(
            intent_id=intent_id,
            event_id=event_id,
            created_by=created_by,
        )

        assert result.status == ChainBuildStatus.SUCCESS
        assert len(result.nodes) == 2
        assert len(result.warnings) == 1  # only event created automatically
        # intent_node should not have been created
        mock_node_service.create_node.assert_called_once_with(
            node_type=CausalNodeType.ECONOMIC_EVENT,
            entity_id=event_id,
            entity_type="economic_event",
            created_by=created_by,
            previous_node_id=intent_node.node_id,
            metadata={},
        )

    def test_build_from_intent_to_event_event_exists_with_wrong_prev(self, causal_builder, mock_node_service):
        intent_id = uuid4()
        event_id = uuid4()
        created_by = "alice"

        intent_node = MagicMock(spec=CausalNode)
        intent_node.node_id = uuid4()
        intent_node.next_node_id = None
        event_node = MagicMock(spec=CausalNode)
        event_node.node_id = uuid4()
        event_node.previous_node_id = uuid4()  # different parent
        event_node.next_node_id = None
        event_node.version = 1

        mock_node_service.get_node_by_entity.side_effect = [intent_node, event_node]
        mock_node_service.create_node.return_value = None

        # When we update event node, we'll return a new mock
        updated_event = MagicMock(spec=CausalNode)
        updated_event.node_id = event_node.node_id
        updated_event.previous_node_id = intent_node.node_id
        updated_event.next_node_id = None

        # Simulate the update: when we create the CausalNode in the method, we need to capture it.
        # We'll patch CausalNode constructor to return updated_event.
        with patch("domain.causality.causal_chain_builder.CausalNode") as mock_causal_node:
            mock_causal_node.return_value = updated_event

            updated_intent = MagicMock(spec=CausalNode)
            updated_intent.node_id = intent_node.node_id
            updated_intent.next_node_id = event_node.node_id
            intent_node.link_to_next.return_value = updated_intent

            result = causal_builder.build_from_intent_to_event(
                intent_id=intent_id,
                event_id=event_id,
                created_by=created_by,
            )

        assert result.status == ChainBuildStatus.SUCCESS
        assert len(result.nodes) == 2
        assert result.errors == []
        # Check that event node was updated (we need to verify the update happened)
        # The updated_event should have been stored in _nodes
        mock_node_service._nodes[event_node.node_id] = updated_event

    def test_build_from_intent_to_event_exception(self, causal_builder, mock_node_service):
        mock_node_service.get_node_by_entity.side_effect = Exception("DB error")
        result = causal_builder.build_from_intent_to_event(
            intent_id=uuid4(),
            event_id=uuid4(),
            created_by="alice",
        )
        assert result.status == ChainBuildStatus.FAILED
        assert len(result.errors) == 1
        assert "DB error" in result.errors[0]

    # ---- build_from_event_to_journal ----
    def test_build_from_event_to_journal_both_new(self, causal_builder, mock_node_service):
        event_id = uuid4()
        journal_id = uuid4()
        created_by = "bob"

        event_node = MagicMock(spec=CausalNode)
        event_node.node_id = uuid4()
        event_node.next_node_id = None
        journal_node = MagicMock(spec=CausalNode)
        journal_node.node_id = uuid4()
        journal_node.previous_node_id = None
        journal_node.next_node_id = None

        mock_node_service.get_node_by_entity.side_effect = [None, None]
        mock_node_service.create_node.side_effect = [event_node, journal_node]

        updated_event = MagicMock(spec=CausalNode)
        updated_event.node_id = event_node.node_id
        updated_event.next_node_id = journal_node.node_id
        event_node.link_to_next.return_value = updated_event

        result = causal_builder.build_from_event_to_journal(
            event_id=event_id,
            journal_id=journal_id,
            created_by=created_by,
            metadata={"reason": "test"},
        )

        assert result.status == ChainBuildStatus.SUCCESS
        assert len(result.nodes) == 2
        assert len(result.warnings) == 2  # both created
        mock_node_service.create_node.assert_any_call(
            node_type=CausalNodeType.ECONOMIC_EVENT,
            entity_id=event_id,
            entity_type="economic_event",
            created_by=created_by,
            metadata={"reason": "test"},
        )
        mock_node_service.create_node.assert_any_call(
            node_type=CausalNodeType.JOURNAL_ENTRY,
            entity_id=journal_id,
            entity_type="journal",
            created_by=created_by,
            previous_node_id=event_node.node_id,
            metadata={"reason": "test"},
        )

    def test_build_from_event_to_journal_event_exists(self, causal_builder, mock_node_service):
        event_id = uuid4()
        journal_id = uuid4()
        created_by = "bob"

        event_node = MagicMock(spec=CausalNode)
        event_node.node_id = uuid4()
        event_node.next_node_id = None
        journal_node = MagicMock(spec=CausalNode)
        journal_node.node_id = uuid4()
        journal_node.previous_node_id = None
        journal_node.next_node_id = None

        mock_node_service.get_node_by_entity.side_effect = [event_node, None]
        mock_node_service.create_node.return_value = journal_node

        updated_event = MagicMock(spec=CausalNode)
        updated_event.node_id = event_node.node_id
        updated_event.next_node_id = journal_node.node_id
        event_node.link_to_next.return_value = updated_event

        result = causal_builder.build_from_event_to_journal(
            event_id=event_id,
            journal_id=journal_id,
            created_by=created_by,
        )

        assert result.status == ChainBuildStatus.SUCCESS
        assert len(result.nodes) == 2
        assert len(result.warnings) == 1  # only journal created

    def test_build_from_event_to_journal_exception(self, causal_builder, mock_node_service):
        mock_node_service.get_node_by_entity.side_effect = Exception("Error")
        result = causal_builder.build_from_event_to_journal(
            event_id=uuid4(),
            journal_id=uuid4(),
            created_by="bob",
        )
        assert result.status == ChainBuildStatus.FAILED
        assert len(result.errors) == 1

    # ---- build_complete_chain ----
    def test_build_complete_chain_success(self, causal_builder):
        intent_id = uuid4()
        event_id = uuid4()
        journal_id = uuid4()
        created_by = "carol"

        # Mock the two build steps to return success
        # We'll patch the individual methods
        with patch.object(causal_builder, "build_from_intent_to_event") as mock_intent_event:
            with patch.object(causal_builder, "build_from_event_to_journal") as mock_event_journal:
                # Mock results
                result1 = BuildResult(
                    status=ChainBuildStatus.SUCCESS,
                    nodes=[MagicMock(spec=CausalNode), MagicMock(spec=CausalNode)],
                    errors=[],
                    warnings=["warning1"],
                    duration_ms=10.0,
                )
                result2 = BuildResult(
                    status=ChainBuildStatus.SUCCESS,
                    nodes=[MagicMock(spec=CausalNode), MagicMock(spec=CausalNode)],
                    errors=[],
                    warnings=[],
                    duration_ms=5.0,
                )
                mock_intent_event.return_value = result1
                mock_event_journal.return_value = result2

                # Mock get_full_chain to return a combined chain
                full_chain = [MagicMock(spec=CausalNode) for _ in range(4)]
                causal_builder._node_service.get_full_chain.return_value = full_chain

                result = causal_builder.build_complete_chain(
                    intent_id=intent_id,
                    event_id=event_id,
                    journal_id=journal_id,
                    created_by=created_by,
                    metadata={"complete": True},
                )

                assert result.status == ChainBuildStatus.SUCCESS
                assert len(result.nodes) == 4
                assert result.errors == []
                assert len(result.warnings) == 1
                mock_intent_event.assert_called_once_with(intent_id, event_id, created_by, {"complete": True})
                mock_event_journal.assert_called_once_with(event_id, journal_id, created_by, {"complete": True})

    def test_build_complete_chain_with_errors(self, causal_builder):
        intent_id = uuid4()
        event_id = uuid4()
        journal_id = uuid4()
        created_by = "carol"

        with patch.object(causal_builder, "build_from_intent_to_event") as mock_intent_event:
            with patch.object(causal_builder, "build_from_event_to_journal") as mock_event_journal:
                result1 = BuildResult(
                    status=ChainBuildStatus.FAILED,
                    nodes=[],
                    errors=["intent_event failed"],
                    warnings=[],
                    duration_ms=10.0,
                )
                result2 = BuildResult(
                    status=ChainBuildStatus.SUCCESS,
                    nodes=[MagicMock(spec=CausalNode)],
                    errors=[],
                    warnings=[],
                    duration_ms=5.0,
                )
                mock_intent_event.return_value = result1
                mock_event_journal.return_value = result2

                full_chain = [MagicMock(spec=CausalNode) for _ in range(2)]
                causal_builder._node_service.get_full_chain.return_value = full_chain

                result = causal_builder.build_complete_chain(
                    intent_id=intent_id,
                    event_id=event_id,
                    journal_id=journal_id,
                    created_by=created_by,
                )

                assert result.status == ChainBuildStatus.FAILED
                assert "intent_event failed" in result.errors

    # ---- build_reversal_chain ----
    def test_build_reversal_chain_success(self, causal_builder, mock_node_service):
        original_journal_id = uuid4()
        reversal_journal_id = uuid4()
        created_by = "dave"

        original_node = MagicMock(spec=CausalNode)
        original_node.node_id = uuid4()
        original_node.next_node_id = None
        reversal_node = MagicMock(spec=CausalNode)
        reversal_node.node_id = uuid4()
        reversal_node.previous_node_id = None
        reversal_node.next_node_id = None

        mock_node_service.get_node_by_entity.side_effect = [None, None]
        mock_node_service.create_node.side_effect = [original_node, reversal_node]

        updated_original = MagicMock(spec=CausalNode)
        updated_original.node_id = original_node.node_id
        updated_original.next_node_id = reversal_node.node_id
        original_node.link_to_next.return_value = updated_original

        full_chain = [original_node, reversal_node]
        mock_node_service.get_full_chain.return_value = full_chain

        result = causal_builder.build_reversal_chain(
            original_journal_id=original_journal_id,
            reversal_journal_id=reversal_journal_id,
            created_by=created_by,
            reason="Correction",
            metadata={"source": "audit"},
        )

        assert result.status == ChainBuildStatus.SUCCESS
        assert len(result.nodes) == 2
        assert result.errors == []
        # Check create_node calls
        mock_node_service.create_node.assert_any_call(
            node_type=CausalNodeType.JOURNAL_ENTRY,
            entity_id=original_journal_id,
            entity_type="journal",
            created_by=created_by,
        )
        mock_node_service.create_node.assert_any_call(
            node_type=CausalNodeType.REVERSAL,
            entity_id=reversal_journal_id,
            entity_type="journal",
            created_by=created_by,
            previous_node_id=original_node.node_id,
            metadata={
                "reversal_reason": "Correction",
                "original_journal_id": str(original_journal_id),
                "source": "audit",
            },
        )

    def test_build_reversal_chain_reversal_exists_wrong_prev(self, causal_builder, mock_node_service):
        original_journal_id = uuid4()
        reversal_journal_id = uuid4()
        created_by = "dave"

        original_node = MagicMock(spec=CausalNode)
        original_node.node_id = uuid4()
        original_node.next_node_id = None
        reversal_node = MagicMock(spec=CausalNode)
        reversal_node.node_id = uuid4()
        reversal_node.previous_node_id = uuid4()  # different
        reversal_node.next_node_id = None
        reversal_node.version = 1

        mock_node_service.get_node_by_entity.side_effect = [original_node, reversal_node]
        mock_node_service.create_node.return_value = None

        updated_reversal = MagicMock(spec=CausalNode)
        updated_reversal.node_id = reversal_node.node_id
        updated_reversal.previous_node_id = original_node.node_id

        with patch("domain.causality.causal_chain_builder.CausalNode") as mock_causal_node:
            mock_causal_node.return_value = updated_reversal

            updated_original = MagicMock(spec=CausalNode)
            updated_original.node_id = original_node.node_id
            updated_original.next_node_id = reversal_node.node_id
            original_node.link_to_next.return_value = updated_original

            full_chain = [original_node, updated_reversal]
            mock_node_service.get_full_chain.return_value = full_chain

            result = causal_builder.build_reversal_chain(
                original_journal_id=original_journal_id,
                reversal_journal_id=reversal_journal_id,
                created_by=created_by,
                reason="Update",
            )

        assert result.status == ChainBuildStatus.SUCCESS
        assert len(result.nodes) == 2

    def test_build_reversal_chain_exception(self, causal_builder, mock_node_service):
        mock_node_service.get_node_by_entity.side_effect = Exception("Error")
        result = causal_builder.build_reversal_chain(
            original_journal_id=uuid4(),
            reversal_journal_id=uuid4(),
            created_by="dave",
        )
        assert result.status == ChainBuildStatus.FAILED
        assert len(result.errors) == 1

    # ---- build_adjustment_chain ----
    def test_build_adjustment_chain_success(self, causal_builder, mock_node_service):
        original_event_id = uuid4()
        adjustment_event_id = uuid4()
        created_by = "eve"

        original_node = MagicMock(spec=CausalNode)
        original_node.node_id = uuid4()
        original_node.next_node_id = None
        adjustment_node = MagicMock(spec=CausalNode)
        adjustment_node.node_id = uuid4()
        adjustment_node.previous_node_id = None
        adjustment_node.next_node_id = None

        mock_node_service.get_node_by_entity.side_effect = [None, None]
        mock_node_service.create_node.side_effect = [original_node, adjustment_node]

        updated_original = MagicMock(spec=CausalNode)
        updated_original.node_id = original_node.node_id
        updated_original.next_node_id = adjustment_node.node_id
        original_node.link_to_next.return_value = updated_original

        full_chain = [original_node, adjustment_node]
        mock_node_service.get_full_chain.return_value = full_chain

        result = causal_builder.build_adjustment_chain(
            original_event_id=original_event_id,
            adjustment_event_id=adjustment_event_id,
            created_by=created_by,
            reason="Correction",
            metadata={"source": "review"},
        )

        assert result.status == ChainBuildStatus.SUCCESS
        assert len(result.nodes) == 2
        mock_node_service.create_node.assert_any_call(
            node_type=CausalNodeType.ADJUSTMENT,
            entity_id=adjustment_event_id,
            entity_type="economic_event",
            created_by=created_by,
            previous_node_id=original_node.node_id,
            metadata={
                "adjustment_reason": "Correction",
                "original_event_id": str(original_event_id),
                "source": "review",
            },
        )

    def test_build_adjustment_chain_exception(self, causal_builder, mock_node_service):
        mock_node_service.get_node_by_entity.side_effect = Exception("Error")
        result = causal_builder.build_adjustment_chain(
            original_event_id=uuid4(),
            adjustment_event_id=uuid4(),
            created_by="eve",
        )
        assert result.status == ChainBuildStatus.FAILED

    # ---- get_traceability_report ----
    def test_get_traceability_report_found(self, causal_builder, mock_node_service):
        entity_id = uuid4()
        entity_type = "journal"
        node = MagicMock(spec=CausalNode)
        node.node_id = uuid4()
        node.entity_id = entity_id
        node.entity_type = entity_type
        node.timestamp = datetime.now(UTC)
        node.created_by = "alice"
        node.metadata = {}
        node.node_type = CausalNodeType.JOURNAL_ENTRY

        chain_nodes = [
            MagicMock(spec=CausalNode, node_id=uuid4(), node_type=CausalNodeType.INTENT, entity_id=uuid4(), entity_type="intent", timestamp=datetime.now(UTC), created_by="alice", metadata={}),
            node,
            MagicMock(spec=CausalNode, node_id=uuid4(), node_type=CausalNodeType.ECONOMIC_EVENT, entity_id=uuid4(), entity_type="economic_event", timestamp=datetime.now(UTC), created_by="alice", metadata={}),
        ]
        # Set node versions
        for n in chain_nodes:
            n.node_type = n.node_type or CausalNodeType.JOURNAL_ENTRY

        mock_node_service.get_node_by_entity.return_value = node
        mock_node_service.get_full_chain.return_value = chain_nodes

        report = causal_builder.get_traceability_report(entity_id, entity_type)

        assert "error" not in report
        assert report["target_entity_id"] == str(entity_id)
        assert report["target_entity_type"] == entity_type
        assert report["chain_length"] == 3
        assert len(report["chain"]) == 3
        assert "root_cause" in report
        assert "final_outcome" in report

    def test_get_traceability_report_not_found(self, causal_builder, mock_node_service):
        mock_node_service.get_node_by_entity.return_value = None
        report = causal_builder.get_traceability_report(uuid4(), "intent")
        assert "error" in report
        assert "Node not found" in report["error"]

    # ---- get_root_cause ----
    def test_get_root_cause_found(self, causal_builder, mock_node_service):
        entity_id = uuid4()
        entity_type = "journal"
        node = MagicMock(spec=CausalNode)
        node.node_id = uuid4()
        root_node = MagicMock(spec=CausalNode)
        root_node.entity_id = uuid4()
        root_node.entity_type = "intent"
        root_node.node_type = CausalNodeType.INTENT
        root_node.timestamp = datetime.now(UTC)
        root_node.created_by = "alice"

        mock_node_service.get_node_by_entity.return_value = node
        mock_node_service.get_full_chain.return_value = [root_node, node]

        result = causal_builder.get_root_cause(entity_id, entity_type)
        assert result is not None
        assert result["entity_id"] == str(root_node.entity_id)
        assert result["entity_type"] == "intent"

    def test_get_root_cause_not_found(self, causal_builder, mock_node_service):
        mock_node_service.get_node_by_entity.return_value = None
        assert causal_builder.get_root_cause(uuid4(), "intent") is None

    # ---- get_impact_chain ----
    def test_get_impact_chain(self, causal_builder, mock_node_service):
        entity_id = uuid4()
        entity_type = "intent"
        node = MagicMock(spec=CausalNode)
        node.node_id = uuid4()
        descendants = [
            MagicMock(spec=CausalNode, entity_id=uuid4(), entity_type="economic_event", node_type=CausalNodeType.ECONOMIC_EVENT),
            MagicMock(spec=CausalNode, entity_id=uuid4(), entity_type="journal", node_type=CausalNodeType.JOURNAL_ENTRY),
        ]
        mock_node_service.get_node_by_entity.return_value = node
        mock_node_service.get_descendants.return_value = descendants

        impact = causal_builder.get_impact_chain(entity_id, entity_type)
        assert len(impact) == 2
        assert impact[0]["entity_type"] == "economic_event"
        assert impact[0]["distance"] == 1
        assert impact[1]["entity_type"] == "journal"
        assert impact[1]["distance"] == 2

    def test_get_impact_chain_not_found(self, causal_builder, mock_node_service):
        mock_node_service.get_node_by_entity.return_value = None
        assert causal_builder.get_impact_chain(uuid4(), "intent") == []

    # ---- validate_chain_completeness ----
    def test_validate_chain_completeness_valid(self, causal_builder, mock_node_service):
        entity_id = uuid4()
        entity_type = "intent"
        node = MagicMock(spec=CausalNode)
        node.node_id = uuid4()
        node.next_node_id = uuid4()
        node.previous_node_id = None

        chain = [
            node,
            MagicMock(spec=CausalNode, node_id=uuid4(), previous_node_id=node.node_id, next_node_id=uuid4()),
        ]
        # Fix relationships
        chain[0].next_node_id = chain[1].node_id
        chain[1].previous_node_id = chain[0].node_id

        mock_node_service.get_node_by_entity.return_value = node
        mock_node_service.get_full_chain.return_value = chain

        result = causal_builder.validate_chain_completeness(entity_id, entity_type)
        assert result["valid"] is True
        assert result["chain_length"] == 2
        assert result["broken_links"] == []

    def test_validate_chain_completeness_broken(self, causal_builder, mock_node_service):
        entity_id = uuid4()
        entity_type = "intent"
        node = MagicMock(spec=CausalNode)
        node.node_id = uuid4()
        node.next_node_id = uuid4()  # wrong next
        node.previous_node_id = None

        node2 = MagicMock(spec=CausalNode)
        node2.node_id = uuid4()
        node2.previous_node_id = uuid4()  # wrong prev
        node2.next_node_id = None

        mock_node_service.get_node_by_entity.return_value = node
        mock_node_service.get_full_chain.return_value = [node, node2]

        result = causal_builder.validate_chain_completeness(entity_id, entity_type)
        assert result["valid"] is False
        assert result["chain_length"] == 2
        assert len(result["broken_links"]) == 2

    def test_validate_chain_completeness_not_found(self, causal_builder, mock_node_service):
        mock_node_service.get_node_by_entity.return_value = None
        result = causal_builder.validate_chain_completeness(uuid4(), "intent")
        assert result["valid"] is False
        assert result["reason"] == "Node not found"

    # ---- record_build and history ----
    def test_record_build(self, causal_builder):
        result = BuildResult(
            status=ChainBuildStatus.SUCCESS,
            nodes=[MagicMock(spec=CausalNode)],
            errors=[],
            warnings=[],
            duration_ms=10.0,
        )
        causal_builder.record_build("test_build", result, {"key": "value"})
        assert len(causal_builder._build_history) == 1
        record = causal_builder._build_history[0]
        assert record["build_type"] == "test_build"
        assert record["status"] == "success"
        assert record["nodes_count"] == 1
        assert record["params"] == {"key": "value"}

    def test_get_build_history(self, causal_builder):
        for i in range(5):
            result = BuildResult(
                status=ChainBuildStatus.SUCCESS,
                nodes=[],
                errors=[],
                warnings=[],
                duration_ms=float(i),
            )
            causal_builder.record_build(f"build_{i}", result, {})
        history = causal_builder.get_build_history(limit=3)
        assert len(history) == 3
        # Should return latest 3
        assert history[0]["build_type"] == "build_4"
        assert history[2]["build_type"] == "build_2"

    # ---- get_statistics ----
    def test_get_statistics_empty(self, causal_builder):
        stats = causal_builder.get_statistics()
        assert stats["total_builds"] == 0

    def test_get_statistics_with_builds(self, causal_builder):
        # Add builds
        for status in [ChainBuildStatus.SUCCESS, ChainBuildStatus.SUCCESS, ChainBuildStatus.FAILED]:
            result = BuildResult(
                status=status,
                nodes=[],
                errors=[] if status == ChainBuildStatus.SUCCESS else ["error"],
                warnings=[],
                duration_ms=10.0,
            )
            causal_builder.record_build("test", result, {})
        # Mock node_service statistics
        causal_builder._node_service.get_statistics.return_value = {"total_nodes": 5}

        stats = causal_builder.get_statistics()
        assert stats["total_builds"] == 3
        assert stats["by_status"] == {"success": 2, "failed": 1}
        assert stats["average_duration_ms"] == 10.0
        assert stats["node_service_stats"] == {"total_nodes": 5}

    # ---- reset ----
    def test_reset(self, causal_builder):
        result = BuildResult(
            status=ChainBuildStatus.SUCCESS,
            nodes=[],
            errors=[],
            warnings=[],
            duration_ms=10.0,
        )
        causal_builder.record_build("test", result, {})
        assert len(causal_builder._build_history) == 1
        causal_builder.reset()
        assert len(causal_builder._build_history) == 0
        causal_builder._node_service.reset.assert_called_once()