# test_explanation_generator.py
# ==============================
# Comprehensive tests for domain/causality/explanation_generator.py.
# Covers all enums, data classes, generator methods, and FullExplanation.to_html.

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from domain.causality.explanation_generator import (
    ExplanationFormat,
    ExplanationGenerator,
    ExplanationLanguage,
    ExplanationLevel,
    ExplanationSegment,
    FullExplanation,
    get_explanation_generator,
)


# ----------------------------------------------------------------------
# Enums
# ----------------------------------------------------------------------
class TestExplanationLevel:
    def test_members_exist(self):
        assert hasattr(ExplanationLevel, "SUMMARY")
        assert hasattr(ExplanationLevel, "STANDARD")
        assert hasattr(ExplanationLevel, "DETAILED")
        assert hasattr(ExplanationLevel, "FORENSIC")

    def test_member_is_instance(self):
        assert isinstance(ExplanationLevel.SUMMARY, ExplanationLevel)


class TestExplanationLanguage:
    def test_members_exist(self):
        assert hasattr(ExplanationLanguage, "ENGLISH")
        assert hasattr(ExplanationLanguage, "INDONESIAN")

    def test_member_is_instance(self):
        assert isinstance(ExplanationLanguage.ENGLISH, ExplanationLanguage)


class TestExplanationFormat:
    def test_members_exist(self):
        assert hasattr(ExplanationFormat, "TEXT")
        assert hasattr(ExplanationFormat, "JSON")
        assert hasattr(ExplanationFormat, "HTML")

    def test_member_is_instance(self):
        assert isinstance(ExplanationFormat.TEXT, ExplanationFormat)


# ----------------------------------------------------------------------
# ExplanationSegment
# ----------------------------------------------------------------------
class TestExplanationSegment:
    def test_construction(self):
        segment = ExplanationSegment(
            step_number=1,
            node_type="INTENT",
            entity_type="intent",
            entity_id="abc-123",
            timestamp="2025-01-01T00:00:00",
            created_by="alice",
            explanation_text="Test explanation",
            metadata={"key": "value"},
        )
        assert segment.step_number == 1
        assert segment.node_type == "INTENT"
        assert segment.explanation_text == "Test explanation"
        assert segment.metadata == {"key": "value"}

    def test_to_dict(self):
        segment = ExplanationSegment(
            step_number=2,
            node_type="ECONOMIC_EVENT",
            entity_type="event",
            entity_id="xyz-789",
            timestamp="2025-01-02T00:00:00",
            created_by="bob",
            explanation_text="Event explanation",
            metadata={"foo": "bar"},
        )
        d = segment.to_dict()
        assert d["step_number"] == 2
        assert d["node_type"] == "ECONOMIC_EVENT"
        assert d["explanation_text"] == "Event explanation"
        assert d["metadata"] == {"foo": "bar"}


# ----------------------------------------------------------------------
# FullExplanation
# ----------------------------------------------------------------------
class TestFullExplanation:
    @pytest.fixture
    def full_explanation(self) -> FullExplanation:
        segments = [
            ExplanationSegment(
                step_number=1,
                node_type="INTENT",
                entity_type="intent",
                entity_id="int-123",
                timestamp="2025-01-01T10:00:00",
                created_by="alice",
                explanation_text="Intent created",
            ),
            ExplanationSegment(
                step_number=2,
                node_type="ECONOMIC_EVENT",
                entity_type="event",
                entity_id="evt-456",
                timestamp="2025-01-01T11:00:00",
                created_by="bob",
                explanation_text="Event recognized",
            ),
        ]
        return FullExplanation(
            target_entity_id="target-001",
            target_entity_type="journal",
            generated_at="2025-01-01T12:00:00",
            generated_by="system",
            level="standard",
            language="en",
            summary="This is a summary",
            segments=segments,
            root_cause={"entity_type": "intent", "entity_id": "int-123", "timestamp": "2025-01-01T10:00:00"},
            final_outcome={"entity_type": "journal", "entity_id": "jrn-789", "timestamp": "2025-01-01T13:00:00"},
        )

    def test_to_dict(self, full_explanation):
        d = full_explanation.to_dict()
        assert d["target_entity_id"] == "target-001"
        assert d["target_entity_type"] == "journal"
        assert d["summary"] == "This is a summary"
        assert len(d["segments"]) == 2
        assert d["root_cause"]["entity_type"] == "intent"
        assert d["final_outcome"]["entity_type"] == "journal"

    def test_to_json(self, full_explanation):
        json_str = full_explanation.to_json()
        import json
        data = json.loads(json_str)
        assert data["target_entity_id"] == "target-001"
        assert data["summary"] == "This is a summary"

    def test_to_html(self, full_explanation):
        """Test FullExplanation.to_html method - this was untested."""
        html = full_explanation.to_html()
        assert "<html>" in html
        assert "<title>Explanation for journal target-001</title>" in html
        assert "<h1>Causal Explanation</h1>" in html
        assert "<p><strong>Target:</strong> journal target-001</p>" in html
        assert "<p><strong>Generated:</strong> 2025-01-01T12:00:00 by system</p>" in html
        assert "<p><strong>Level:</strong> standard | <strong>Language:</strong> en</p>" in html
        assert "<h2>Summary</h2>" in html
        assert "<p>This is a summary</p>" in html
        assert "<h2>Detailed Steps</h2>" in html
        # Check segments
        assert "Step 1: Intent created" in html
        assert "Step 2: Event recognized" in html
        # Check metadata
        assert "<span class=\"metadata\">Node: INTENT | Entity: intent int-123 | Time: 2025-01-01T10:00:00 | By: alice</span>" in html
        # Check root cause and final outcome
        assert "<h2>Root Cause</h2>" in html
        assert "<p>intent int-123 at 2025-01-01T10:00:00</p>" in html
        assert "<h2>Final Outcome</h2>" in html
        assert "<p>journal jrn-789 at 2025-01-01T13:00:00</p>" in html
        assert "</html>" in html

    def test_to_html_no_root_cause_or_outcome(self):
        """Test to_html when root_cause and final_outcome are None."""
        segments = [
            ExplanationSegment(
                step_number=1,
                node_type="INTENT",
                entity_type="intent",
                entity_id="int-123",
                timestamp="2025-01-01T10:00:00",
                created_by="alice",
                explanation_text="Intent created",
            )
        ]
        explanation = FullExplanation(
            target_entity_id="target-001",
            target_entity_type="journal",
            generated_at="2025-01-01T12:00:00",
            generated_by="system",
            level="standard",
            language="en",
            summary="Simple summary",
            segments=segments,
            root_cause=None,
            final_outcome=None,
        )
        html = explanation.to_html()
        assert "<h2>Root Cause</h2>" not in html
        assert "<h2>Final Outcome</h2>" not in html
        assert "Step 1: Intent created" in html


# ----------------------------------------------------------------------
# ExplanationGenerator (requires mocking of dependencies)
# ----------------------------------------------------------------------
class TestExplanationGenerator:
    @pytest.fixture
    def generator(self):
        ExplanationGenerator._instance = None
        gen = ExplanationGenerator()
        # Mock dependencies
        gen._chain_builder = MagicMock()
        gen._node_service = MagicMock()
        return gen

    def test_singleton(self):
        g1 = get_explanation_generator()
        g2 = get_explanation_generator()
        assert g1 is g2
        g1.reset()
        ExplanationGenerator._instance = None

    def test_generate_explanation_error(self, generator):
        # Simulate error in traceability report
        generator._chain_builder.get_traceability_report.return_value = {"error": "Node not found"}
        result = generator.generate_explanation(
            entity_id=uuid4(),
            entity_type="journal",
            generated_by="system",
            level=ExplanationLevel.STANDARD,
            language=ExplanationLanguage.ENGLISH,
            output_format=ExplanationFormat.TEXT,
        )
        assert "Unable to generate explanation: Node not found" in result

        # With JSON format (returns FullExplanation)
        result_full = generator.generate_explanation(
            entity_id=uuid4(),
            entity_type="journal",
            generated_by="system",
            output_format=ExplanationFormat.JSON,
        )
        assert isinstance(result_full, FullExplanation)
        assert "Unable to generate explanation: Node not found" in result_full.summary

    def test_generate_explanation_no_chain(self, generator):
        generator._chain_builder.get_traceability_report.return_value = {"chain": []}
        result = generator.generate_explanation(
            entity_id=uuid4(),
            entity_type="journal",
            generated_by="system",
            output_format=ExplanationFormat.TEXT,
        )
        assert "No causal chain found" in result

    def test_generate_explanation_success_text(self, generator):
        # Mock trace with chain
        chain = [
            {
                "node_type": "INTENT",
                "entity_type": "intent",
                "entity_id": "int-123",
                "timestamp": "2025-01-01T10:00:00",
                "created_by": "alice",
                "metadata": {},
            },
            {
                "node_type": "ECONOMIC_EVENT",
                "entity_type": "event",
                "entity_id": "evt-456",
                "timestamp": "2025-01-01T11:00:00",
                "created_by": "bob",
                "metadata": {},
            },
        ]
        trace = {
            "chain": chain,
            "root_cause": {"entity_type": "intent", "entity_id": "int-123", "timestamp": "2025-01-01T10:00:00"},
            "final_outcome": {"entity_type": "journal", "entity_id": "jrn-789", "timestamp": "2025-01-01T13:00:00"},
        }
        generator._chain_builder.get_traceability_report.return_value = trace

        result = generator.generate_explanation(
            entity_id=uuid4(),
            entity_type="journal",
            generated_by="system",
            level=ExplanationLevel.STANDARD,
            language=ExplanationLanguage.ENGLISH,
            output_format=ExplanationFormat.TEXT,
        )
        assert "CAUSAL EXPLANATION FOR JOURNAL" in result
        assert "SUMMARY" in result
        assert "DETAILED STEPS" in result
        assert "Step 1: Intent created" in result
        assert "Step 2: Economic event recognized" in result
        assert "ROOT CAUSE" in result
        assert "FINAL OUTCOME" in result

    def test_generate_explanation_success_html(self, generator):
        chain = [
            {
                "node_type": "INTENT",
                "entity_type": "intent",
                "entity_id": "int-123",
                "timestamp": "2025-01-01T10:00:00",
                "created_by": "alice",
                "metadata": {},
            }
        ]
        trace = {"chain": chain, "root_cause": {}, "final_outcome": {}}
        generator._chain_builder.get_traceability_report.return_value = trace

        result = generator.generate_explanation(
            entity_id=uuid4(),
            entity_type="journal",
            generated_by="system",
            output_format=ExplanationFormat.HTML,
        )
        assert isinstance(result, str)
        assert "<html>" in result
        assert "<h1>Causal Explanation</h1>" in result

    def test_generate_why_explanation(self, generator):
        generator._chain_builder.get_traceability_report.return_value = {
            "chain": [{"node_type": "INTENT"}],
            "root_cause": {"entity_type": "intent", "entity_id": "int-123", "timestamp": "2025-01-01T10:00:00"},
        }
        result = generator.generate_why_explanation(
            entity_id=uuid4(),
            entity_type="journal",
            generated_by="system",
            language=ExplanationLanguage.ENGLISH,
        )
        assert "occurred because of intent int-123" in result

    def test_generate_what_if_explanation(self, generator):
        generator._chain_builder.get_impact_chain.return_value = [{"entity_id": "evt-456"}]
        result = generator.generate_what_if_explanation(
            entity_id=uuid4(),
            entity_type="journal",
            hypothetical_change="change amount",
            generated_by="system",
        )
        assert "affect 1 downstream entities" in result

    def test_get_history(self, generator):
        assert generator.get_history() == []
        # Generate one explanation (needs proper mocks)
        generator._chain_builder.get_traceability_report.return_value = {"chain": []}
        generator.generate_explanation(
            entity_id=uuid4(),
            entity_type="journal",
            generated_by="system",
            output_format=ExplanationFormat.JSON,
        )
        history = generator.get_history()
        assert len(history) == 1
        assert isinstance(history[0], FullExplanation)

    def test_get_statistics(self, generator):
        stats = generator.get_statistics()
        assert stats["total_explanations"] == 0
        # Generate some explanations
        generator._chain_builder.get_traceability_report.return_value = {"chain": []}
        for _ in range(3):
            generator.generate_explanation(
                entity_id=uuid4(),
                entity_type="journal",
                generated_by="system",
                output_format=ExplanationFormat.JSON,
            )
        stats = generator.get_statistics()
        assert stats["total_explanations"] == 3
        assert stats["by_level"]["standard"] == 3
        assert stats["by_language"]["en"] == 3

    def test_reset(self, generator):
        generator._chain_builder.get_traceability_report.return_value = {"chain": []}
        generator.generate_explanation(
            entity_id=uuid4(),
            entity_type="journal",
            generated_by="system",
            output_format=ExplanationFormat.JSON,
        )
        assert len(generator._history) == 1
        generator.reset()
        assert len(generator._history) == 0
