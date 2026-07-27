# tests/compliance/legal/test_legal_opinion_document_store.py
# Comprehensive tests for compliance/legal/legal_opinion_document_store.py

import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch
from uuid import UUID, uuid4

import pytest

from compliance.legal.legal_opinion_document_store import (
    LegalOpinion,
    LegalOpinionAttachment,
    LegalOpinionConfidentiality,
    LegalOpinionDocumentStore,
    LegalOpinionError,
    LegalOpinionNotFoundError,
    LegalOpinionStatus,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def sample_attachment():
    return LegalOpinionAttachment(
        attachment_id=uuid4(),
        filename="tax_treaty.pdf",
        file_url="s3://bucket/tax_treaty.pdf",
        file_hash="abc123",
        file_size_bytes=1024,
        description="PDF of tax treaty",
    )


@pytest.fixture
def sample_opinion():
    return LegalOpinion(
        opinion_id=uuid4(),
        title="Tax Treatment of Cross-Border Payments",
        author="John Doe, Partner",
        law_firm="Law Firm A",
        date_issued=date(2025, 3, 15),
        subject="Withholding tax on software royalties",
        content="Based on Indonesia-Singapore tax treaty, the withholding tax rate is reduced to 10%...",
        jurisdiction="ID",
        status=LegalOpinionStatus.FINAL,
        confidentiality=LegalOpinionConfidentiality.CONFIDENTIAL,
        version=1,
        reviewed_by="Jane Smith",
        approved_by="Bob Johnson",
        tags=["tax", "withholding", "royalty", "treaty"],
    )


@pytest.fixture
def opinion_store(tmp_path):
    store = LegalOpinionDocumentStore(storage_path=tmp_path / "attachments")
    return store


# ============================================================================
# Tests for Enums (already present, but we keep them)
# ============================================================================

class TestLegalOpinionStatus:
    def test_members_exist(self):
        assert hasattr(LegalOpinionStatus, 'DRAFT')
        assert hasattr(LegalOpinionStatus, 'FINAL')
        assert hasattr(LegalOpinionStatus, 'SUPERSEDED')
        assert hasattr(LegalOpinionStatus, 'EXPIRED')
        assert hasattr(LegalOpinionStatus, 'ARCHIVED')

    def test_member_is_instance(self):
        assert isinstance(LegalOpinionStatus.DRAFT, LegalOpinionStatus)


class TestLegalOpinionConfidentiality:
    def test_members_exist(self):
        assert hasattr(LegalOpinionConfidentiality, 'PUBLIC')
        assert hasattr(LegalOpinionConfidentiality, 'INTERNAL')
        assert hasattr(LegalOpinionConfidentiality, 'CONFIDENTIAL')
        assert hasattr(LegalOpinionConfidentiality, 'ATTORNEY_CLIENT')

    def test_member_is_instance(self):
        assert isinstance(LegalOpinionConfidentiality.PUBLIC, LegalOpinionConfidentiality)


# ============================================================================
# Tests for Exceptions
# ============================================================================

class TestLegalOpinionError:
    def test_raise(self):
        with pytest.raises(LegalOpinionError):
            raise LegalOpinionError("test")


class TestLegalOpinionNotFoundError:
    def test_raise(self):
        with pytest.raises(LegalOpinionNotFoundError):
            raise LegalOpinionNotFoundError("not found")


# ============================================================================
# Tests for LegalOpinionAttachment
# ============================================================================

class TestLegalOpinionAttachment:
    def test_construction(self, sample_attachment):
        assert sample_attachment.id is not None
        assert sample_attachment.filename == "tax_treaty.pdf"
        assert sample_attachment.file_hash == "abc123"
        assert sample_attachment.uploaded_at is not None

    def test_to_dict(self, sample_attachment):
        d = sample_attachment.to_dict()
        assert d["attachment_id"] == str(sample_attachment.id)
        assert d["filename"] == "tax_treaty.pdf"
        assert d["file_url"] == "s3://bucket/tax_treaty.pdf"
        assert d["file_hash"] == "abc123"
        assert d["file_size_bytes"] == 1024
        assert d["description"] == "PDF of tax treaty"
        assert "uploaded_at" in d


# ============================================================================
# Tests for LegalOpinion
# ============================================================================

class TestLegalOpinion:
    def test_construction(self, sample_opinion):
        assert sample_opinion.id is not None
        assert sample_opinion.title == "Tax Treatment of Cross-Border Payments"
        assert sample_opinion.status == LegalOpinionStatus.FINAL
        assert sample_opinion.version == 1
        assert sample_opinion._hash is not None
        assert sample_opinion.created_at is not None
        assert sample_opinion.updated_at is not None

    def test_compute_hash(self, sample_opinion):
        h1 = sample_opinion._compute_hash()
        h2 = sample_opinion._compute_hash()
        assert h1 == h2
        # Change something
        sample_opinion.title = "New Title"
        h3 = sample_opinion._compute_hash()
        assert h1 != h3

    def test_add_attachment(self, sample_opinion, sample_attachment):
        sample_opinion.add_attachment(sample_attachment)
        assert len(sample_opinion.attachments) == 1
        assert sample_opinion.attachments[0] is sample_attachment
        # Updated_at should change
        old_updated = sample_opinion.updated_at
        sample_opinion.add_attachment(sample_attachment)  # add another
        assert sample_opinion.updated_at > old_updated
        # Hash should change because attachments are part of to_dict? Actually _compute_hash doesn't include attachments,
        # but add_attachment calls _compute_hash anyway (it recomputes even though attachments not in hash)
        # So hash changes? Actually _compute_hash doesn't include attachments, so it stays same.
        # But we can check it doesn't break.

    def test_update_status(self, sample_opinion):
        sample_opinion.update_status(LegalOpinionStatus.DRAFT, "admin")
        assert sample_opinion.status == LegalOpinionStatus.DRAFT
        assert sample_opinion.updated_at is not None
        # Check hash recomputed
        old_hash = sample_opinion._hash
        sample_opinion.update_status(LegalOpinionStatus.FINAL, "admin")
        assert sample_opinion._hash != old_hash  # status change changes hash

    def test_create_new_version(self, sample_opinion):
        new_date = date(2026, 1, 1)
        new_content = "Updated content"
        new_opinion = sample_opinion.create_new_version(
            new_content=new_content,
            new_author="New Author",
            new_date=new_date,
            notes="Updated version"
        )
        assert new_opinion.id != sample_opinion.id
        assert new_opinion.title == sample_opinion.title
        assert new_opinion.author == "New Author"
        assert new_opinion.date_issued == new_date
        assert new_opinion.content == new_content
        assert new_opinion.version == sample_opinion.version + 1
        assert new_opinion.supersedes_opinion_id == sample_opinion.id
        assert new_opinion.status == LegalOpinionStatus.FINAL
        # Original should be superseded
        assert sample_opinion.status == LegalOpinionStatus.SUPERSEDED
        assert sample_opinion.updated_at is not None

    def test_is_expired(self, sample_opinion):
        # Today is 2026-07-27 in tests? We'll patch date.today
        with patch("compliance.legal.legal_opinion_document_store.date") as mock_date:
            mock_date.today.return_value = date(2026, 3, 15)  # exactly 1 year after issue (2025-03-15)
            # expiry is 1 year after issue, so should be False (not expired)
            assert sample_opinion.is_expired(expiry_days=365) is False
            mock_date.today.return_value = date(2026, 3, 16)
            assert sample_opinion.is_expired(expiry_days=365) is True
            # With different expiry days
            mock_date.today.return_value = date(2025, 9, 15)  # 6 months
            assert sample_opinion.is_expired(expiry_days=180) is False
            mock_date.today.return_value = date(2025, 9, 16)
            assert sample_opinion.is_expired(expiry_days=180) is True

    def test_to_dict(self, sample_opinion, sample_attachment):
        sample_opinion.add_attachment(sample_attachment)
        d = sample_opinion.to_dict(include_attachments=True)
        assert d["opinion_id"] == str(sample_opinion.id)
        assert d["title"] == sample_opinion.title
        assert d["content"] == sample_opinion.content[:500] + "..."  # truncated
        assert d["status"] == "final"
        assert d["version"] == 1
        assert d["hash"] == sample_opinion._hash
        assert "attachments" in d
        assert len(d["attachments"]) == 1
        assert d["attachments"][0]["filename"] == "tax_treaty.pdf"
        # Without attachments
        d2 = sample_opinion.to_dict(include_attachments=False)
        assert "attachments" not in d2
        # Short content
        opinion_short = LegalOpinion(
            opinion_id=uuid4(),
            title="Short",
            author="A",
            law_firm="B",
            date_issued=date.today(),
            subject="S",
            content="short",
            jurisdiction="ID",
        )
        d3 = opinion_short.to_dict()
        assert d3["content"] == "short"  # not truncated


# ============================================================================
# Tests for LegalOpinionDocumentStore
# ============================================================================

class TestLegalOpinionDocumentStore:
    def test_add_opinion(self, opinion_store, sample_opinion):
        opinion_id = opinion_store.add_opinion(sample_opinion)
        assert opinion_id == sample_opinion.id
        assert opinion_store.get_opinion(opinion_id) is sample_opinion
        # Check indexes
        assert "tax" in opinion_store._subject_index
        assert sample_opinion.id in opinion_store._subject_index["tax"]
        assert "ID" in opinion_store._jurisdiction_index
        assert sample_opinion.id in opinion_store._jurisdiction_index["ID"]
        assert "tax" in opinion_store._tag_index
        assert sample_opinion.id in opinion_store._tag_index["tax"]

    def test_get_opinion(self, opinion_store, sample_opinion):
        opinion_store.add_opinion(sample_opinion)
        retrieved = opinion_store.get_opinion(sample_opinion.id)
        assert retrieved is sample_opinion
        assert opinion_store.get_opinion(uuid4()) is None

    def test_update_opinion(self, opinion_store, sample_opinion):
        opinion_store.add_opinion(sample_opinion)
        # Update title
        result = opinion_store.update_opinion(sample_opinion.id, title="New Title")
        assert result is True
        assert sample_opinion.title == "New Title"
        assert sample_opinion.updated_at is not None
        # Update non-existent field
        result2 = opinion_store.update_opinion(sample_opinion.id, fake_field="value")
        assert result2 is True  # it will ignore unknown field silently (hasattr returns False)
        # Update non-existent opinion
        result3 = opinion_store.update_opinion(uuid4(), title="x")
        assert result3 is False

    def test_delete_opinion(self, opinion_store, sample_opinion):
        opinion_store.add_opinion(sample_opinion)
        result = opinion_store.delete_opinion(sample_opinion.id)
        assert result is True
        assert opinion_store.get_opinion(sample_opinion.id) is None
        # Delete again
        result2 = opinion_store.delete_opinion(sample_opinion.id)
        assert result2 is False

    def test_find_by_subject(self, opinion_store, sample_opinion):
        opinion_store.add_opinion(sample_opinion)
        # Search by keyword
        results = opinion_store.find_by_subject("withholding")
        assert len(results) == 1
        assert results[0] is sample_opinion
        # Search by partial word
        results2 = opinion_store.find_by_subject("tax")
        assert len(results2) == 1
        # Search by multiple words
        results3 = opinion_store.find_by_subject("tax royalty")
        assert len(results3) == 1
        # No match
        results4 = opinion_store.find_by_subject("nonexistent")
        assert len(results4) == 0

    def test_find_by_jurisdiction(self, opinion_store, sample_opinion):
        opinion_store.add_opinion(sample_opinion)
        results = opinion_store.find_by_jurisdiction("ID")
        assert len(results) == 1
        assert results[0] is sample_opinion
        results2 = opinion_store.find_by_jurisdiction("US")
        assert len(results2) == 0

    def test_find_by_tag(self, opinion_store, sample_opinion):
        opinion_store.add_opinion(sample_opinion)
        results = opinion_store.find_by_tag("tax")
        assert len(results) == 1
        results2 = opinion_store.find_by_tag("TREATY")  # case insensitive
        assert len(results2) == 1
        results3 = opinion_store.find_by_tag("nonexistent")
        assert len(results3) == 0

    def test_find_by_date_range(self, opinion_store, sample_opinion):
        opinion_store.add_opinion(sample_opinion)
        start = date(2025, 1, 1)
        end = date(2025, 12, 31)
        results = opinion_store.find_by_date_range(start, end)
        assert len(results) == 1
        results2 = opinion_store.find_by_date_range(date(2024, 1, 1), date(2024, 12, 31))
        assert len(results2) == 0

    def test_find_by_law_firm(self, opinion_store, sample_opinion):
        opinion_store.add_opinion(sample_opinion)
        results = opinion_store.find_by_law_firm("Law Firm A")
        assert len(results) == 1
        results2 = opinion_store.find_by_law_firm("Law Firm B")
        assert len(results2) == 0

    def test_get_latest_version_single(self, opinion_store, sample_opinion):
        opinion_store.add_opinion(sample_opinion)
        latest = opinion_store.get_latest_version(sample_opinion.id)
        assert latest is sample_opinion

    def test_get_latest_version_with_supersede(self, opinion_store, sample_opinion):
        opinion_store.add_opinion(sample_opinion)
        # Create a new version that supersedes
        new_date = date(2026, 1, 1)
        new_content = "Updated content"
        new_opinion = sample_opinion.create_new_version(
            new_content=new_content,
            new_author="New Author",
            new_date=new_date,
            notes="Updated"
        )
        opinion_store.add_opinion(new_opinion)
        # Latest should be new_opinion
        latest = opinion_store.get_latest_version(sample_opinion.id)
        assert latest is new_opinion
        # If we ask for latest of new_opinion, should return itself
        latest2 = opinion_store.get_latest_version(new_opinion.id)
        assert latest2 is new_opinion
        # If we ask for non-existent
        assert opinion_store.get_latest_version(uuid4()) is None

    def test_get_all_active(self, opinion_store, sample_opinion):
        opinion_store.add_opinion(sample_opinion)  # FINAL
        draft_opinion = LegalOpinion(
            opinion_id=uuid4(),
            title="Draft",
            author="A",
            law_firm="B",
            date_issued=date.today(),
            subject="Draft",
            content="Draft",
            jurisdiction="ID",
            status=LegalOpinionStatus.DRAFT,
        )
        opinion_store.add_opinion(draft_opinion)
        active = opinion_store.get_all_active()
        assert len(active) == 1
        assert active[0] is sample_opinion

    def test_generate_report(self, opinion_store, sample_opinion):
        opinion_store.add_opinion(sample_opinion)
        # Add another
        op2 = LegalOpinion(
            opinion_id=uuid4(),
            title="Another",
            author="X",
            law_firm="Law Firm A",
            date_issued=date.today(),
            subject="Compliance",
            content="...",
            jurisdiction="US",
            status=LegalOpinionStatus.DRAFT,
            tags=["compliance"],
        )
        opinion_store.add_opinion(op2)
        report = opinion_store.generate_report()
        assert report["total_opinions"] == 2
        assert report["active_opinions"] == 1
        assert report["by_jurisdiction"]["ID"] == 1
        assert report["by_jurisdiction"]["US"] == 1
        assert report["by_status"]["final"] == 1
        assert report["by_status"]["draft"] == 1

    def test_export_to_json(self, opinion_store, sample_opinion, tmp_path):
        opinion_store.add_opinion(sample_opinion)
        file_path = tmp_path / "export.json"
        opinion_store.export_to_json(str(file_path))
        assert file_path.exists()
        data = json.loads(file_path.read_text())
        assert "report" in data
        assert "opinions" in data
        assert len(data["opinions"]) == 1
        assert data["opinions"][0]["title"] == sample_opinion.title

    def test_save_attachment_no_storage_path(self, opinion_store, sample_opinion):
        opinion_store.add_opinion(sample_opinion)
        opinion_store._storage_path = None
        with pytest.raises(LegalOpinionError, match="Storage path not configured"):
            opinion_store.save_attachment(sample_opinion.id, "test.pdf", b"content")

    def test_save_attachment_opinion_not_found(self, opinion_store):
        result = opinion_store.save_attachment(uuid4(), "test.pdf", b"content")
        assert result is None

    def test_save_attachment_success(self, opinion_store, sample_opinion, tmp_path):
        opinion_store.add_opinion(sample_opinion)
        # Ensure storage path exists
        storage_path = tmp_path / "attachments"
        opinion_store._storage_path = storage_path
        # Save attachment
        file_content = b"PDF content"
        attachment_id = opinion_store.save_attachment(
            sample_opinion.id, "tax_treaty.pdf", file_content, description="Tax treaty PDF"
        )
        assert attachment_id is not None
        # Check file saved
        files = list(storage_path.glob("*"))
        assert len(files) == 1
        assert files[0].read_bytes() == file_content
        # Check attachment added to opinion
        assert len(sample_opinion.attachments) == 1
        att = sample_opinion.attachments[0]
        assert att.filename == "tax_treaty.pdf"
        assert att.file_hash == hashlib.sha256(file_content).hexdigest()
        assert att.file_size_bytes == len(file_content)
        assert att.description == "Tax treaty PDF"
        assert att.id == attachment_id
        # Check updated_at changed
        assert sample_opinion.updated_at is not None

    def test_index_opinion_private_method(self, opinion_store, sample_opinion):
        # We can call _index_opinion manually to test it
        opinion_store._index_opinion(sample_opinion)
        # Should have added to indexes
        assert "tax" in opinion_store._subject_index
        assert sample_opinion.id in opinion_store._subject_index["tax"]
        assert "ID" in opinion_store._jurisdiction_index
        assert sample_opinion.id in opinion_store._jurisdiction_index["ID"]
        assert "tax" in opinion_store._tag_index
        assert sample_opinion.id in opinion_store._tag_index["tax"]
        # Also should ignore short words
        opinion_store._subject_index.clear()
        opinion_store._index_opinion(sample_opinion)
        assert "tax" in opinion_store._subject_index
        assert "on" not in opinion_store._subject_index  # short word

    def test_storage_path_creation(self, tmp_path):
        store = LegalOpinionDocumentStore(storage_path=tmp_path / "new")
        # Path is not created until save_attachment, but we can test that it creates
        opinion = LegalOpinion(
            opinion_id=uuid4(),
            title="Test",
            author="A",
            law_firm="B",
            date_issued=date.today(),
            subject="S",
            content="C",
            jurisdiction="ID",
        )
        store.add_opinion(opinion)
        store.save_attachment(opinion.id, "file.txt", b"data")
        assert (tmp_path / "new").exists()

    def test_add_opinion_updates_indexes(self, opinion_store, sample_opinion):
        opinion_store.add_opinion(sample_opinion)
        # Check indexes contain opinion
        assert sample_opinion.id in opinion_store._subject_index["tax"]
        assert sample_opinion.id in opinion_store._jurisdiction_index["ID"]
        assert sample_opinion.id in opinion_store._tag_index["tax"]

    def test_delete_opinion_does_not_clean_indexes(self, opinion_store, sample_opinion):
        opinion_store.add_opinion(sample_opinion)
        opinion_store.delete_opinion(sample_opinion.id)
        # Indexes still contain the ID (acceptable for small scale)
        assert sample_opinion.id in opinion_store._subject_index["tax"]
        # But find_by_subject should not return it because it's not in _opinions
        results = opinion_store.find_by_subject("tax")
        assert len(results) == 0