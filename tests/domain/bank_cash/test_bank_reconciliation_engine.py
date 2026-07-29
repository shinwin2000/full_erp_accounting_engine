# test_bank_reconciliation_engine.py
# ===================================
# Comprehensive tests for domain/bank_cash/bank_reconciliation_engine.py.
# Covers enums, value objects, and all reconciliation engine methods.

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from domain.bank_cash.bank_reconciliation_engine import (
    BankReconciliationEngine,
    MatchingMethod,
    ReconciledItemType,
    ReconciliationItem,
    ReconciliationResult,
    ReconciliationStatus,
)


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------
@pytest.fixture
def sample_engine() -> BankReconciliationEngine:
    return BankReconciliationEngine(
        tolerance=Decimal("0.01"),
        date_tolerance_days=3,
        amount_tolerance_percent=Decimal("0.01"),
    )


@pytest.fixture
def sample_book_tx() -> MagicMock:
    """Create a mock book transaction."""
    tx = MagicMock()
    tx.transaction_id = uuid4()
    tx.transaction_date = datetime(2025, 1, 15, 10, 0, tzinfo=UTC)
    tx.amount = Decimal("1000.00")
    tx.is_credit.return_value = False
    tx.reference_number = "REF-001"
    tx.reference = "REF-001"
    tx.description = "Payment"
    tx.status = "posted"
    return tx


@pytest.fixture
def sample_book_tx_credit() -> MagicMock:
    tx = MagicMock()
    tx.transaction_id = uuid4()
    tx.transaction_date = datetime(2025, 1, 16, 10, 0, tzinfo=UTC)
    tx.amount = Decimal("500.00")
    tx.is_credit.return_value = True
    tx.reference_number = "REF-002"
    tx.reference = "REF-002"
    tx.description = "Deposit"
    tx.status = "posted"
    return tx


@pytest.fixture
def sample_statement_tx() -> dict:
    return {
        "reference_number": "REF-001",
        "amount": "1000.00",
        "date": datetime(2025, 1, 15, 10, 0, tzinfo=UTC),
        "description": "Payment",
    }


@pytest.fixture
def sample_statement_tx_credit() -> dict:
    return {
        "reference_number": "REF-002",
        "amount": "500.00",
        "date": datetime(2025, 1, 16, 10, 0, tzinfo=UTC),
        "description": "Deposit",
    }


# ----------------------------------------------------------------------
# Enums
# ----------------------------------------------------------------------
class TestReconciliationStatus:
    def test_members_exist(self):
        assert hasattr(ReconciliationStatus, "BALANCED")
        assert hasattr(ReconciliationStatus, "MISMATCH")
        assert hasattr(ReconciliationStatus, "PENDING")
        assert hasattr(ReconciliationStatus, "IN_PROGRESS")
        assert hasattr(ReconciliationStatus, "COMPLETED")
        assert hasattr(ReconciliationStatus, "CANCELLED")
        assert hasattr(ReconciliationStatus, "APPROVED")
        assert hasattr(ReconciliationStatus, "REJECTED")

    def test_member_is_instance(self):
        assert isinstance(ReconciliationStatus.BALANCED, ReconciliationStatus)


class TestReconciledItemType:
    def test_members_exist(self):
        assert hasattr(ReconciledItemType, "MATCHED")
        assert hasattr(ReconciledItemType, "BOOK_ONLY")
        assert hasattr(ReconciledItemType, "BANK_ONLY")
        assert hasattr(ReconciledItemType, "ADJUSTMENT")
        assert hasattr(ReconciledItemType, "PARTIAL_MATCH")
        assert hasattr(ReconciledItemType, "SUSPICIOUS")

    def test_member_is_instance(self):
        assert isinstance(ReconciledItemType.MATCHED, ReconciledItemType)


class TestMatchingMethod:
    def test_members_exist(self):
        assert hasattr(MatchingMethod, "EXACT")
        assert hasattr(MatchingMethod, "FUZZY")
        assert hasattr(MatchingMethod, "REFERENCE")
        assert hasattr(MatchingMethod, "AMOUNT_DATE")
        assert hasattr(MatchingMethod, "ML")

    def test_member_is_instance(self):
        assert isinstance(MatchingMethod.EXACT, MatchingMethod)


# ----------------------------------------------------------------------
# ReconciliationItem
# ----------------------------------------------------------------------
class TestReconciliationItem:
    def test_construction(self):
        item = ReconciliationItem(
            transaction_id=uuid4(),
            reference="REF-001",
            date=datetime.now(UTC),
            amount=Decimal("1000.00"),
            type=ReconciledItemType.MATCHED,
            description="Test",
            confidence_score=0.95,
            matched_with="tx-123",
            notes="OK",
        )
        assert item.transaction_id is not None
        assert item.reference == "REF-001"
        assert item.amount == Decimal("1000.00")
        assert item.type == ReconciledItemType.MATCHED
        assert item.confidence_score == 0.95

    def test_to_dict(self):
        tx_id = uuid4()
        item = ReconciliationItem(
            transaction_id=tx_id,
            reference="REF-002",
            date=datetime(2025, 1, 1, 12, 0, tzinfo=UTC),
            amount=Decimal("200.50"),
            type=ReconciledItemType.BOOK_ONLY,
            description="Book only",
            confidence_score=0.8,
            matched_with="none",
            notes="Check",
        )
        d = item.to_dict()
        assert d["transaction_id"] == str(tx_id)
        assert d["reference"] == "REF-002"
        assert d["amount"] == "200.50"
        assert d["type"] == "book_only"
        assert d["confidence_score"] == 0.8


# ----------------------------------------------------------------------
# ReconciliationResult
# ----------------------------------------------------------------------
class TestReconciliationResult:
    @pytest.fixture
    def result(self) -> ReconciliationResult:
        return ReconciliationResult(
            reconciliation_id=uuid4(),
            account_id=uuid4(),
            reconciliation_date=datetime(2025, 1, 15, 12, 0, tzinfo=UTC),
            statement_date=datetime(2025, 1, 15, 0, 0, tzinfo=UTC),
            statement_balance=Decimal("5000.00"),
            book_balance=Decimal("5000.00"),
            reconciled_balance=Decimal("5000.00"),
            difference=Decimal("0.00"),
            status=ReconciliationStatus.BALANCED,
            matched_items=[],
            book_only_items=[],
            bank_only_items=[],
            adjustments=[],
            reconciled_by="alice",
        )

    def test_hash_generation(self, result):
        assert result.hash_signature is not None
        assert len(result.hash_signature) == 64
        assert result.verify_hash() is True

    def test_hash_tamper_detection(self, result):
        original_hash = result.hash_signature
        # Modify a field and check hash fails
        tampered = ReconciliationResult(
            reconciliation_id=result.reconciliation_id,
            account_id=result.account_id,
            reconciliation_date=result.reconciliation_date,
            statement_date=result.statement_date,
            statement_balance=result.statement_balance + Decimal("1"),
            book_balance=result.book_balance,
            reconciled_balance=result.reconciled_balance,
            difference=result.difference,
            status=result.status,
            matched_items=result.matched_items,
            book_only_items=result.book_only_items,
            bank_only_items=result.bank_only_items,
            adjustments=result.adjustments,
            reconciled_by=result.reconciled_by,
            created_at=result.created_at,
            hash_signature=original_hash,  # keep original
        )
        assert tampered.verify_hash() is False

    def test_approve(self, result):
        approved = result.approve("bob")
        assert approved.status == ReconciliationStatus.APPROVED
        assert approved.approved_by == "bob"
        assert approved.approved_at is not None
        assert approved.version == 2
        # Original unchanged
        assert result.status == ReconciliationStatus.BALANCED

    def test_to_dict(self, result):
        d = result.to_dict()
        assert d["reconciliation_id"] == str(result.reconciliation_id)
        assert d["status"] == "balanced"
        assert d["matched_count"] == 0
        assert d["book_only_count"] == 0
        assert d["bank_only_count"] == 0
        assert d["hash_signature"] == result.hash_signature


# ----------------------------------------------------------------------
# BankReconciliationEngine
# ----------------------------------------------------------------------
class TestBankReconciliationEngine:
    def test_init(self):
        engine = BankReconciliationEngine()
        assert engine.tolerance == Decimal("0.01")
        assert engine.date_tolerance_days == 3
        assert engine.amount_tolerance_percent == Decimal("0.01")

        engine2 = BankReconciliationEngine(
            tolerance=Decimal("0.5"),
            date_tolerance_days=5,
            amount_tolerance_percent=Decimal("0.5"),
        )
        assert engine2.tolerance == Decimal("0.50")
        assert engine2.date_tolerance_days == 5
        assert engine2.amount_tolerance_percent == Decimal("0.5")

    # ------------------------------------------------------------------
    # reconcile - basic matching
    # ------------------------------------------------------------------
    def test_reconcile_exact_match(self, sample_engine, sample_book_tx, sample_statement_tx):
        account_id = uuid4()
        book_txs = [sample_book_tx]
        statement_txs = [sample_statement_tx]
        result = sample_engine.reconcile(
            account_id=account_id,
            book_transactions=book_txs,
            statement_balance=Decimal("0.00"),  # not used for balance calculation? but important
            statement_date=datetime(2025, 1, 15, 23, 59, tzinfo=UTC),
            statement_transactions=statement_txs,
            reconciled_by="alice",
            auto_approve=False,
        )
        # Check matching
        assert len(result.matched_items) == 1
        assert result.matched_items[0].reference == "REF-001"
        assert result.matched_items[0].type == ReconciledItemType.MATCHED
        assert result.matched_items[0].confidence_score == 1.0
        # No unmatched
        assert len(result.book_only_items) == 0
        assert len(result.bank_only_items) == 0
        # Book balance: 1000 debit? Actually sample_tx has amount 1000 and is_credit False -> book_balance = -1000
        # But we also have statement_balance=0. We need to compute.
        # In reconcile, book_balance is calculated from book_transactions up to statement_date.
        # Since sample_book_tx is debit (is_credit False), book_balance = -1000
        # But statement_balance is 0, so difference = reconciled_balance - statement_balance.
        # Let's calculate: reconciled_balance = book_balance - book_only + bank_only.
        # No book_only, bank_only. reconciled_balance = -1000.
        # difference = -1000 - 0 = -1000, mismatch.
        # For it to be balanced, we need statement_balance = -1000.
        # So we set statement_balance accordingly.
        # We'll adjust test.
        # Better: use statement_balance = -1000, so difference = 0.
        # But we have statement_txs only, statement_balance can be provided separately.
        result2 = sample_engine.reconcile(
            account_id=account_id,
            book_transactions=book_txs,
            statement_balance=Decimal("-1000.00"),
            statement_date=datetime(2025, 1, 15, 23, 59, tzinfo=UTC),
            statement_transactions=statement_txs,
            reconciled_by="alice",
        )
        assert result2.status == ReconciliationStatus.BALANCED
        assert result2.difference == Decimal("0.00")

    def test_reconcile_reference_match_with_opposite_sign(self, sample_engine):
        # Book transaction debit 1000, statement amount +1000 (credit)
        # The engine should match by reference and amount (absolute)
        book_tx = MagicMock()
        book_tx.transaction_id = uuid4()
        book_tx.transaction_date = datetime(2025, 1, 15, 10, 0, tzinfo=UTC)
        book_tx.amount = Decimal("1000.00")
        book_tx.is_credit.return_value = False
        book_tx.reference_number = "REF-001"
        book_tx.reference = "REF-001"
        book_tx.description = "Payment"
        book_tx.status = "posted"

        stmt_tx = {
            "reference_number": "REF-001",
            "amount": "1000.00",  # positive in statement (could be credit)
            "date": datetime(2025, 1, 15, 10, 0, tzinfo=UTC),
            "description": "Payment",
        }

        account_id = uuid4()
        result = sample_engine.reconcile(
            account_id=account_id,
            book_transactions=[book_tx],
            statement_balance=Decimal("-1000.00"),  # book balance -1000, statement balance -1000
            statement_date=datetime(2025, 1, 15, 23, 59, tzinfo=UTC),
            statement_transactions=[stmt_tx],
            reconciled_by="alice",
        )
        assert len(result.matched_items) == 1
        assert result.matched_items[0].amount == Decimal("1000.00")  # statement amount
        assert result.status == ReconciliationStatus.BALANCED

    def test_reconcile_amount_date_match(self, sample_engine):
        # Book transaction with no reference, but same amount and date
        book_tx = MagicMock()
        book_tx.transaction_id = uuid4()
        book_tx.transaction_date = datetime(2025, 1, 15, 10, 0, tzinfo=UTC)
        book_tx.amount = Decimal("500.00")
        book_tx.is_credit.return_value = False
        book_tx.reference_number = None
        book_tx.reference = None
        book_tx.description = "Payment"
        book_tx.status = "posted"

        stmt_tx = {
            "reference_number": "",
            "amount": "500.00",
            "date": datetime(2025, 1, 15, 10, 0, tzinfo=UTC),
            "description": "Payment",
        }

        account_id = uuid4()
        result = sample_engine.reconcile(
            account_id=account_id,
            book_transactions=[book_tx],
            statement_balance=Decimal("-500.00"),
            statement_date=datetime(2025, 1, 15, 23, 59, tzinfo=UTC),
            statement_transactions=[stmt_tx],
            reconciled_by="alice",
        )
        assert len(result.matched_items) == 1
        assert result.matched_items[0].type == ReconciledItemType.MATCHED
        assert result.matched_items[0].confidence_score == 0.9  # from amount_date with delta 0
        assert result.status == ReconciliationStatus.BALANCED

    def test_reconcile_fuzzy_match(self, sample_engine):
        # Amount slightly off but within tolerance percent
        book_tx = MagicMock()
        book_tx.transaction_id = uuid4()
        book_tx.transaction_date = datetime(2025, 1, 15, 10, 0, tzinfo=UTC)
        book_tx.amount = Decimal("100.00")
        book_tx.is_credit.return_value = False
        book_tx.reference_number = None
        book_tx.reference = None
        book_tx.description = "Payment"
        book_tx.status = "posted"

        stmt_tx = {
            "reference_number": "",
            "amount": "100.50",  # 0.5% difference, within tolerance 0.01%? Actually tolerance_percent=0.01%, so 0.01% of 100 = 0.01, so 100.50 is not within.
            "date": datetime(2025, 1, 15, 10, 0, tzinfo=UTC),
            "description": "Payment",
        }
        # With default tolerance percent 0.01, 100.50 - 100 = 0.5, which is 0.5%, not within 0.01%, so not fuzzy matched.
        # We'll increase tolerance percent or adjust amount.
        engine = BankReconciliationEngine(
            tolerance=Decimal("0.01"),
            date_tolerance_days=3,
            amount_tolerance_percent=Decimal("1.0"),  # 1% tolerance
        )
        result = engine.reconcile(
            account_id=uuid4(),
            book_transactions=[book_tx],
            statement_balance=Decimal("-100.00"),
            statement_date=datetime(2025, 1, 15, 23, 59, tzinfo=UTC),
            statement_transactions=[stmt_tx],
            reconciled_by="alice",
        )
        assert len(result.matched_items) == 1
        assert result.matched_items[0].type == ReconciledItemType.MATCHED
        assert result.matched_items[0].confidence_score > 0.5

    def test_reconcile_unmatched_book_only(self, sample_engine, sample_book_tx):
        account_id = uuid4()
        # Book tx with no matching statement
        result = sample_engine.reconcile(
            account_id=account_id,
            book_transactions=[sample_book_tx],
            statement_balance=Decimal("0.00"),
            statement_date=datetime(2025, 1, 15, 23, 59, tzinfo=UTC),
            statement_transactions=[],  # empty statement
            reconciled_by="alice",
        )
        assert len(result.matched_items) == 0
        assert len(result.book_only_items) == 1
        assert result.book_only_items[0].transaction_id == sample_book_tx.transaction_id
        assert result.book_only_items[0].type == ReconciledItemType.BOOK_ONLY
        assert result.status == ReconciliationStatus.MISMATCH  # difference is not zero

    def test_reconcile_unmatched_bank_only(self, sample_engine, sample_statement_tx):
        account_id = uuid4()
        result = sample_engine.reconcile(
            account_id=account_id,
            book_transactions=[],  # empty book
            statement_balance=Decimal("0.00"),
            statement_date=datetime(2025, 1, 15, 23, 59, tzinfo=UTC),
            statement_transactions=[sample_statement_tx],
            reconciled_by="alice",
        )
        assert len(result.matched_items) == 0
        assert len(result.bank_only_items) == 1
        assert result.bank_only_items[0].reference == "REF-001"
        assert result.bank_only_items[0].type == ReconciledItemType.BANK_ONLY
        assert result.status == ReconciliationStatus.MISMATCH

    def test_reconcile_suspicious_large_amount(self, sample_engine):
        # Statement tx with amount > 10,000,000 should be marked suspicious
        stmt_tx = {
            "reference_number": "",
            "amount": "15000000.00",
            "date": datetime.now(UTC),
            "description": "Large transfer",
        }
        result = sample_engine.reconcile(
            account_id=uuid4(),
            book_transactions=[],
            statement_balance=Decimal("0.00"),
            statement_date=datetime.now(UTC),
            statement_transactions=[stmt_tx],
            reconciled_by="alice",
        )
        assert len(result.bank_only_items) == 1
        bank_only = result.bank_only_items[0]
        assert bank_only.type == ReconciledItemType.SUSPICIOUS
        assert bank_only.notes == "Suspicious: Large amount"
        assert result.status == ReconciliationStatus.PENDING

    def test_reconcile_auto_approve_balanced(self, sample_engine, sample_book_tx, sample_statement_tx):
        account_id = uuid4()
        result = sample_engine.reconcile(
            account_id=account_id,
            book_transactions=[sample_book_tx],
            statement_balance=Decimal("-1000.00"),
            statement_date=datetime(2025, 1, 15, 23, 59, tzinfo=UTC),
            statement_transactions=[sample_statement_tx],
            reconciled_by="alice",
            auto_approve=True,
        )
        assert result.status == ReconciliationStatus.APPROVED
        assert result.approved_by == "alice"
        assert result.approved_at is not None

    def test_reconcile_auto_approve_not_balanced(self, sample_engine, sample_book_tx):
        # Not balanced (no matching statement)
        result = sample_engine.reconcile(
            account_id=uuid4(),
            book_transactions=[sample_book_tx],
            statement_balance=Decimal("0.00"),
            statement_date=datetime(2025, 1, 15, 23, 59, tzinfo=UTC),
            statement_transactions=[],
            reconciled_by="alice",
            auto_approve=True,
        )
        assert result.status != ReconciliationStatus.APPROVED
        assert result.status == ReconciliationStatus.MISMATCH

    def test_reconcile_with_gl_balance(self, sample_engine, sample_book_tx, sample_statement_tx):
        account_id = uuid4()
        gl_balance = Decimal("-1000.00")
        result = sample_engine.reconcile(
            account_id=account_id,
            book_transactions=[sample_book_tx],
            statement_balance=Decimal("-1000.00"),
            statement_date=datetime(2025, 1, 15, 23, 59, tzinfo=UTC),
            statement_transactions=[sample_statement_tx],
            reconciled_by="alice",
            gl_balance=gl_balance,
        )
        assert result.gl_balance == gl_balance
        assert result.gl_difference == Decimal("0.00")  # gl_balance == book_balance

        # With mismatch
        gl_balance_mismatch = Decimal("-950.00")
        result2 = sample_engine.reconcile(
            account_id=account_id,
            book_transactions=[sample_book_tx],
            statement_balance=Decimal("-1000.00"),
            statement_date=datetime(2025, 1, 15, 23, 59, tzinfo=UTC),
            statement_transactions=[sample_statement_tx],
            reconciled_by="alice",
            gl_balance=gl_balance_mismatch,
        )
        assert result2.gl_balance == gl_balance_mismatch
        assert result2.gl_difference == Decimal("50.00")  # -950 - (-1000) = 50

    # ------------------------------------------------------------------
    # generate_adjustment_entry
    # ------------------------------------------------------------------
    def test_generate_adjustment_entry_no_difference(self, sample_engine):
        result = ReconciliationResult(
            reconciliation_id=uuid4(),
            account_id=uuid4(),
            reconciliation_date=datetime.now(UTC),
            statement_date=datetime.now(UTC),
            statement_balance=Decimal("1000"),
            book_balance=Decimal("1000"),
            reconciled_balance=Decimal("1000"),
            difference=Decimal("0"),
            status=ReconciliationStatus.BALANCED,
            matched_items=[],
            book_only_items=[],
            bank_only_items=[],
            adjustments=[],
            reconciled_by="alice",
        )
        adj = sample_engine.generate_adjustment_entry(result)
        assert adj is None

    def test_generate_adjustment_entry_positive_difference(self, sample_engine):
        # difference > 0 means book_balance > statement_balance? Actually difference = reconciled_balance - statement_balance.
        # If difference > 0, book balance is higher than statement -> need to reduce book balance.
        result = ReconciliationResult(
            reconciliation_id=uuid4(),
            account_id=uuid4(),
            reconciliation_date=datetime.now(UTC),
            statement_date=datetime(2025, 1, 15, tzinfo=UTC),
            statement_balance=Decimal("1000"),
            book_balance=Decimal("1200"),
            reconciled_balance=Decimal("1200"),
            difference=Decimal("200"),
            status=ReconciliationStatus.MISMATCH,
            matched_items=[],
            book_only_items=[],
            bank_only_items=[],
            adjustments=[],
            reconciled_by="alice",
        )
        adj = sample_engine.generate_adjustment_entry(result)
        assert adj is not None
        assert adj["total_difference"] == "200"
        assert len(adj["lines"]) == 2
        # First line: debit adjustment expense 200
        assert adj["lines"][0]["account"] == "Bank Adjustment Expense"
        assert adj["lines"][0]["debit"] == "200"
        assert adj["lines"][0]["credit"] == "0"
        # Second line: credit Cash 200
        assert adj["lines"][1]["account"] == "Cash in Bank"
        assert adj["lines"][1]["debit"] == "0"
        assert adj["lines"][1]["credit"] == "200"

    def test_generate_adjustment_entry_negative_difference(self, sample_engine):
        result = ReconciliationResult(
            reconciliation_id=uuid4(),
            account_id=uuid4(),
            reconciliation_date=datetime.now(UTC),
            statement_date=datetime(2025, 1, 15, tzinfo=UTC),
            statement_balance=Decimal("1000"),
            book_balance=Decimal("800"),
            reconciled_balance=Decimal("800"),
            difference=Decimal("-200"),
            status=ReconciliationStatus.MISMATCH,
            matched_items=[],
            book_only_items=[],
            bank_only_items=[],
            adjustments=[],
            reconciled_by="alice",
        )
        adj = sample_engine.generate_adjustment_entry(result)
        assert adj is not None
        assert adj["total_difference"] == "-200"
        assert len(adj["lines"]) == 2
        # First line: debit Cash 200
        assert adj["lines"][0]["account"] == "Cash in Bank"
        assert adj["lines"][0]["debit"] == "200"
        assert adj["lines"][0]["credit"] == "0"
        # Second line: credit Adjustment Income 200
        assert adj["lines"][1]["account"] == "Bank Adjustment Income"
        assert adj["lines"][1]["debit"] == "0"
        assert adj["lines"][1]["credit"] == "200"

    # ------------------------------------------------------------------
    # get_reconciliation_summary
    # ------------------------------------------------------------------
    def test_get_reconciliation_summary(self, sample_engine):
        result = ReconciliationResult(
            reconciliation_id=uuid4(),
            account_id=uuid4(),
            reconciliation_date=datetime.now(UTC),
            statement_date=datetime(2025, 1, 15, tzinfo=UTC),
            statement_balance=Decimal("1000"),
            book_balance=Decimal("800"),
            reconciled_balance=Decimal("800"),
            difference=Decimal("-200"),
            status=ReconciliationStatus.MISMATCH,
            matched_items=[],
            book_only_items=[],
            bank_only_items=[],
            adjustments=[],
            reconciled_by="alice",
            gl_balance=Decimal("850"),
            gl_difference=Decimal("50"),
        )
        summary = sample_engine.get_reconciliation_summary(result)
        assert summary["reconciliation_id"] == str(result.reconciliation_id)
        assert summary["is_balanced"] is False
        assert summary["status"] == "mismatch"
        assert summary["gl_balance"] == "850"
        assert summary["gl_difference"] == "50"

    # ------------------------------------------------------------------
    # suggest_matching
    # ------------------------------------------------------------------
    def test_suggest_matching_perfect_match(self, sample_engine, sample_book_tx, sample_statement_tx):
        score = sample_engine.suggest_matching(sample_book_tx, sample_statement_tx)
        # Perfect match: amount exact (0.5), ref exact (0.3), date within tolerance (0.2) => 1.0
        assert score == 1.0

    def test_suggest_matching_partial(self, sample_engine):
        book_tx = MagicMock()
        book_tx.transaction_id = uuid4()
        book_tx.transaction_date = datetime(2025, 1, 15, 10, 0, tzinfo=UTC)
        book_tx.amount = Decimal("100.00")
        book_tx.is_credit.return_value = False
        book_tx.reference_number = "REF-001"
        book_tx.reference = "REF-001"
        book_tx.description = "Payment"

        stmt_tx = {
            "reference_number": "REF-002",
            "amount": "100.50",
            "date": datetime(2025, 1, 18, 10, 0, tzinfo=UTC),  # 3 days diff
            "description": "Payment",
        }
        # Amount diff 0.5% (0.5/100=0.5%) > tolerance 0.01%, so amount part not exact, but within 0.5%? Actually amount_tolerance_percent=0.01 -> 0.01% of 100 = 0.01, so 0.5 is not within, so no amount score.
        # So score only from ref partial? ref not exact, but maybe partial match? suggest_matching does not do partial ref matching, only exact equality.
        # So score should be 0.
        # Adjust tolerance.
        engine = BankReconciliationEngine(
            tolerance=Decimal("0.01"),
            date_tolerance_days=3,
            amount_tolerance_percent=Decimal("1.0"),
        )
        score = engine.suggest_matching(book_tx, stmt_tx)
        # Amount diff 0.5% < 1%, so amount score 0.3, ref not matching, date diff 3 days -> date score 0.2 - 3*0.05 = 0.05. total 0.35.
        # But amount score is 0.3 because diff <= tolerance percent? Actually in code: if abs(book_tx.amount - stmt_amount) <= stmt_amount * self.amount_tolerance_percent / 100: score += 0.3
        # 0.5 <= 100 * 1.0/100 = 1.0 -> True, so 0.3. Date diff <=3 -> 0.2 - 3*0.05 = 0.05. total 0.35.
        assert score == 0.35

    # ------------------------------------------------------------------
    # auto_reconcile (threshold)
    # ------------------------------------------------------------------
    def test_auto_reconcile_low_confidence_becomes_partial_match(self, sample_engine, sample_book_tx):
        # Create a statement that results in low confidence (e.g., fuzzy match with low score)
        # We'll use a fuzzy match scenario by having amount diff within tolerance but not exact, date far.
        book_tx = MagicMock()
        book_tx.transaction_id = uuid4()
        book_tx.transaction_date = datetime(2025, 1, 15, 10, 0, tzinfo=UTC)
        book_tx.amount = Decimal("100.00")
        book_tx.is_credit.return_value = False
        book_tx.reference_number = None
        book_tx.reference = None
        book_tx.description = "Payment"

        stmt_tx = {
            "reference_number": "",
            "amount": "100.50",
            "date": datetime(2025, 1, 18, 10, 0, tzinfo=UTC),  # 3 days diff
            "description": "Payment",
        }
        engine = BankReconciliationEngine(
            tolerance=Decimal("0.01"),
            date_tolerance_days=3,
            amount_tolerance_percent=Decimal("1.0"),
        )
        result = engine.auto_reconcile(
            account_id=uuid4(),
            book_transactions=[book_tx],
            statement_balance=Decimal("-100.00"),
            statement_date=datetime(2025, 1, 18, 23, 59, tzinfo=UTC),
            statement_transactions=[stmt_tx],
            reconciled_by="alice",
            threshold=0.8,  # low confidence (<0.8) should become partial match
        )
        # Check matched item count: 1, but type should be PARTIAL_MATCH
        assert len(result.matched_items) == 1
        item = result.matched_items[0]
        assert item.type == ReconciledItemType.PARTIAL_MATCH
        assert "LOW CONFIDENCE" in item.description
        assert item.notes == "Manual review recommended"

    # ------------------------------------------------------------------
    # find_matching_candidates
    # ------------------------------------------------------------------
    def test_find_matching_candidates(self, sample_engine, sample_book_tx, sample_statement_tx):
        candidates = sample_engine.find_matching_candidates(
            book_transactions=[sample_book_tx],
            statement_transactions=[sample_statement_tx],
            min_confidence=0.5,
        )
        assert len(candidates) == 1
        cand = candidates[0]
        assert cand["statement_reference"] == "REF-001"
        assert cand["confidence"] == 1.0
        assert cand["transaction_id"] == str(sample_book_tx.transaction_id)

    def test_find_matching_candidates_no_match(self, sample_engine):
        book_tx = MagicMock()
        book_tx.transaction_id = uuid4()
        book_tx.transaction_date = datetime(2025, 1, 15, 10, 0, tzinfo=UTC)
        book_tx.amount = Decimal("100.00")
        book_tx.is_credit.return_value = False
        book_tx.reference_number = "REF-001"
        book_tx.reference = "REF-001"
        book_tx.description = "Payment"

        stmt_tx = {
            "reference_number": "REF-002",
            "amount": "1000.00",
            "date": datetime(2025, 1, 15, 10, 0, tzinfo=UTC),
            "description": "Other",
        }
        candidates = sample_engine.find_matching_candidates(
            book_transactions=[book_tx],
            statement_transactions=[stmt_tx],
            min_confidence=0.5,
        )
        assert len(candidates) == 0  # confidence < 0.5

    # ------------------------------------------------------------------
    # calculate_outstanding_items
    # ------------------------------------------------------------------
    def test_calculate_outstanding_items(self, sample_engine, sample_book_tx, sample_book_tx_credit):
        # Create statement with same references to simulate cleared items
        stmt_txs = [
            {"reference_number": "REF-001", "amount": "1000"},
            {"reference_number": "REF-002", "amount": "500"},
        ]
        result = sample_engine.calculate_outstanding_items(
            book_transactions=[sample_book_tx, sample_book_tx_credit],
            statement_transactions=stmt_txs,
        )
        # Both are matched by reference, so no outstanding
        assert Decimal(result["outstanding_deposits"]) == Decimal("0")
        assert Decimal(result["outstanding_checks"]) == Decimal("0")

    def test_calculate_outstanding_items_unmatched(self, sample_engine, sample_book_tx):
        # Statement empty, all book transactions outstanding
        result = sample_engine.calculate_outstanding_items(
            book_transactions=[sample_book_tx],
            statement_transactions=[],
        )
        # sample_book_tx is debit (not credit), so outstanding_checks = 1000
        assert Decimal(result["outstanding_checks"]) == Decimal("1000.00")
        assert Decimal(result["outstanding_deposits"]) == Decimal("0")

    # ------------------------------------------------------------------
    # Edge Cases
    # ------------------------------------------------------------------
    def test_reconcile_with_zero_tolerance(self):
        engine = BankReconciliationEngine(tolerance=Decimal("0"))
        book_tx = MagicMock()
        book_tx.transaction_id = uuid4()
        book_tx.transaction_date = datetime.now(UTC)
        book_tx.amount = Decimal("100.00")
        book_tx.is_credit.return_value = False
        book_tx.reference_number = "REF-001"
        book_tx.reference = "REF-001"

        stmt_tx = {"reference_number": "REF-001", "amount": "100.00", "date": datetime.now(UTC)}
        result = engine.reconcile(
            account_id=uuid4(),
            book_transactions=[book_tx],
            statement_balance=Decimal("-100.00"),
            statement_date=datetime.now(UTC),
            statement_transactions=[stmt_tx],
            reconciled_by="alice",
        )
        assert result.status == ReconciliationStatus.BALANCED
        assert result.difference == Decimal("0")

    def test_reconcile_with_date_tolerance_extended(self):
        engine = BankReconciliationEngine(date_tolerance_days=10)
        book_tx = MagicMock()
        book_tx.transaction_id = uuid4()
        book_tx.transaction_date = datetime(2025, 1, 1, 10, 0, tzinfo=UTC)
        book_tx.amount = Decimal("100.00")
        book_tx.is_credit.return_value = False
        book_tx.reference_number = None
        book_tx.reference = None

        stmt_tx = {
            "reference_number": "",
            "amount": "100.00",
            "date": datetime(2025, 1, 10, 10, 0, tzinfo=UTC),  # 9 days diff, within tolerance
            "description": "",
        }
        result = engine.reconcile(
            account_id=uuid4(),
            book_transactions=[book_tx],
            statement_balance=Decimal("-100.00"),
            statement_date=datetime(2025, 1, 10, 23, 59, tzinfo=UTC),
            statement_transactions=[stmt_tx],
            reconciled_by="alice",
        )
        assert len(result.matched_items) == 1
        assert result.matched_items[0].confidence_score == 0.9 - (9 * 0.05) == 0.45  # 0.9 - 0.45 = 0.45

    # ------------------------------------------------------------------
    # Integration tests with multiple transactions
    # ------------------------------------------------------------------
    def test_reconcile_multiple_matches(self, sample_engine, sample_book_tx, sample_book_tx_credit):
        account_id = uuid4()
        book_txs = [sample_book_tx, sample_book_tx_credit]
        stmt_txs = [
            {"reference_number": "REF-001", "amount": "1000.00", "date": datetime(2025, 1, 15, 10, 0, tzinfo=UTC)},
            {"reference_number": "REF-002", "amount": "500.00", "date": datetime(2025, 1, 16, 10, 0, tzinfo=UTC)},
        ]
        result = sample_engine.reconcile(
            account_id=account_id,
            book_transactions=book_txs,
            statement_balance=Decimal("-1000.00") + Decimal("500.00"),  # book balance = -1000 + 500 = -500
            statement_date=datetime(2025, 1, 16, 23, 59, tzinfo=UTC),
            statement_transactions=stmt_txs,
            reconciled_by="alice",
        )
        assert len(result.matched_items) == 2
        assert result.status == ReconciliationStatus.BALANCED

    def test_reconcile_mixed_unmatched(self, sample_engine, sample_book_tx, sample_book_tx_credit):
        account_id = uuid4()
        book_txs = [sample_book_tx, sample_book_tx_credit]
        # Only one statement matches one, other unmatched
        stmt_txs = [
            {"reference_number": "REF-001", "amount": "1000.00", "date": datetime(2025, 1, 15, 10, 0, tzinfo=UTC)},
        ]
        result = sample_engine.reconcile(
            account_id=account_id,
            book_transactions=book_txs,
            statement_balance=Decimal("-1000.00") + Decimal("500.00"),
            statement_date=datetime(2025, 1, 16, 23, 59, tzinfo=UTC),
            statement_transactions=stmt_txs,
            reconciled_by="alice",
        )
        assert len(result.matched_items) == 1
        assert len(result.book_only_items) == 1  # REF-002 unmatched
        assert result.book_only_items[0].reference == "REF-002"
        # Difference should reflect unmatched
        # book_balance = -500, statement_balance = -500? Actually statement_balance we set to -500 as well, but with one unmatched, difference should be 0? Wait, book_balance includes both, statement_balance is -500, but actual statement balance should be -1000 (only one tx). So difference = reconciled_balance - statement_balance.
        # reconciled_balance = book_balance - book_only = -500 - 500 = -1000
        # statement_balance is given as -500, so difference = -500 -> mismatch.
        # So status should be MISMATCH.
        assert result.status == ReconciliationStatus.MISMATCH
        assert result.difference == Decimal("-500.00")
