# tests/infrastructure/persistence_orm/test_bank_transaction_table.py
"""
Comprehensive unit tests for infrastructure/persistence_orm/bank_transaction_table.py.
Covers all properties, methods, state transitions, and edge cases.
Uses direct instantiation without a DB session for testing model logic.
"""

from datetime import date
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest

from infrastructure.persistence_orm.bank_transaction_table import BankTransactionTable

# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def sample_transaction():
    """Create a BankTransactionTable instance with default values."""
    return BankTransactionTable(
        id=uuid4(),
        transaction_number="BT-2026-001",
        bank_account_id=uuid4(),
        transaction_date=date(2026, 1, 1),
        transaction_type="deposit",
        amount=Decimal("1000000"),
        currency_code="IDR",
        description="Deposit from customer",
        reference_number="REF-001",
        counterparty_account="1234567890",
        counterparty_name="PT Customer",
        journal_id=None,
        status="pending",
        is_reconciled=False,
        reconciliation_id=None,
        created_by=uuid4(),
        legal_entity_id=uuid4(),
        version=1,
    )


@pytest.fixture
def sample_posted_transaction(sample_transaction):
    """Return a posted transaction."""
    tx = sample_transaction
    tx.status = "posted"
    tx.journal_id = uuid4()
    return tx


@pytest.fixture
def sample_reconciled_transaction(sample_transaction):
    """Return a reconciled transaction."""
    tx = sample_transaction
    tx.status = "reconciled"
    tx.is_reconciled = True
    tx.reconciliation_id = uuid4()
    return tx


# ============================================================================
# TABLE METADATA TESTS
# ============================================================================

class TestBankTransactionTableMetadata:
    def test_tablename_defined(self):
        assert hasattr(BankTransactionTable, "__tablename__")
        assert BankTransactionTable.__tablename__ == "bank_transaction"

    def test_table_args_defined(self):
        assert hasattr(BankTransactionTable, "__table_args__")
        args = BankTransactionTable.__table_args__
        assert isinstance(args, tuple)
        # Check for constraints and indexes
        constraints = [arg for arg in args if hasattr(arg, "name")]
        assert len(constraints) > 0


# ============================================================================
# INSTANTIATION TESTS
# ============================================================================

class TestBankTransactionTableInstantiation:
    def test_instantiation(self, sample_transaction):
        assert isinstance(sample_transaction, BankTransactionTable)
        assert sample_transaction.transaction_number == "BT-2026-001"
        assert sample_transaction.amount == Decimal("1000000")
        assert sample_transaction.status == "pending"
        assert sample_transaction.version == 1

    def test_instantiation_with_defaults(self):
        tx = BankTransactionTable(
            transaction_number="BT-001",
            bank_account_id=uuid4(),
            transaction_date=date.today(),
            transaction_type="deposit",
            amount=Decimal("100"),
            description="Test",
        )
        assert tx.currency_code == "IDR"
        assert tx.status == "pending"
        assert tx.is_reconciled is False
        assert tx.version == 1


# ============================================================================
# PROPERTY TESTS
# ============================================================================

class TestBankTransactionTableProperties:
    def test_is_deposit_true(self, sample_transaction):
        sample_transaction.transaction_type = "deposit"
        assert sample_transaction.is_deposit is True
        assert sample_transaction.is_withdrawal is False
        assert sample_transaction.is_transfer_in is False
        assert sample_transaction.is_transfer_out is False
        assert sample_transaction.is_bank_charge is False
        assert sample_transaction.is_interest is False

    def test_is_withdrawal_true(self, sample_transaction):
        sample_transaction.transaction_type = "withdrawal"
        assert sample_transaction.is_deposit is False
        assert sample_transaction.is_withdrawal is True
        assert sample_transaction.is_transfer_in is False
        assert sample_transaction.is_transfer_out is False
        assert sample_transaction.is_bank_charge is False
        assert sample_transaction.is_interest is False

    def test_is_transfer_in_true(self, sample_transaction):
        sample_transaction.transaction_type = "transfer_in"
        assert sample_transaction.is_deposit is False
        assert sample_transaction.is_withdrawal is False
        assert sample_transaction.is_transfer_in is True
        assert sample_transaction.is_transfer_out is False
        assert sample_transaction.is_bank_charge is False
        assert sample_transaction.is_interest is False

    def test_is_transfer_out_true(self, sample_transaction):
        sample_transaction.transaction_type = "transfer_out"
        assert sample_transaction.is_deposit is False
        assert sample_transaction.is_withdrawal is False
        assert sample_transaction.is_transfer_in is False
        assert sample_transaction.is_transfer_out is True
        assert sample_transaction.is_bank_charge is False
        assert sample_transaction.is_interest is False

    def test_is_bank_charge_true(self, sample_transaction):
        sample_transaction.transaction_type = "bank_charge"
        assert sample_transaction.is_deposit is False
        assert sample_transaction.is_withdrawal is False
        assert sample_transaction.is_transfer_in is False
        assert sample_transaction.is_transfer_out is False
        assert sample_transaction.is_bank_charge is True
        assert sample_transaction.is_interest is False

    def test_is_interest_true(self, sample_transaction):
        sample_transaction.transaction_type = "interest"
        assert sample_transaction.is_deposit is False
        assert sample_transaction.is_withdrawal is False
        assert sample_transaction.is_transfer_in is False
        assert sample_transaction.is_transfer_out is False
        assert sample_transaction.is_bank_charge is False
        assert sample_transaction.is_interest is True

    def test_status_properties(self, sample_transaction):
        # pending
        sample_transaction.status = "pending"
        assert sample_transaction.is_pending is True
        assert sample_transaction.is_posted is False
        assert sample_transaction.is_reconciled is False  # property but also column
        assert sample_transaction.is_cancelled is False

        # posted
        sample_transaction.status = "posted"
        assert sample_transaction.is_pending is False
        assert sample_transaction.is_posted is True
        assert sample_transaction.is_reconciled is False
        assert sample_transaction.is_cancelled is False

        # reconciled
        sample_transaction.status = "reconciled"
        assert sample_transaction.is_pending is False
        assert sample_transaction.is_posted is False
        assert sample_transaction.is_reconciled is True
        assert sample_transaction.is_cancelled is False

        # cancelled
        sample_transaction.status = "cancelled"
        assert sample_transaction.is_pending is False
        assert sample_transaction.is_posted is False
        assert sample_transaction.is_reconciled is False
        assert sample_transaction.is_cancelled is True


# ============================================================================
# METHOD TESTS
# ============================================================================

class TestBankTransactionTableMethods:
    def test_post_success(self, sample_transaction):
        journal_id = uuid4()
        posted_by = uuid4()
        with patch.object(sample_transaction, 'increment_version') as mock_increment:
            sample_transaction.post(journal_id, posted_by)
        assert sample_transaction.status == "posted"
        assert sample_transaction.journal_id == journal_id
        mock_increment.assert_called_once()

    def test_post_invalid_state(self, sample_posted_transaction):
        journal_id = uuid4()
        posted_by = uuid4()
        with pytest.raises(ValueError, match="Cannot post transaction with status posted"):
            sample_posted_transaction.post(journal_id, posted_by)

    def test_post_already_reconciled(self, sample_reconciled_transaction):
        journal_id = uuid4()
        posted_by = uuid4()
        with pytest.raises(ValueError, match="Cannot post transaction with status reconciled"):
            sample_reconciled_transaction.post(journal_id, posted_by)

    def test_post_cancelled(self, sample_transaction):
        sample_transaction.status = "cancelled"
        journal_id = uuid4()
        posted_by = uuid4()
        with pytest.raises(ValueError, match="Cannot post transaction with status cancelled"):
            sample_transaction.post(journal_id, posted_by)

    def test_reconcile_success_from_pending(self, sample_transaction):
        reconciliation_id = uuid4()
        reconciled_by = uuid4()
        with patch.object(sample_transaction, 'increment_version') as mock_increment:
            sample_transaction.reconcile(reconciliation_id, reconciled_by)
        assert sample_transaction.status == "reconciled"
        assert sample_transaction.is_reconciled is True
        assert sample_transaction.reconciliation_id == reconciliation_id
        mock_increment.assert_called_once()

    def test_reconcile_success_from_posted(self, sample_posted_transaction):
        reconciliation_id = uuid4()
        reconciled_by = uuid4()
        with patch.object(sample_posted_transaction, 'increment_version') as mock_increment:
            sample_posted_transaction.reconcile(reconciliation_id, reconciled_by)
        assert sample_posted_transaction.status == "reconciled"
        assert sample_posted_transaction.is_reconciled is True
        assert sample_posted_transaction.reconciliation_id == reconciliation_id
        mock_increment.assert_called_once()

    def test_reconcile_invalid_state_reconciled(self, sample_reconciled_transaction):
        reconciliation_id = uuid4()
        reconciled_by = uuid4()
        with pytest.raises(ValueError, match="Cannot reconcile transaction with status reconciled"):
            sample_reconciled_transaction.reconcile(reconciliation_id, reconciled_by)

    def test_reconcile_invalid_state_cancelled(self, sample_transaction):
        sample_transaction.status = "cancelled"
        reconciliation_id = uuid4()
        reconciled_by = uuid4()
        with pytest.raises(ValueError, match="Cannot reconcile transaction with status cancelled"):
            sample_transaction.reconcile(reconciliation_id, reconciled_by)

    def test_cancel_success_from_pending(self, sample_transaction):
        with patch.object(sample_transaction, 'increment_version') as mock_increment:
            sample_transaction.cancel(uuid4())
        assert sample_transaction.status == "cancelled"
        mock_increment.assert_called_once()

    def test_cancel_success_from_posted(self, sample_posted_transaction):
        with patch.object(sample_posted_transaction, 'increment_version') as mock_increment:
            sample_posted_transaction.cancel(uuid4())
        assert sample_posted_transaction.status == "cancelled"
        mock_increment.assert_called_once()

    def test_cancel_invalid_state_reconciled(self, sample_reconciled_transaction):
        with pytest.raises(ValueError, match="Cannot cancel transaction with status reconciled"):
            sample_reconciled_transaction.cancel(uuid4())

    def test_cancel_invalid_state_cancelled(self, sample_transaction):
        sample_transaction.status = "cancelled"
        with pytest.raises(ValueError, match="Cannot cancel transaction with status cancelled"):
            sample_transaction.cancel(uuid4())


# ============================================================================
# EDGE CASES & NEGATIVE PATHS
# ============================================================================

class TestBankTransactionTableEdgeCases:
    def test_version_increment_on_post(self, sample_transaction):
        old_version = sample_transaction.version
        sample_transaction.post(uuid4(), uuid4())
        assert sample_transaction.version == old_version + 1

    def test_version_increment_on_reconcile(self, sample_transaction):
        old_version = sample_transaction.version
        sample_transaction.reconcile(uuid4(), uuid4())
        assert sample_transaction.version == old_version + 1

    def test_version_increment_on_cancel(self, sample_transaction):
        old_version = sample_transaction.version
        sample_transaction.cancel(uuid4())
        assert sample_transaction.version == old_version + 1

    def test_post_with_none_journal_id(self, sample_transaction):
        # The method expects UUID, but if None is passed, it will store None.
        # We test that it doesn't raise.
        sample_transaction.post(None, uuid4())
        assert sample_transaction.journal_id is None
        assert sample_transaction.status == "posted"

    def test_reconcile_with_none_reconciliation_id(self, sample_transaction):
        # Similar test: None is valid? The type annotation says uuid.UUID, but method doesn't enforce.
        sample_transaction.reconcile(None, uuid4())
        assert sample_transaction.reconciliation_id is None
        assert sample_transaction.status == "reconciled"

    def test_cancel_with_none_user(self, sample_transaction):
        # The method doesn't store cancelled_by, so None is fine.
        sample_transaction.cancel(None)
        assert sample_transaction.status == "cancelled"

    def test_all_transaction_types_properties(self, sample_transaction):
        types = {
            "deposit": ("is_deposit", True),
            "withdrawal": ("is_withdrawal", True),
            "transfer_in": ("is_transfer_in", True),
            "transfer_out": ("is_transfer_out", True),
            "bank_charge": ("is_bank_charge", True),
            "interest": ("is_interest", True),
        }
        for tx_type, (prop, expected) in types.items():
            sample_transaction.transaction_type = tx_type
            # Reset all others
            # We'll just check each property individually
            assert getattr(sample_transaction, prop) is expected
            # Make sure others are False
            for _other_tx_type, (other_prop, _) in types.items():
                if other_prop != prop:
                    assert getattr(sample_transaction, other_prop) is False
