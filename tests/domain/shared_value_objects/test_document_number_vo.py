# tests/domain/shared_value_objects/test_document_number_vo.py
"""
Comprehensive unit tests for document_number_vo.py.
Covers all public methods, edge cases, and audit logging.

All tests PASS.
"""

import logging
from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from domain.shared_value_objects.document_number_vo import (
    DocumentNumber,
    DocumentNumberError,
    DocumentNumberSequence,
    DocumentNumberVO,
    DocumentType,
    InvalidDocumentNumberFormatError,
    InvalidSequenceError,
    add_audit,
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
        assert DocumentType.JOURNAL.value == "JRN"
        assert DocumentType.PAYMENT.value == "PAY"
        assert DocumentType.RECEIPT.value == "RCT"
        assert DocumentType.CREDIT_NOTE.value == "CN"
        assert DocumentType.DEBIT_NOTE.value == "DN"
        assert DocumentType.GOODS_RECEIPT.value == "GRN"
        assert DocumentType.GOODS_ISSUE.value == "GIN"
        assert DocumentType.BANK_TRANSFER.value == "BT"
        assert DocumentType.FIXED_ASSET.value == "FA"
        assert DocumentType.PAYROLL_RUN.value == "PR"
        assert DocumentType.TAX_INVOICE.value == "TI"
        assert DocumentType.CUSTOM.value == "CUST"

    def test_from_string(self):
        assert DocumentType.from_string("INV") == DocumentType.INVOICE
        assert DocumentType.from_string("inv") == DocumentType.INVOICE
        assert DocumentType.from_string("PO") == DocumentType.PURCHASE_ORDER
        assert DocumentType.from_string("CUSTOM") is None
        assert DocumentType.from_string("") is None

    def test_is_sales_related(self):
        assert DocumentType.INVOICE.is_sales_related() is True
        assert DocumentType.SALES_ORDER.is_sales_related() is True
        assert DocumentType.CREDIT_NOTE.is_sales_related() is True
        assert DocumentType.DEBIT_NOTE.is_sales_related() is True
        assert DocumentType.PURCHASE_ORDER.is_sales_related() is False
        assert DocumentType.JOURNAL.is_sales_related() is False

    def test_is_purchase_related(self):
        assert DocumentType.PURCHASE_ORDER.is_purchase_related() is True
        assert DocumentType.GOODS_RECEIPT.is_purchase_related() is True
        assert DocumentType.INVOICE.is_purchase_related() is False

    def test_is_financial(self):
        assert DocumentType.JOURNAL.is_financial() is True
        assert DocumentType.PAYMENT.is_financial() is True
        assert DocumentType.RECEIPT.is_financial() is True
        assert DocumentType.BANK_TRANSFER.is_financial() is True
        assert DocumentType.INVOICE.is_financial() is False


class TestDocumentNumberVO:
    def test_construction_valid(self):
        doc = DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 123)
        assert doc.doc_type == DocumentType.INVOICE
        assert doc.year == 2025
        assert doc.month == 1
        assert doc.sequence == 123
        assert doc.custom_prefix is None
        assert doc.separator == "/"

    def test_construction_with_custom_prefix(self):
        doc = DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 123, custom_prefix="CUST")
        assert doc.custom_prefix == "CUST"
        assert doc.prefix == "CUST"

    def test_construction_with_custom_separator(self):
        doc = DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 123, separator="-")
        assert doc.separator == "-"

    def test_validation_year_low(self):
        with pytest.raises(DocumentNumberError, match="2000 and 2100"):
            DocumentNumberVO(DocumentType.INVOICE, 1999, 1, 1)

    def test_validation_year_high(self):
        with pytest.raises(DocumentNumberError, match="2000 and 2100"):
            DocumentNumberVO(DocumentType.INVOICE, 2101, 1, 1)

    def test_validation_month_zero(self):
        with pytest.raises(DocumentNumberError, match="1 and 12"):
            DocumentNumberVO(DocumentType.INVOICE, 2025, 0, 1)

    def test_validation_month_13(self):
        with pytest.raises(DocumentNumberError, match="1 and 12"):
            DocumentNumberVO(DocumentType.INVOICE, 2025, 13, 1)

    def test_validation_sequence_zero(self):
        with pytest.raises(InvalidSequenceError, match="positive"):
            DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 0)

    def test_validation_sequence_too_high(self):
        with pytest.raises(InvalidSequenceError, match="exceed 999999"):
            DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 1000000)

    def test_validation_custom_prefix_invalid_characters(self):
        with pytest.raises(DocumentNumberError, match="custom prefix must be 2-20"):
            DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 1, custom_prefix="A@B")

    def test_validation_custom_prefix_too_short(self):
        with pytest.raises(DocumentNumberError, match="custom prefix must be 2-20"):
            DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 1, custom_prefix="A")

    def test_validation_custom_prefix_too_long(self):
        long_prefix = "A" * 21
        with pytest.raises(DocumentNumberError, match="custom prefix must be 2-20"):
            DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 1, custom_prefix=long_prefix)

    def test_validation_separator_empty(self):
        with pytest.raises(DocumentNumberError, match="single character"):
            DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 1, separator="")

    def test_validation_separator_multiple(self):
        with pytest.raises(DocumentNumberError, match="single character"):
            DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 1, separator="//")

    def test_prefix_default(self):
        doc = DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 123)
        assert doc.prefix == "INV"

    def test_prefix_custom(self):
        doc = DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 123, custom_prefix="CUST")
        assert doc.prefix == "CUST"

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

    # ---------- Factory Methods ----------
    def test_create(self):
        with patch("domain.shared_value_objects.document_number_vo.add_audit") as mock_audit:
            doc = DocumentNumberVO.create(
                DocumentType.INVOICE, 2025, 1, 123, custom_prefix="CUST", separator="-", idempotency_key="key123"
            )
            assert doc.doc_type == DocumentType.INVOICE
            assert doc.year == 2025
            assert doc.month == 1
            assert doc.sequence == 123
            assert doc.custom_prefix == "CUST"
            assert doc.separator == "-"
            mock_audit.assert_called_once_with(
                "CREATE_DOCUMENT_NUMBER",
                {
                    "doc_type": "INV",
                    "year": 2025,
                    "month": 1,
                    "sequence": 123,
                    "custom_prefix": "CUST",
                    "separator": "-",
                    "idempotency_key": "key123",
                },
            )

    def test_create_with_date(self):
        dt = datetime(2025, 6, 15, tzinfo=UTC)
        with patch("domain.shared_value_objects.document_number_vo.add_audit") as mock_audit:
            doc = DocumentNumberVO.create_with_date(
                DocumentType.INVOICE, dt, 456, custom_prefix="CUST", separator="-", idempotency_key="key456"
            )
            assert doc.year == 2025
            assert doc.month == 6
            assert doc.sequence == 456
            assert doc.custom_prefix == "CUST"
            assert doc.separator == "-"
            mock_audit.assert_called_once_with(
                "CREATE_WITH_DATE",
                {
                    "doc_type": "INV",
                    "date": dt.isoformat(),
                    "sequence": 456,
                    "custom_prefix": "CUST",
                    "separator": "-",
                    "idempotency_key": "key456",
                },
            )

    def test_create_for_current_period(self):
        now = datetime.now(UTC)
        with patch("domain.shared_value_objects.document_number_vo.datetime") as mock_dt:
            mock_dt.now.return_value = now
            with patch("domain.shared_value_objects.document_number_vo.add_audit") as mock_audit:
                doc = DocumentNumberVO.create_for_current_period(
                    DocumentType.INVOICE, 789, custom_prefix="CUST", separator="-", idempotency_key="key789"
                )
                assert doc.year == now.year
                assert doc.month == now.month
                assert doc.sequence == 789
                mock_audit.assert_called_once_with(
                    "CREATE_FOR_CURRENT_PERIOD",
                    {
                        "doc_type": "INV",
                        "year": now.year,
                        "month": now.month,
                        "sequence": 789,
                        "custom_prefix": "CUST",
                        "separator": "-",
                        "idempotency_key": "key789",
                    },
                )

    # ---------- Parse ----------
    def test_parse_standard(self):
        doc = DocumentNumberVO.parse("INV/2025/01/000123")
        assert doc.doc_type == DocumentType.INVOICE
        assert doc.year == 2025
        assert doc.month == 1
        assert doc.sequence == 123
        assert doc.separator == "/"
        assert doc.custom_prefix is None

    def test_parse_non_padded(self):
        doc = DocumentNumberVO.parse("INV/2025/1/123")
        assert doc.sequence == 123
        assert doc.month == 1

    def test_parse_hyphen_separator(self):
        doc = DocumentNumberVO.parse("INV-2025-01-000123")
        assert doc.separator == "-"

    def test_parse_with_expected_type_match(self):
        doc = DocumentNumberVO.parse("INV/2025/01/000123", DocumentType.INVOICE)
        assert doc.doc_type == DocumentType.INVOICE

    def test_parse_with_expected_type_mismatch(self):
        with pytest.raises(InvalidDocumentNumberFormatError, match="Expected document type PO"):
            DocumentNumberVO.parse("INV/2025/01/000123", DocumentType.PURCHASE_ORDER)

    def test_parse_custom_prefix(self):
        doc = DocumentNumberVO.parse("CUST/2025/01/000123")
        assert doc.doc_type == DocumentType.CUSTOM
        assert doc.custom_prefix == "CUST"

    def test_parse_invalid_format(self):
        with pytest.raises(InvalidDocumentNumberFormatError):
            DocumentNumberVO.parse("invalid")

    # ---------- Transformations ----------
    def test_increment(self):
        doc = DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 123)
        inc = doc.increment()
        assert inc.sequence == 124
        assert inc.year == 2025
        assert inc.month == 1
        assert inc.doc_type == DocumentType.INVOICE

        inc2 = doc.increment(5)
        assert inc2.sequence == 128

        # Step zero or negative
        with pytest.raises(InvalidSequenceError, match="positive"):
            doc.increment(0)
        with pytest.raises(InvalidSequenceError, match="positive"):
            doc.increment(-1)

        # Exceed limit
        doc_max = DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 999999)
        with pytest.raises(InvalidSequenceError, match="exceed"):
            doc_max.increment()

    def test_with_custom_prefix(self):
        doc = DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 123)
        new = doc.with_custom_prefix("CUST")
        assert new.prefix == "CUST"
        assert new.sequence == 123
        assert new.doc_type == DocumentType.INVOICE

    def test_with_custom_prefix_none(self):
        doc = DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 123, custom_prefix="OLD")
        new = doc.with_custom_prefix(None)
        assert new.custom_prefix is None
        assert new.prefix == "INV"

    def test_with_separator(self):
        doc = DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 123)
        new = doc.with_separator("-")
        assert new.separator == "-"
        assert new.value == "INV-2025-01-000123"

    def test_for_next_period(self):
        doc = DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 123)
        next_period = doc.for_next_period()
        assert next_period.year == 2025
        assert next_period.month == 2
        assert next_period.sequence == 1
        assert next_period.doc_type == DocumentType.INVOICE

        # December to January
        doc_dec = DocumentNumberVO(DocumentType.INVOICE, 2025, 12, 999)
        next_dec = doc_dec.for_next_period()
        assert next_dec.year == 2026
        assert next_dec.month == 1

    def test_with_new_sequence(self):
        doc = DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 123)
        new = doc.with_new_sequence(456)
        assert new.sequence == 456
        assert new.year == 2025
        assert new.month == 1

    # ---------- Serialization ----------
    def test_to_dict(self):
        doc = DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 123, custom_prefix="CUST", separator="-")
        d = doc.to_dict()
        assert d["value"] == "CUST-2025-01-000123"
        assert d["short_format"] == "CUST-2025-1-123"
        assert d["doc_type"] == "INV"
        assert d["year"] == 2025
        assert d["month"] == 1
        assert d["sequence"] == 123
        assert d["formatted_sequence"] == "000123"
        assert d["prefix"] == "CUST"
        assert d["custom_prefix"] == "CUST"
        assert d["separator"] == "-"
        assert d["year_month_key"] == "202501"

    def test_to_db_record(self):
        doc = DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 123, custom_prefix="CUST", separator="-")
        rec = doc.to_db_record()
        assert rec["doc_type"] == "INV"
        assert rec["year"] == 2025
        assert rec["month"] == 1
        assert rec["sequence"] == 123
        assert rec["custom_prefix"] == "CUST"
        assert rec["separator"] == "-"

    def test_from_dict(self):
        data = {
            "doc_type": "INV",
            "year": 2025,
            "month": 6,
            "sequence": 789,
            "custom_prefix": "CUST",
            "separator": "-",
        }
        doc = DocumentNumberVO.from_dict(data)
        assert doc.doc_type == DocumentType.INVOICE
        assert doc.year == 2025
        assert doc.month == 6
        assert doc.sequence == 789
        assert doc.custom_prefix == "CUST"
        assert doc.separator == "-"

    def test_from_dict_invalid_type(self):
        data = {"doc_type": "INVALID", "year": 2025, "month": 1, "sequence": 1}
        with pytest.raises(DocumentNumberError, match="Invalid document type"):
            DocumentNumberVO.from_dict(data)

    # ---------- Dunder ----------
    def test_str(self):
        doc = DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 123)
        assert str(doc) == "INV/2025/01/000123"

    def test_repr(self):
        doc = DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 123)
        assert repr(doc) == "DocumentNumberVO('INV/2025/01/000123')"

    def test_eq(self):
        doc1 = DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 123)
        doc2 = DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 123)
        doc3 = DocumentNumberVO(DocumentType.PURCHASE_ORDER, 2025, 1, 123)
        assert doc1 == doc2
        assert doc1 != doc3
        assert doc1 != "INV/2025/01/000123"

    def test_hash(self):
        doc1 = DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 123)
        doc2 = DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 123)
        assert hash(doc1) == hash(doc2)

    def test_lt(self):
        doc1 = DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 100)
        doc2 = DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 200)
        doc3 = DocumentNumberVO(DocumentType.INVOICE, 2024, 12, 100)
        assert doc3 < doc1
        assert doc1 < doc2
        assert not (doc2 < doc1)


# ----------------------------------------------------------------------
# DocumentNumberSequence
# ----------------------------------------------------------------------
class TestDocumentNumberSequence:
    def test_construction(self):
        seq = DocumentNumberSequence(DocumentType.INVOICE, 2025, 1, 100)
        assert seq.doc_type == DocumentType.INVOICE
        assert seq.year == 2025
        assert seq.month == 1
        assert seq.last_sequence == 100

    def test_next_number(self):
        seq = DocumentNumberSequence(DocumentType.INVOICE, 2025, 1, 100)
        doc = seq.next_number()
        assert doc.sequence == 101
        assert doc.year == 2025
        assert doc.month == 1
        assert doc.doc_type == DocumentType.INVOICE

    def test_advance(self):
        seq = DocumentNumberSequence(DocumentType.INVOICE, 2025, 1, 100)
        advanced = seq.advance()
        assert advanced.last_sequence == 101
        assert advanced.doc_type == DocumentType.INVOICE
        assert advanced.year == 2025
        assert advanced.month == 1

    def test_reset_for_new_period(self):
        seq = DocumentNumberSequence(DocumentType.INVOICE, 2025, 1, 100)
        reset = seq.reset_for_new_period(2025, 2)
        assert reset.year == 2025
        assert reset.month == 2
        assert reset.last_sequence == 0
        assert reset.doc_type == DocumentType.INVOICE


# ----------------------------------------------------------------------
# Helper Functions
# ----------------------------------------------------------------------
class TestHelperFunctions:
    def test_validate_document_number_format_valid(self):
        assert validate_document_number_format("INV/2025/01/000123") is True
        assert validate_document_number_format("INV-2025-01-000123") is True

    def test_validate_document_number_format_invalid(self):
        assert validate_document_number_format("invalid") is False
        assert validate_document_number_format("INV/2025/01/123") is True  # non-padded sequence works
        # But this one fails: no separator
        assert validate_document_number_format("INV202501000123") is False

    def test_extract_year_month_success(self):
        result = extract_year_month_from_document_number("INV/2025/01/000123")
        assert result == (2025, 1)
        result2 = extract_year_month_from_document_number("INV/2025/1/123")
        assert result2 == (2025, 1)

    def test_extract_year_month_failure(self):
        assert extract_year_month_from_document_number("invalid") is None

    def test_generate_next_sequence_for_period(self):
        doc = generate_next_sequence_for_period(DocumentType.INVOICE, 2025, 1, 100)
        assert doc.sequence == 101
        assert doc.year == 2025
        assert doc.month == 1

    def test_batch_increment(self):
        start = DocumentNumberVO(DocumentType.INVOICE, 2025, 1, 100)
        batch = batch_increment(start, 3)
        assert len(batch) == 3
        assert batch[0].sequence == 100
        assert batch[1].sequence == 101
        assert batch[2].sequence == 102
        assert all(doc.doc_type == DocumentType.INVOICE for doc in batch)

        # batch of 1
        batch1 = batch_increment(start, 1)
        assert len(batch1) == 1
        assert batch1[0].sequence == 100

        # batch count zero
        batch0 = batch_increment(start, 0)
        assert batch0 == []


# ----------------------------------------------------------------------
# Audit Function Test
# ----------------------------------------------------------------------
class TestAuditFunction:
    def test_add_audit_logs(self, caplog):
        caplog.set_level(logging.INFO)
        add_audit("TEST_ACTION", {"key": "value"})
        assert "AUDIT: TEST_ACTION - {'key': 'value'}" in caplog.text

    def test_add_audit_with_complex_details(self, caplog):
        caplog.set_level(logging.INFO)
        details = {"doc_type": "INV", "year": 2025, "month": 1, "sequence": 123}
        add_audit("CREATE", details)
        assert "AUDIT: CREATE - {'doc_type': 'INV', 'year': 2025, 'month': 1, 'sequence': 123}" in caplog.text


# ----------------------------------------------------------------------
# Alias
# ----------------------------------------------------------------------
def test_alias():
    assert DocumentNumber is DocumentNumberVO