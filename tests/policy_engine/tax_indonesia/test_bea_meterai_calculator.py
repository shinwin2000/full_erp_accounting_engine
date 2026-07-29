# tests/policy_engine/tax_indonesia/test_bea_meterai_calculator.py
"""
Comprehensive tests for bea_meterai_calculator.py.

Covers:
- Enums: BeaMeteraiType, BeaMeteraiStatus
- Exceptions: BeaMeteraiError
- BeaMeteraiDocument: construction, validation
- BeaMeteraiCalculationResult: construction, to_dict
- BeaMeteraiCalculator:
  - calculate, set_rate, is_exempt
  - calculate_bea_meterai (with quantity, exempt cases)
  - calculate_bulk_bea_meterai
  - get_total_bea_meterai
  - get_requirements_summary
  - classmethods: calculate_document_stamp, calculate_cek
  - validate, get_rate, calculate_tax
- Singleton accessor: get_bea_meterai_calculator
- Edge cases: negative amount, zero quantity, rate changes, exempt documents
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from policy_engine.tax_indonesia.bea_meterai_calculator import (
    BeaMeteraiCalculationResult,
    BeaMeteraiCalculator,
    BeaMeteraiDocument,
    BeaMeteraiError,
    BeaMeteraiStatus,
    BeaMeteraiType,
    get_bea_meterai_calculator,
)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def document_id() -> UUID:
    return uuid4()


@pytest.fixture
def sample_document(document_id) -> BeaMeteraiDocument:
    """A standard agreement document with amount mentioned."""
    return BeaMeteraiDocument(
        document_id=document_id,
        document_type=BeaMeteraiType.AGREEMENT,
        document_number="DOC-001",
        date=datetime(2025, 1, 15, tzinfo=UTC),
        amount_mentioned=Decimal("50000000"),
        currency="IDR",
        is_electronic=False,
    )


@pytest.fixture
def receipt_document(document_id) -> BeaMeteraiDocument:
    """A receipt document (exempt if <= 1,000,000)."""
    return BeaMeteraiDocument(
        document_id=document_id,
        document_type=BeaMeteraiType.RECEIPT,
        document_number="REC-001",
        date=datetime(2025, 1, 15, tzinfo=UTC),
        amount_mentioned=Decimal("500000"),
        currency="IDR",
        is_electronic=False,
    )


@pytest.fixture
def large_receipt_document(document_id) -> BeaMeteraiDocument:
    """A receipt document above threshold (subject to bea meterai)."""
    return BeaMeteraiDocument(
        document_id=document_id,
        document_type=BeaMeteraiType.RECEIPT,
        document_number="REC-002",
        date=datetime(2025, 1, 15, tzinfo=UTC),
        amount_mentioned=Decimal("1500000"),
        currency="IDR",
        is_electronic=False,
    )


@pytest.fixture
def bank_statement_document(document_id) -> BeaMeteraiDocument:
    """A bank statement document (exempt)."""
    return BeaMeteraiDocument(
        document_id=document_id,
        document_type=BeaMeteraiType.BANK_STATEMENT,
        document_number="BS-001",
        date=datetime(2025, 1, 15, tzinfo=UTC),
        amount_mentioned=Decimal(0),
        currency="IDR",
        is_electronic=False,
    )


@pytest.fixture
def calculator() -> BeaMeteraiCalculator:
    """Fresh BeaMeteraiCalculator instance."""
    return BeaMeteraiCalculator()


# ============================================================================
# Tests for Enums
# ============================================================================

class TestBeaMeteraiType:
    def test_members(self):
        assert BeaMeteraiType.AGREEMENT.value == "agreement"
        assert BeaMeteraiType.NOTARIAL_DEED.value == "notarial_deed"
        assert BeaMeteraiType.COURT_DOCUMENT.value == "court_document"
        assert BeaMeteraiType.SHARE_CERTIFICATE.value == "share_certificate"
        assert BeaMeteraiType.LETTER_OF_INTENT.value == "letter_of_intent"
        assert BeaMeteraiType.POWER_OF_ATTORNEY.value == "power_of_attorney"
        assert BeaMeteraiType.RECEIPT.value == "receipt"
        assert BeaMeteraiType.BANK_STATEMENT.value == "bank_statement"
        assert BeaMeteraiType.OTHER.value == "other"


class TestBeaMeteraiStatus:
    def test_members(self):
        assert BeaMeteraiStatus.REQUIRED.value == "required"
        assert BeaMeteraiStatus.EXEMPT.value == "exempt"
        assert BeaMeteraiStatus.PAID.value == "paid"
        assert BeaMeteraiStatus.STAMPED.value == "stamped"


# ============================================================================
# Tests for Exception
# ============================================================================

class TestBeaMeteraiError:
    def test_is_exception(self):
        error = BeaMeteraiError("Test error")
        assert isinstance(error, Exception)
        assert str(error) == "Test error"


# ============================================================================
# Tests for BeaMeteraiDocument
# ============================================================================

class TestBeaMeteraiDocument:
    def test_construction_valid(self, sample_document):
        assert sample_document.document_id is not None
        assert sample_document.document_type == BeaMeteraiType.AGREEMENT
        assert sample_document.amount_mentioned == Decimal("50000000")

    def test_negative_amount_raises(self, document_id):
        with pytest.raises(ValueError, match="Amount mentioned cannot be negative"):
            BeaMeteraiDocument(
                document_id=document_id,
                document_type=BeaMeteraiType.AGREEMENT,
                document_number="NEG",
                date=datetime.now(UTC),
                amount_mentioned=Decimal("-1"),
            )


# ============================================================================
# Tests for BeaMeteraiCalculationResult
# ============================================================================

class TestBeaMeteraiCalculationResult:
    def test_construction(self, document_id):
        result = BeaMeteraiCalculationResult(
            document_id=document_id,
            document_type=BeaMeteraiType.AGREEMENT,
            document_number="DOC-001",
            bea_meterai_amount=Decimal("10000"),
            status=BeaMeteraiStatus.REQUIRED,
            quantity=1,
            description="Test",
        )
        assert result.document_id == document_id
        assert result.bea_meterai_amount == Decimal("10000")
        assert result.calculated_at is not None

    def test_to_dict(self, document_id):
        result = BeaMeteraiCalculationResult(
            document_id=document_id,
            document_type=BeaMeteraiType.AGREEMENT,
            document_number="DOC-001",
            bea_meterai_amount=Decimal("10000"),
            status=BeaMeteraiStatus.REQUIRED,
            quantity=2,
            description="Two documents",
        )
        d = result.to_dict()
        assert d["document_id"] == str(document_id)
        assert d["document_type"] == "agreement"
        assert d["bea_meterai_amount"] == "10000"
        assert d["status"] == "required"
        assert d["quantity"] == 2
        assert "calculated_at" in d


# ============================================================================
# Tests for BeaMeteraiCalculator
# ============================================================================

class TestBeaMeteraiCalculator:
    def test_initial_rate(self, calculator):
        assert calculator._rate == Decimal("10000")

    def test_set_rate(self, calculator):
        calculator.set_rate(Decimal("15000"))
        assert calculator._rate == Decimal("15000")

    def test_set_rate_negative_raises(self, calculator):
        with pytest.raises(BeaMeteraiError, match="Bea Meterai rate must be positive"):
            calculator.set_rate(Decimal("-1000"))

    def test_set_rate_zero_raises(self, calculator):
        with pytest.raises(BeaMeteraiError, match="Bea Meterai rate must be positive"):
            calculator.set_rate(Decimal("0"))

    # ---- is_exempt ----

    def test_is_exempt_receipt_below_threshold(self, calculator, receipt_document):
        assert calculator.is_exempt(receipt_document) is True

    def test_is_exempt_receipt_above_threshold(self, calculator, large_receipt_document):
        assert calculator.is_exempt(large_receipt_document) is False

    def test_is_exempt_bank_statement(self, calculator, bank_statement_document):
        assert calculator.is_exempt(bank_statement_document) is True

    def test_is_exempt_agreement(self, calculator, sample_document):
        assert calculator.is_exempt(sample_document) is False

    # ---- calculate_bea_meterai ----

    def test_calculate_bea_meterai_agreement(self, calculator, sample_document):
        result = calculator.calculate_bea_meterai(sample_document, quantity=1)
        assert result.bea_meterai_amount == Decimal("10000")
        assert result.status == BeaMeteraiStatus.REQUIRED
        assert result.quantity == 1

    def test_calculate_bea_meterai_with_quantity(self, calculator, sample_document):
        result = calculator.calculate_bea_meterai(sample_document, quantity=5)
        assert result.bea_meterai_amount == Decimal("50000")
        assert result.quantity == 5

    def test_calculate_bea_meterai_exempt(self, calculator, receipt_document):
        result = calculator.calculate_bea_meterai(receipt_document)
        assert result.bea_meterai_amount == Decimal(0)
        assert result.status == BeaMeteraiStatus.EXEMPT

    def test_calculate_bea_meterai_share_certificate(self, calculator, document_id):
        doc = BeaMeteraiDocument(
            document_id=document_id,
            document_type=BeaMeteraiType.SHARE_CERTIFICATE,
            document_number="SH-001",
            date=datetime.now(UTC),
            amount_mentioned=Decimal("1000000"),
        )
        result = calculator.calculate_bea_meterai(doc, quantity=3)
        # Rate 10000 * 3 * 1 (multiplier)
        assert result.bea_meterai_amount == Decimal("30000")

    def test_calculate_bea_meterai_zero_quantity_raises(self, calculator, sample_document):
        with pytest.raises(BeaMeteraiError, match="Quantity must be positive"):
            calculator.calculate_bea_meterai(sample_document, quantity=0)

    def test_calculate_bea_meterai_negative_quantity_raises(self, calculator, sample_document):
        with pytest.raises(BeaMeteraiError, match="Quantity must be positive"):
            calculator.calculate_bea_meterai(sample_document, quantity=-1)

    # ---- calculate ----

    def test_calculate_returns_decimal(self, calculator, sample_document):
        amount = calculator.calculate(sample_document, quantity=2)
        assert isinstance(amount, Decimal)
        assert amount == Decimal("20000")

    # ---- calculate_bulk_bea_meterai ----

    def test_calculate_bulk_bea_meterai(self, calculator, sample_document, receipt_document, large_receipt_document):
        documents = [sample_document, receipt_document, large_receipt_document]
        results = calculator.calculate_bulk_bea_meterai(documents)
        assert len(results) == 3
        # sample_document: 10000
        # receipt_document: exempt -> 0
        # large_receipt_document: 10000
        assert results[0].bea_meterai_amount == Decimal("10000")
        assert results[1].bea_meterai_amount == Decimal(0)
        assert results[1].status == BeaMeteraiStatus.EXEMPT
        assert results[2].bea_meterai_amount == Decimal("10000")

    # ---- get_total_bea_meterai ----

    def test_get_total_bea_meterai(self, calculator, sample_document, receipt_document, large_receipt_document):
        results = calculator.calculate_bulk_bea_meterai(
            [sample_document, receipt_document, large_receipt_document]
        )
        total = calculator.get_total_bea_meterai(results)
        assert total == Decimal("20000")  # 10000 + 0 + 10000

    def test_get_total_bea_meterai_with_exempt_only(self, calculator, receipt_document):
        results = calculator.calculate_bulk_bea_meterai([receipt_document])
        total = calculator.get_total_bea_meterai(results)
        assert total == Decimal(0)

    # ---- get_requirements_summary ----

    def test_get_requirements_summary(self, calculator):
        summary = calculator.get_requirements_summary()
        assert "standard_rate" in summary
        assert summary["standard_rate"] == "10000"
        assert "exempt_document_types" in summary
        assert "receipt" in summary["exempt_document_types"]
        assert "receipt_threshold" in summary
        assert summary["receipt_threshold"] == "1000000"

    # ---- classmethods ----

    def test_calculate_document_stamp_below_threshold(self):
        amount = BeaMeteraiCalculator.calculate_document_stamp(Decimal("5000000"))
        assert amount == Decimal(0)

    def test_calculate_document_stamp_at_threshold(self):
        amount = BeaMeteraiCalculator.calculate_document_stamp(Decimal("10000000"))
        assert amount == Decimal("10000")

    def test_calculate_document_stamp_above_threshold(self):
        amount = BeaMeteraiCalculator.calculate_document_stamp(Decimal("15000000"))
        assert amount == Decimal("10000")

    def test_calculate_cek_below_threshold(self):
        amount = BeaMeteraiCalculator.calculate_cek(Decimal("4000000"))
        assert amount == Decimal(0)

    def test_calculate_cek_at_threshold(self):
        amount = BeaMeteraiCalculator.calculate_cek(Decimal("5000000"))
        assert amount == Decimal("10000")

    def test_calculate_cek_above_threshold(self):
        amount = BeaMeteraiCalculator.calculate_cek(Decimal("6000000"))
        assert amount == Decimal("10000")

    # ---- validate ----

    def test_validate_always_true(self, calculator):
        assert calculator.validate({}) is True
        assert calculator.validate({"some": "data"}) is True

    # ---- get_rate ----

    def test_get_rate_default(self, calculator):
        assert calculator.get_rate() == Decimal("10000")

    def test_get_rate_after_change(self, calculator):
        calculator.set_rate(Decimal("15000"))
        assert calculator.get_rate() == Decimal("15000")

    def test_get_rate_with_tax_type_ignored(self, calculator):
        assert calculator.get_rate("PPN") == Decimal("10000")

    # ---- calculate_tax ----

    def test_calculate_tax(self, calculator, sample_document):
        tax = calculator.calculate_tax(sample_document, quantity=3)
        assert tax == Decimal("30000")

    def test_calculate_tax_exempt(self, calculator, receipt_document):
        tax = calculator.calculate_tax(receipt_document)
        assert tax == Decimal(0)


# ============================================================================
# Tests for Singleton
# ============================================================================

class TestSingleton:
    def test_get_bea_meterai_calculator(self):
        # Reset singleton
        import policy_engine.tax_indonesia.bea_meterai_calculator as module
        module._bea_meterai_calculator_instance = None
        c1 = get_bea_meterai_calculator()
        c2 = get_bea_meterai_calculator()
        assert c1 is c2
        assert isinstance(c1, BeaMeteraiCalculator)


# ============================================================================
# Additional edge cases
# ============================================================================

class TestEdgeCases:
    def test_calculate_with_electronic_agreement(self, calculator, document_id):
        doc = BeaMeteraiDocument(
            document_id=document_id,
            document_type=BeaMeteraiType.AGREEMENT,
            document_number="E-001",
            date=datetime.now(UTC),
            amount_mentioned=Decimal("1000000"),
            is_electronic=True,
        )
        # Electronic agreement is NOT exempt (is_exempt returns False)
        result = calculator.calculate_bea_meterai(doc)
        assert result.bea_meterai_amount == Decimal("10000")
        assert result.status == BeaMeteraiStatus.REQUIRED

    def test_bulk_with_empty_list(self, calculator):
        results = calculator.calculate_bulk_bea_meterai([])
        assert results == []
        total = calculator.get_total_bea_meterai(results)
        assert total == Decimal(0)

    def test_multiplier_for_other_types(self, calculator, document_id):
        # Types not in MULTIPLIER_TYPES default to multiplier 1
        doc = BeaMeteraiDocument(
            document_id=document_id,
            document_type=BeaMeteraiType.NOTARIAL_DEED,
            document_number="ND-001",
            date=datetime.now(UTC),
            amount_mentioned=Decimal(0),
        )
        result = calculator.calculate_bea_meterai(doc, quantity=2)
        assert result.bea_meterai_amount == Decimal("20000")
