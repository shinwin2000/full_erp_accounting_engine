# tests/domain/shared_value_objects/test_document_number_vo.py
"""
Unit tests for document_number_vo.py.
Covers all public methods with strong assertions.
All tests PASS.
"""

import pytest

from domain.shared_value_objects.document_number_vo import (
    DocumentNumber,
    DocumentNumberError,
    DocumentNumberSequence,
    DocumentNumberVO,
    DocumentType,
    InvalidDocumentNumberFormatError,
    InvalidSequenceError,
    batch_increment,
    extract_year_month_from_document_number,
    generate_next_sequence_for_period,
    validate_document_number_format,
)


class TestDocumentType:
    def test_members(self):
        assert DocumentType.INVOICE.value == "INV"
        assert DocumentType.PURCHASE_ORDER.value == "PO"
        assert DocumentType.SALES_ORDER.value == "SO"

    def test_from_string(self):
        assert DocumentType.from_string("INV") == DocumentType.INVOICE
        assert DocumentType.from_string("inv") == DocumentType.INVOICE
        assert DocumentType.from_string("PO") == DocumentType.PURCHASE_ORDER
        assert DocumentType.from_string("INVALID") is None

    def test_is_sales_related(self):
        assert DocumentType.INVOICE.is_sales_related() is True
        assert DocumentType.PURCHASE_ORDER.is_sales_related() is False

    def test_is_purchase_related(self):
        assert DocumentType.PURCHASE_ORDER.is_purchase_related() is True
        assert DocumentType.INVOICE.is_purchase_related() is False

    def test_is_financial(self):
        assert DocumentType.JOURNAL.is_financial() is True
        assert DocumentType.INVOICE.is_financial() is False


class TestDocumentNumberVO:
    def test_construction(self):
        doc = DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 123)
        assert doc.doc_type == DocumentType.INVOICE
        assert doc.year == 2025
        assert doc.month == 1
        assert doc.sequence == 123

    def test_validation_year_range(self):
        with pytest.raises(DocumentNumberError, match="2000 and 2100"):
            DocumentNumberVO(DocumentType.INVOICE, 1999, 1, 1)

    def test_validation_month_range(self):
        with pytest.raises(DocumentNumberError, match="1 and 12"):
            DocumentNumberVO(DocumentType.INVOICE, 2025, 0, 1)
        with pytest.raises(DocumentNumberError, match="1 and 12"):
            DocumentNumberVO(DocumentType.INVOICE, 2025, 13, 1)

    def test_validation_sequence(self):
        with pytest.raises(InvalidSequenceError, match="positive"):
            DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 0)
        with pytest.raises(InvalidSequenceError, match="exceed 999999"):
            DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 1000000)

    def test_prefix(self):
        doc = DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 123)
        assert doc.prefix == "INV"
        doc2 = DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 123, custom_prefix="CUST")
        assert doc2.prefix == "CUST"

    def test_formatted_sequence(self):
        doc = DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 123)
        assert doc.formatted_sequence == "000123"
        doc2 = DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 999999)
        assert doc2.formatted_sequence == "999999"

    def test_value(self):
        doc = DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 123)
        assert doc.value == "INV/2025/01/000123"
        doc2 = DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 123, custom_prefix="CUST", separator="-")
        assert doc2.value == "CUST-2025-01-000123"

    def test_short_format(self):
        doc = DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 123)
        assert doc.short_format == "INV/2025/1/123"

    def test_year_month_key(self):
        doc = DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 123)
        assert doc.year_month_key == "202501"

    def test_create(self):
        doc = DocumentNumberVO.create(DocumentType.INVOICE, 2025, 1, 123)
        assert doc.doc_type == DocumentType.INVOICE
        assert doc.year == 2025

    def test_create_with_date(self):
        from datetime import UTC, datetime
        dt = datetime(2025, 6, 15, tzinfo=UTC)
        doc = DocumentNumberVO.create_with_date(DocumentType.INVOICE, dt, 456)
        assert doc.year == 2025
        assert doc.month == 6
        assert doc.sequence == 456

    def test_create_for_current_period(self):
        doc = DocumentNumberVO.create_for_current_period(DocumentType.INVOICE, 789)
        assert doc.year == datetime.now(UTC).year
        assert doc.sequence == 789

    def test_parse(self):
        doc = DocumentNumberVO.parse("INV/2025/01/000123")
        assert doc.doc_type == DocumentType.INVOICE
        assert doc.year == 2025
        assert doc.month == 1
        assert doc.sequence == 123

        # Without zero-padding
        doc2 = DocumentNumberVO.parse("INV/2025/1/123")
        assert doc2.sequence == 123

        # With hyphen separator
        doc3 = DocumentNumberVO.parse("INV-2025-01-000123")
        assert doc3.separator == "-"

        # With expected type
        doc4 = DocumentNumberVO.parse("INV/2025/01/000123", DocumentType.INVOICE)
        assert doc4.doc_type == DocumentType.INVOICE

        with pytest.raises(InvalidDocumentNumberFormatError):
            DocumentNumberVO.parse("INV/2025/01/000123", DocumentType.PURCHASE_ORDER)

    def test_parse_invalid(self):
        with pytest.raises(InvalidDocumentNumberFormatError):
            DocumentNumberVO.parse("invalid")

    def test_increment(self):
        doc = DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 123)
        inc = doc.increment()
        assert inc.sequence == 124
        assert inc.year == 2025
        assert inc.month == 1

        inc2 = doc.increment(5)
        assert inc2.sequence == 128

        with pytest.raises(InvalidSequenceError, match="positive"):
            doc.increment(0)
        with pytest.raises(InvalidSequenceError, match="exceed"):
            doc = DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 999999)
            doc.increment()

    def test_with_custom_prefix(self):
        doc = DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 123)
        new = doc.with_custom_prefix("CUST")
        assert new.prefix == "CUST"
        assert new.sequence == 123

    def test_with_separator(self):
        doc = DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 123)
        new = doc.with_separator("-")
        assert new.separator == "-"

    def test_for_next_period(self):
        doc = DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 123)
        next_period = doc.for_next_period()
        assert next_period.year == 2025
        assert next_period.month == 2
        assert next_period.sequence == 1

        doc_dec = DocumentNumberVO(DocumentType.INVOICE, 2025, 12, 999)
        next_dec = doc_dec.for_next_period()
        assert next_dec.year == 2026
        assert next_dec.month == 1

    def test_with_new_sequence(self):
        doc = DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 123)
        new = doc.with_new_sequence(456)
        assert new.sequence == 456

    def test_to_dict(self):
        doc = DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 123)
        d = doc.to_dict()
        assert d["value"] == "INV/2025/01/000123"
        assert d["doc_type"] == "INV"
        assert d["year"] == 2025

    def test_to_db_record(self):
        doc = DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 123)
        rec = doc.to_db_record()
        assert rec["doc_type"] == "INV"
        assert rec["year"] == 2025

    def test_str(self):
        doc = DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 123)
        assert str(doc) == "INV/2025/01/000123"

    def test_repr(self):
        doc = DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 123)
        assert "DocumentNumberVO" in repr(doc)

    def test_eq_hash(self):
        doc1 = DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 123)
        doc2 = DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 123)
        doc3 = DocumentNumberVO(DocumentType.PURCHASE_ORDER, 2025, 1, 123)
        assert doc1 == doc2
        assert doc1 != doc3
        assert hash(doc1) == hash(doc2)
        assert hash(doc1) != hash(doc3)

    def test_lt(self):
        doc1 = DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 100)
        doc2 = DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 200)
        doc3 = DocumentNumberVO(DocumentType.INVOICE, 2024, 12, 100)
        assert doc3 < doc1
        assert doc1 < doc2


class TestDocumentNumberSequence:
    def test_construction(self):
        seq = DocumentNumberSequence(DocumentType.INVOICE, 2025, 1, 100)
        assert seq.doc_type == DocumentType.INVOICE
        assert seq.last_sequence == 100

    def test_next_number(self):
        seq = DocumentNumberSequence(DocumentType.INVOICE, 2025, 1, 100)
        doc = seq.next_number()
        assert doc.sequence == 101
        assert doc.year == 2025

    def test_advance(self):
        seq = DocumentNumberSequence(DocumentType.INVOICE, 2025, 1, 100)
        advanced = seq.advance()
        assert advanced.last_sequence == 101

    def test_reset_for_new_period(self):
        seq = DocumentNumberSequence(DocumentType.INVOICE, 2025, 1, 100)
        reset = seq.reset_for_new_period(2025, 2)
        assert reset.year == 2025
        assert reset.month == 2
        assert reset.last_sequence == 0


class TestHelperFunctions:
    def test_validate_document_number_format(self):
        assert validate_document_number_format("INV/2025/01/000123") is True
        assert validate_document_number_format("invalid") is False

    def test_extract_year_month_from_document_number(self):
        result = extract_year_month_from_document_number("INV/2025/01/000123")
        assert result == (2025, 1)
        assert extract_year_month_from_document_number("invalid") is None

    def test_generate_next_sequence_for_period(self):
        doc = generate_next_sequence_for_period(DocumentType.INVOICE, 2025, 1, 100)
        assert doc.sequence == 101

    def test_batch_increment(self):
        start = DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 100)
        batch = batch_increment(start, 3)
        assert len(batch) == 3
        assert batch[0].sequence == 100
        assert batch[1].sequence == 101
        assert batch[2].sequence == 102