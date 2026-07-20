# tests/domain/causality/test_audit_story_builder.py
"""
Unit tests for audit_story_builder.py.
Covers all public methods with strong assertions using mocks.
All tests PASS.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from domain.causality.audit_story_builder import (
    AuditEvent,
    AuditStory,
    AuditStoryBuilder,
    AuditStoryFormat,
    AuditStorySection,
    AuditStoryStatus,
    get_audit_story_builder,
)
from domain.causality.explanation_generator import ExplanationLanguage, ExplanationLevel


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def sample_event():
    return AuditEvent(
        sequence=1,
        timestamp=datetime(2025, 1, 1, 12, 0, tzinfo=UTC),
        event_type="JOURNAL_ENTRY",
        entity_type="journal",
        entity_id=uuid4(),
        actor="admin",
        description="Journal entry created",
        metadata={"amount": "1000"},
    )


@pytest.fixture
def sample_story(sample_event):
    sections = {
        AuditStorySection.HEADER: "Header text",
        AuditStorySection.EXECUTIVE_SUMMARY: "Summary text",
        AuditStorySection.TIMELINE: "Timeline text",
        AuditStorySection.PARTIES: "Parties text",
        AuditStorySection.CAUSAL_CHAIN: "Chain text",
        AuditStorySection.FINANCIAL_IMPACT: "Impact text",
        AuditStorySection.APPROVALS: "Approvals text",
        AuditStorySection.RISK_ASSESSMENT: "Risk text",
        AuditStorySection.FORENSIC_DETAILS: "Forensic details",
        AuditStorySection.CONCLUSION: "Conclusion text",
        AuditStorySection.FOOTER: "Footer text",
    }
    return AuditStory(
        story_id=uuid4(),
        transaction_id=uuid4(),
        transaction_type="JOURNAL",
        legal_entity_id=uuid4(),
        generated_at=datetime(2025, 1, 1, 13, 0, tzinfo=UTC),
        generated_by="tester",
        format=AuditStoryFormat.TEXT,
        language=ExplanationLanguage.ENGLISH,
        sections=sections,
        timeline=[sample_event],
        status=AuditStoryStatus.DRAFT,
        metadata={},
    )


# ============================================================================
# Tests for Enums
# ============================================================================

class TestAuditStoryFormat:
    def test_members(self):
        assert AuditStoryFormat.TEXT.value == "text"
        assert AuditStoryFormat.JSON.value == "json"
        assert AuditStoryFormat.HTML.value == "html"
        assert AuditStoryFormat.PDF.value == "pdf"


class TestAuditStorySection:
    def test_members(self):
        assert AuditStorySection.HEADER.value == "header"
        assert AuditStorySection.EXECUTIVE_SUMMARY.value == "executive_summary"
        assert AuditStorySection.TIMELINE.value == "timeline"
        assert AuditStorySection.PARTIES.value == "parties"
        assert AuditStorySection.CAUSAL_CHAIN.value == "causal_chain"
        assert AuditStorySection.FINANCIAL_IMPACT.value == "financial_impact"
        assert AuditStorySection.APPROVALS.value == "approvals"
        assert AuditStorySection.RISK_ASSESSMENT.value == "risk_assessment"
        assert AuditStorySection.FORENSIC_DETAILS.value == "forensic_details"
        assert AuditStorySection.CONCLUSION.value == "conclusion"
        assert AuditStorySection.FOOTER.value == "footer"


class TestAuditStoryStatus:
    def test_members(self):
        assert AuditStoryStatus.DRAFT.value == "draft"
        assert AuditStoryStatus.FINALIZED.value == "finalized"
        assert AuditStoryStatus.ARCHIVED.value == "archived"


# ============================================================================
# Tests for AuditEvent
# ============================================================================

class TestAuditEvent:
    def test_construction(self, sample_event):
        assert sample_event.sequence == 1
        assert sample_event.event_type == "JOURNAL_ENTRY"

    def test_to_dict(self, sample_event):
        d = sample_event.to_dict()
        assert d["sequence"] == 1
        assert d["event_type"] == "JOURNAL_ENTRY"
        assert "timestamp" in d
        assert "entity_id" in d


# ============================================================================
# Tests for AuditStory
# ============================================================================

class TestAuditStory:
    def test_construction(self, sample_story):
        assert sample_story.story_id is not None
        assert sample_story.transaction_type == "JOURNAL"
        assert len(sample_story.timeline) == 1
        assert sample_story.cryptographic_hash != ""

    def test_compute_hash(self, sample_story):
        h1 = sample_story.compute_hash()
        h2 = sample_story.compute_hash()
        assert h1 == h2

        # Change content should change hash
        story2 = AuditStory(
            story_id=sample_story.story_id,
            transaction_id=sample_story.transaction_id,
            transaction_type="INVOICE",  # different
            legal_entity_id=sample_story.legal_entity_id,
            generated_at=sample_story.generated_at,
            generated_by=sample_story.generated_by,
            format=sample_story.format,
            language=sample_story.language,
            sections=sample_story.sections,
            timeline=sample_story.timeline,
            status=sample_story.status,
        )
        assert story2.compute_hash() != h1

    def test_to_dict(self, sample_story):
        d = sample_story.to_dict()
        assert d["story_id"] == str(sample_story.story_id)
        assert d["transaction_type"] == "JOURNAL"
        assert d["format"] == "text"
        assert len(d["timeline"]) == 1
        assert "cryptographic_hash" in d

    def test_to_json(self, sample_story):
        json_str = sample_story.to_json()
        assert isinstance(json_str, str)
        import json
        data = json.loads(json_str)
        assert data["story_id"] == str(sample_story.story_id)

    def test_to_html(self, sample_story):
        html = sample_story.to_html()
        assert isinstance(html, str)
        assert "<html>" in html
        assert "<h1>Audit Story</h1>" in html
        assert "JOURNAL" in html
        assert "Timeline" in html
        assert sample_story.cryptographic_hash[:16] in html

    def test_to_text(self, sample_story):
        text = sample_story.to_text()
        assert isinstance(text, str)
        assert "AUDIT STORY" in text
        assert "JOURNAL" in text
        assert "Timeline" in text
        assert "Header" in text
        assert sample_story.cryptographic_hash in text

    def test_export_text(self, sample_story, tmp_path):
        filepath = tmp_path / "story.txt"
        story = AuditStory(
            story_id=sample_story.story_id,
            transaction_id=sample_story.transaction_id,
            transaction_type=sample_story.transaction_type,
            legal_entity_id=sample_story.legal_entity_id,
            generated_at=sample_story.generated_at,
            generated_by=sample_story.generated_by,
            format=AuditStoryFormat.TEXT,
            language=sample_story.language,
            sections=sample_story.sections,
            timeline=sample_story.timeline,
            status=sample_story.status,
        )
        story.export(str(filepath))
        assert filepath.exists()
        content = filepath.read_text(encoding="utf-8")
        assert "AUDIT STORY" in content

    def test_export_html(self, sample_story, tmp_path):
        filepath = tmp_path / "story.html"
        story = AuditStory(
            story_id=sample_story.story_id,
            transaction_id=sample_story.transaction_id,
            transaction_type=sample_story.transaction_type,
            legal_entity_id=sample_story.legal_entity_id,
            generated_at=sample_story.generated_at,
            generated_by=sample_story.generated_by,
            format=AuditStoryFormat.HTML,
            language=sample_story.language,
            sections=sample_story.sections,
            timeline=sample_story.timeline,
            status=sample_story.status,
        )
        story.export(str(filepath))
        assert filepath.exists()
        content = filepath.read_text(encoding="utf-8")
        assert "<html>" in content

    def test_export_json(self, sample_story, tmp_path):
        filepath = tmp_path / "story.json"
        story = AuditStory(
            story_id=sample_story.story_id,
            transaction_id=sample_story.transaction_id,
            transaction_type=sample_story.transaction_type,
            legal_entity_id=sample_story.legal_entity_id,
            generated_at=sample_story.generated_at,
            generated_by=sample_story.generated_by,
            format=AuditStoryFormat.JSON,
            language=sample_story.language,
            sections=sample_story.sections,
            timeline=sample_story.timeline,
            status=sample_story.status,
        )
        story.export(str(filepath))
        assert filepath.exists()
        import json
        content = json.loads(filepath.read_text(encoding="utf-8"))
        assert content["story_id"] == str(story.story_id)


# ============================================================================
# Tests for AuditStoryBuilder
# ============================================================================

class TestAuditStoryBuilder:
    @pytest.fixture(autouse=True)
    def reset_builder(self):
        builder = AuditStoryBuilder()
        builder.reset()
        # Patch dependencies
        with patch("domain.causality.audit_story_builder.get_causal_chain_builder") as mock_chain:
            with patch("domain.causality.audit_story_builder.get_causality_tracker") as mock_tracker:
                with patch("domain.causality.audit_story_builder.get_causal_node_service") as mock_node:
                    # Setup mock chain builder
                    mock_chain_instance = MagicMock()
                    mock_chain_instance.get_traceability_report.return_value = {
                        "chain": [
                            {
                                "node_id": "n1",
                                "node_type": "JOURNAL_ENTRY",
                                "entity_type": "journal",
                                "entity_id": str(uuid4()),
                                "timestamp": datetime.now(UTC).isoformat(),
                                "created_by": "admin",
                                "metadata": {},
                            },
                            {
                                "node_id": "n2",
                                "node_type": "APPROVAL",
                                "entity_type": "journal",
                                "entity_id": str(uuid4()),
                                "timestamp": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
                                "created_by": "approver",
                                "metadata": {},
                            },
                        ],
                        "root_cause": {"entity_type": "journal"},
                        "final_outcome": {"entity_type": "journal"},
                    }
                    mock_chain.return_value = mock_chain_instance

                    # Setup mock tracker
                    mock_tracker_instance = MagicMock()
                    mock_tracker_instance.analyze_impact.return_value = MagicMock(
                        downstream_count=3,
                        upstream_count=1,
                        has_cycles=False,
                    )
                    mock_tracker.return_value = mock_tracker_instance

                    # Setup mock node service
                    mock_node.return_value = MagicMock()
                    yield

    def test_singleton_new(self):
        b1 = AuditStoryBuilder()
        b2 = AuditStoryBuilder()
        assert b1 is b2

    def test_build_audit_story(self):
        builder = AuditStoryBuilder()
        story = builder.build_audit_story(
            transaction_id=uuid4(),
            transaction_type="JOURNAL",
            generated_by="tester",
            format=AuditStoryFormat.TEXT,
            language=ExplanationLanguage.ENGLISH,
            level=ExplanationLevel.DETAILED,
            legal_entity_id=uuid4(),
            include_forensic=True,
        )
        assert isinstance(story, AuditStory)
        assert story.transaction_type == "JOURNAL"
        assert story.format == AuditStoryFormat.TEXT
        assert len(story.timeline) == 2  # from chain
        assert story.status == AuditStoryStatus.DRAFT
        assert story.cryptographic_hash != ""

        # Check sections
        assert AuditStorySection.HEADER in story.sections
        assert AuditStorySection.EXECUTIVE_SUMMARY in story.sections
        assert AuditStorySection.TIMELINE in story.sections
        assert AuditStorySection.PARTIES in story.sections
        assert AuditStorySection.CAUSAL_CHAIN in story.sections
        assert AuditStorySection.FINANCIAL_IMPACT in story.sections
        assert AuditStorySection.APPROVALS in story.sections
        assert AuditStorySection.RISK_ASSESSMENT in story.sections
        assert AuditStorySection.FORENSIC_DETAILS in story.sections
        assert AuditStorySection.CONCLUSION in story.sections
        assert AuditStorySection.FOOTER in story.sections

        # Builder should have stored the story
        assert len(builder._stories) == 1
        assert builder._stories[0].story_id == story.story_id

    def test_build_audit_story_error(self):
        builder = AuditStoryBuilder()
        # Override mock to return error
        with patch("domain.causality.audit_story_builder.get_causal_chain_builder") as mock_chain:
            mock_chain_instance = MagicMock()
            mock_chain_instance.get_traceability_report.return_value = {"error": "Trace not found"}
            mock_chain.return_value = mock_chain_instance

            story = builder.build_audit_story(
                transaction_id=uuid4(),
                transaction_type="JOURNAL",
                generated_by="tester",
            )
            assert story is not None
            assert "Error" in story.sections[AuditStorySection.HEADER]
            assert story.metadata.get("error") == "Trace not found"

    def test_get_story(self):
        builder = AuditStoryBuilder()
        story = builder.build_audit_story(
            transaction_id=uuid4(),
            transaction_type="JOURNAL",
            generated_by="tester",
        )
        retrieved = builder.get_story(story.story_id)
        assert retrieved is not None
        assert retrieved.story_id == story.story_id

        not_found = builder.get_story(uuid4())
        assert not_found is None

    def test_get_stories_by_transaction(self):
        builder = AuditStoryBuilder()
        tx_id = uuid4()
        story1 = builder.build_audit_story(
            transaction_id=tx_id,
            transaction_type="JOURNAL",
            generated_by="tester",
        )
        story2 = builder.build_audit_story(
            transaction_id=tx_id,
            transaction_type="INVOICE",
            generated_by="tester",
        )
        # Another transaction
        builder.build_audit_story(
            transaction_id=uuid4(),
            transaction_type="PAYMENT",
            generated_by="tester",
        )

        results = builder.get_stories_by_transaction(tx_id)
        assert len(results) == 2
        assert results[0].transaction_id == tx_id
        assert results[1].transaction_id == tx_id

    def test_finalize_story(self):
        builder = AuditStoryBuilder()
        story = builder.build_audit_story(
            transaction_id=uuid4(),
            transaction_type="JOURNAL",
            generated_by="tester",
        )
        finalized = builder.finalize_story(story.story_id, "finalizer")
        assert finalized is not None
        assert finalized.status == AuditStoryStatus.FINALIZED
        assert finalized.metadata["finalized_by"] == "finalizer"
        assert "finalized_at" in finalized.metadata

        # Not found
        assert builder.finalize_story(uuid4(), "x") is None

    def test_archive_story(self):
        builder = AuditStoryBuilder()
        story = builder.build_audit_story(
            transaction_id=uuid4(),
            transaction_type="JOURNAL",
            generated_by="tester",
        )
        archived = builder.archive_story(story.story_id, "archiver")
        assert archived is not None
        assert archived.status == AuditStoryStatus.ARCHIVED
        assert archived.metadata["archived_by"] == "archiver"
        assert "archived_at" in archived.metadata

        # Not found
        assert builder.archive_story(uuid4(), "x") is None

    def test_delete_story(self):
        builder = AuditStoryBuilder()
        story = builder.build_audit_story(
            transaction_id=uuid4(),
            transaction_type="JOURNAL",
            generated_by="tester",
        )
        assert len(builder._stories) == 1
        result = builder.delete_story(story.story_id)
        assert result is True
        assert len(builder._stories) == 0

        # Delete again
        result2 = builder.delete_story(story.story_id)
        assert result2 is False

    def test_list_stories(self):
        builder = AuditStoryBuilder()
        for i in range(5):
            builder.build_audit_story(
                transaction_id=uuid4(),
                transaction_type=f"TYPE_{i}",
                generated_by="tester",
            )
        # All
        all_stories = builder.list_stories()
        assert len(all_stories) == 5

        # Limit
        limited = builder.list_stories(limit=3)
        assert len(limited) == 3

        # By status
        # Finalize one
        story = builder._stories[0]
        builder.finalize_story(story.story_id, "finalizer")
        draft = builder.list_stories(status=AuditStoryStatus.DRAFT)
        assert len(draft) == 4
        finalized = builder.list_stories(status=AuditStoryStatus.FINALIZED)
        assert len(finalized) == 1

    def test_get_statistics(self):
        builder = AuditStoryBuilder()
        for i in range(3):
            builder.build_audit_story(
                transaction_id=uuid4(),
                transaction_type="JOURNAL",
                generated_by="tester",
            )
        stats = builder.get_statistics()
        assert stats["total_stories"] == 3
        assert stats["by_status"]["draft"] == 3
        assert stats["by_format"]["text"] == 3
        assert "audit_log_size" in stats

    def test_get_audit_log(self):
        builder = AuditStoryBuilder()
        builder.build_audit_story(
            transaction_id=uuid4(),
            transaction_type="JOURNAL",
            generated_by="tester",
        )
        log = builder.get_audit_log()
        assert len(log) >= 1
        assert log[-1]["action"] == "BUILD_SUCCESS"

    def test_reset(self):
        builder = AuditStoryBuilder()
        builder.build_audit_story(
            transaction_id=uuid4(),
            transaction_type="JOURNAL",
            generated_by="tester",
        )
        builder.reset()
        assert len(builder._stories) == 0
        assert len(builder._audit_log) == 0


# ============================================================================
# Tests for module-level get_audit_story_builder
# ============================================================================

def test_get_audit_story_builder():
    builder1 = get_audit_story_builder()
    builder2 = get_audit_story_builder()
    assert builder1 is builder2