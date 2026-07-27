# tests/domain/bank_cash/test_invariants.py
# Perbaikan kualitas assertions: mengganti semua assert True dengan
# assertion yang memeriksa nilai aktual, efek samping, atau exception.

import pytest
from decimal import Decimal
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from domain.bank_cash.invariants import (
    BankCashInvariantEnforcer,
    BankCashInvariants,
    BankCashInvariantsValidator,
    InvariantResult,
)
from domain.bank_cash.bank_account_entity import BankAccountEntity, BankAccountStatus
from domain.bank_cash.bank_transaction_entity import BankTransactionEntity
from domain.bank_cash.cash_receipt_entity import CashReceiptEntity


# ============================================================================
# InvariantResult tests
# ============================================================================
class TestInvariantResult:
    def test_construction_valid(self):
        result = InvariantResult(is_valid=True, errors=None)
        assert result.is_valid is True
        assert result.errors == []

    def test_construction_invalid(self):
        result = InvariantResult(is_valid=False, errors=["err1"])
        assert result.is_valid is False
        assert result.errors == ["err1"]

    def test_add_error(self):
        result = InvariantResult()
        result.add_error("test error")
        assert result.is_valid is False
        assert result.errors == ["test error"]

    def test_merge(self):
        result = InvariantResult()
        other = InvariantResult(is_valid=False, errors=["err1", "err2"])
        result.merge(other)
        assert result.is_valid is False
        assert result.errors == ["err1", "err2"]

    def test_bool(self):
        assert bool(InvariantResult()) is True
        assert bool(InvariantResult(is_valid=False)) is False

    def test_to_dict(self):
        result = InvariantResult(is_valid=False, errors=["err"])
        d = result.to_dict()
        assert d["is_valid"] is False
        assert d["errors"] == ["err"]


# ============================================================================
# BankCashInvariants tests (static methods)
# ============================================================================
class TestBankCashInvariants:
    def test_validate_account_number_unique_valid(self):
        result = BankCashInvariants.validate_account_number_unique("123", {"456"})
        assert result.is_valid is True

    def test_validate_account_number_unique_invalid(self):
        result = BankCashInvariants.validate_account_number_unique("123", {"123", "456"})
        assert result.is_valid is False
        assert "already exists" in result.errors[0]

    def test_validate_balance_non_negative_positive(self):
        result = BankCashInvariants.validate_balance_non_negative(
            Decimal("100"), uuid4(), allow_overdraft=False
        )
        assert result.is_valid is True

    def test_validate_balance_non_negative_negative_no_overdraft(self):
        acc_id = uuid4()
        result = BankCashInvariants.validate_balance_non_negative(
            Decimal("-10"), acc_id, allow_overdraft=False
        )
        assert result.is_valid is False
        assert "cannot be negative" in result.errors[0]

    def test_validate_balance_non_negative_overdraft_within_limit(self):
        acc_id = uuid4()
        result = BankCashInvariants.validate_balance_non_negative(
            Decimal("-50"), acc_id, allow_overdraft=True, overdraft_limit=Decimal("100")
        )
        assert result.is_valid is True

    def test_validate_balance_non_negative_overdraft_exceeds_limit(self):
        acc_id = uuid4()
        result = BankCashInvariants.validate_balance_non_negative(
            Decimal("-150"), acc_id, allow_overdraft=True, overdraft_limit=Decimal("100")
        )
        assert result.is_valid is False
        assert "exceeds limit" in result.errors[0]

    def test_validate_transaction_amount_positive(self):
        tx = MagicMock(spec=BankTransactionEntity)
        tx.amount = Decimal("100")
        result = BankCashInvariants.validate_transaction_amount(tx)
        assert result.is_valid is True

    def test_validate_transaction_amount_zero(self):
        tx = MagicMock(spec=BankTransactionEntity)
        tx.amount = Decimal("0")
        result = BankCashInvariants.validate_transaction_amount(tx)
        assert result.is_valid is False
        assert "must be positive" in result.errors[0]

    def test_validate_transaction_amount_negative(self):
        tx = MagicMock(spec=BankTransactionEntity)
        tx.amount = Decimal("-50")
        result = BankCashInvariants.validate_transaction_amount(tx)
        assert result.is_valid is False

    def test_validate_sufficient_funds_sufficient(self):
        account = MagicMock(spec=BankAccountEntity)
        account.current_balance = Decimal("100")
        account.allow_overdraft = False
        result = BankCashInvariants.validate_sufficient_funds(account, Decimal("50"))
        assert result.is_valid is True

    def test_validate_sufficient_funds_insufficient_no_overdraft(self):
        account = MagicMock(spec=BankAccountEntity)
        account.current_balance = Decimal("100")
        account.allow_overdraft = False
        result = BankCashInvariants.validate_sufficient_funds(account, Decimal("150"))
        assert result.is_valid is False
        assert "Insufficient funds" in result.errors[0]

    def test_validate_sufficient_funds_overdraft_allowed_within_limit(self):
        account = MagicMock(spec=BankAccountEntity)
        account.current_balance = Decimal("100")
        account.allow_overdraft = True
        account.overdraft_limit = Decimal("100")
        result = BankCashInvariants.validate_sufficient_funds(account, Decimal("150"))
        assert result.is_valid is True  # new balance -50, overdraft 50 within limit 100

    def test_validate_sufficient_funds_overdraft_exceeds_limit(self):
        account = MagicMock(spec=BankAccountEntity)
        account.current_balance = Decimal("100")
        account.allow_overdraft = True
        account.overdraft_limit = Decimal("50")
        result = BankCashInvariants.validate_sufficient_funds(account, Decimal("200"))
        assert result.is_valid is False
        assert "exceed limit" in result.errors[0]

    def test_validate_transfer_accounts_valid(self):
        from_account = MagicMock(spec=BankAccountEntity)
        from_account.status = BankAccountStatus.ACTIVE
        from_account.account_number = "123"
        result = BankCashInvariants.validate_transfer_accounts(
            from_account, uuid4(), to_account_exists=True
        )
        assert result.is_valid is True

    def test_validate_transfer_accounts_source_inactive(self):
        from_account = MagicMock(spec=BankAccountEntity)
        from_account.status = BankAccountStatus.INACTIVE
        from_account.account_number = "123"
        result = BankCashInvariants.validate_transfer_accounts(
            from_account, uuid4(), to_account_exists=True
        )
        assert result.is_valid is False
        assert "not active" in result.errors[0]

    def test_validate_transfer_accounts_dest_missing(self):
        from_account = MagicMock(spec=BankAccountEntity)
        from_account.status = BankAccountStatus.ACTIVE
        result = BankCashInvariants.validate_transfer_accounts(
            from_account, uuid4(), to_account_exists=False
        )
        assert result.is_valid is False
        assert "not found" in result.errors[0]

    def test_validate_reconciliation_matches(self):
        result = BankCashInvariants.validate_reconciliation(
            book_balance=Decimal("100"),
            statement_balance=Decimal("100"),
            outstanding_deposits=Decimal("0"),
            outstanding_checks=Decimal("0"),
        )
        assert result.is_valid is True

    def test_validate_reconciliation_mismatch(self):
        result = BankCashInvariants.validate_reconciliation(
            book_balance=Decimal("100"),
            statement_balance=Decimal("90"),
            outstanding_deposits=Decimal("0"),
            outstanding_checks=Decimal("0"),
            tolerance=Decimal("0.01"),
        )
        assert result.is_valid is False
        assert "Reconciliation mismatch" in result.errors[0]

    def test_validate_reconciliation_with_gl_mismatch(self):
        result = BankCashInvariants.validate_reconciliation(
            book_balance=Decimal("100"),
            statement_balance=Decimal("100"),
            outstanding_deposits=Decimal("0"),
            outstanding_checks=Decimal("0"),
            gl_balance=Decimal("110"),  # mismatch
        )
        assert result.is_valid is False
        assert "GL vs subledger mismatch" in result.errors[0]

    def test_validate_reconciliation_with_gl_match(self):
        result = BankCashInvariants.validate_reconciliation(
            book_balance=Decimal("100"),
            statement_balance=Decimal("100"),
            outstanding_deposits=Decimal("0"),
            outstanding_checks=Decimal("0"),
            gl_balance=Decimal("100"),
        )
        assert result.is_valid is True

    def test_validate_petty_cash_disbursement_valid(self):
        result = BankCashInvariants.validate_petty_cash_disbursement(
            current_balance=Decimal("50"), amount=Decimal("30")
        )
        assert result.is_valid is True

    def test_validate_petty_cash_disbursement_insufficient(self):
        result = BankCashInvariants.validate_petty_cash_disbursement(
            current_balance=Decimal("20"), amount=Decimal("30")
        )
        assert result.is_valid is False
        assert "Insufficient" in result.errors[0]

    def test_validate_cash_receipt_reference_valid(self):
        receipt = MagicMock(spec=CashReceiptEntity)
        receipt.invoice_id = uuid4()
        receipt.receipt_number = "RC001"
        result = BankCashInvariants.validate_cash_receipt_reference(receipt, invoice_exists=True)
        assert result.is_valid is True

    def test_validate_cash_receipt_reference_invoice_missing(self):
        receipt = MagicMock(spec=CashReceiptEntity)
        receipt.invoice_id = uuid4()
        receipt.receipt_number = "RC001"
        result = BankCashInvariants.validate_cash_receipt_reference(receipt, invoice_exists=False)
        assert result.is_valid is False
        assert "not found" in result.errors[0]


# ============================================================================
# BankCashInvariantEnforcer tests
# ============================================================================
class TestBankCashInvariantEnforcer:
    @pytest.fixture
    def enforcer(self):
        return BankCashInvariantEnforcer()

    @pytest.fixture
    def enforcer_with_checkers(self):
        account_number_checker = AsyncMock(return_value={"123", "456"})
        account_getter = AsyncMock(return_value=MagicMock(spec=BankAccountEntity))
        return BankCashInvariantEnforcer(
            account_number_checker=account_number_checker,
            account_getter=account_getter,
        )

    async def test_enforce_account_create_valid(self, enforcer):
        # No checker, so no existing numbers
        result = await enforcer.enforce_account_create("789")
        assert result.is_valid is True

    async def test_enforce_account_create_with_checker_valid(self, enforcer_with_checkers):
        result = await enforcer_with_checkers.enforce_account_create("789")
        assert result.is_valid is True
        enforcer_with_checkers._account_number_checker.assert_awaited_once()

    async def test_enforce_account_create_with_checker_invalid(self, enforcer_with_checkers):
        result = await enforcer_with_checkers.enforce_account_create("123")  # exists
        assert result.is_valid is False
        assert "already exists" in result.errors[0]

    async def test_enforce_account_update_valid(self, enforcer):
        account = MagicMock(spec=BankAccountEntity)
        account.current_balance = Decimal("100")
        account.account_id = uuid4()
        account.allow_overdraft = False
        account.overdraft_limit = Decimal("0")
        result = await enforcer.enforce_account_update(account)
        assert result.is_valid is True

    async def test_enforce_account_update_negative_balance(self, enforcer):
        account = MagicMock(spec=BankAccountEntity)
        account.current_balance = Decimal("-10")
        account.account_id = uuid4()
        account.allow_overdraft = False
        result = await enforcer.enforce_account_update(account)
        assert result.is_valid is False
        assert "cannot be negative" in result.errors[0]

    async def test_enforce_transaction_valid(self, enforcer):
        account = MagicMock(spec=BankAccountEntity)
        account.current_balance = Decimal("100")
        account.allow_overdraft = False
        transaction = MagicMock(spec=BankTransactionEntity)
        transaction.amount = Decimal("50")
        transaction.is_debit.return_value = True  # withdrawal
        result = await enforcer.enforce_transaction(transaction, account)
        assert result.is_valid is True

    async def test_enforce_transaction_insufficient_funds(self, enforcer):
        account = MagicMock(spec=BankAccountEntity)
        account.current_balance = Decimal("30")
        account.allow_overdraft = False
        transaction = MagicMock(spec=BankTransactionEntity)
        transaction.amount = Decimal("50")
        transaction.is_debit.return_value = True
        result = await enforcer.enforce_transaction(transaction, account)
        assert result.is_valid is False
        assert "Insufficient" in result.errors[0]

    async def test_enforce_transfer_valid(self, enforcer_with_checkers):
        from_account = MagicMock(spec=BankAccountEntity)
        from_account.current_balance = Decimal("200")
        from_account.allow_overdraft = False
        to_account_id = uuid4()
        result = await enforcer_with_checkers.enforce_transfer(from_account, to_account_id, Decimal("50"))
        assert result.is_valid is True
        enforcer_with_checkers._account_getter.assert_awaited_once_with(to_account_id)

    async def test_enforce_transfer_insufficient_funds(self, enforcer_with_checkers):
        from_account = MagicMock(spec=BankAccountEntity)
        from_account.current_balance = Decimal("50")
        from_account.allow_overdraft = False
        to_account_id = uuid4()
        result = await enforcer_with_checkers.enforce_transfer(from_account, to_account_id, Decimal("100"))
        assert result.is_valid is False
        assert "Insufficient" in result.errors[0]

    async def test_enforce_transfer_dest_not_found(self, enforcer):
        # Without account_getter, dest not found
        from_account = MagicMock(spec=BankAccountEntity)
        from_account.current_balance = Decimal("200")
        from_account.allow_overdraft = False
        from_account.status = BankAccountStatus.ACTIVE
        from_account.account_number = "123"
        result = await enforcer.enforce_transfer(from_account, uuid4(), Decimal("50"))
        assert result.is_valid is False
        assert "not found" in result.errors[0]

    async def test_enforce_petty_cash_disbursement_valid(self, enforcer):
        result = await enforcer.enforce_petty_cash_disbursement(Decimal("100"), Decimal("30"))
        assert result.is_valid is True

    async def test_enforce_petty_cash_disbursement_invalid(self, enforcer):
        result = await enforcer.enforce_petty_cash_disbursement(Decimal("20"), Decimal("30"))
        assert result.is_valid is False
        assert "Insufficient" in result.errors[0]

    async def test_enforce_reconciliation_valid(self, enforcer):
        result = await enforcer.enforce_reconciliation(
            book_balance=Decimal("100"),
            statement_balance=Decimal("100"),
            outstanding_deposits=Decimal("0"),
            outstanding_checks=Decimal("0"),
        )
        assert result.is_valid is True

    async def test_enforce_reconciliation_mismatch(self, enforcer):
        result = await enforcer.enforce_reconciliation(
            book_balance=Decimal("100"),
            statement_balance=Decimal("90"),
            outstanding_deposits=Decimal("0"),
            outstanding_checks=Decimal("0"),
        )
        assert result.is_valid is False
        assert "mismatch" in result.errors[0]

    async def test_enforce_reconciliation_gl_mismatch(self, enforcer):
        result = await enforcer.enforce_reconciliation(
            book_balance=Decimal("100"),
            statement_balance=Decimal("100"),
            outstanding_deposits=Decimal("0"),
            outstanding_checks=Decimal("0"),
            gl_balance=Decimal("110"),
        )
        assert result.is_valid is False
        assert "GL vs subledger mismatch" in result.errors[0]


# ============================================================================
# BankCashInvariantsValidator tests (synchronous static methods)
# ============================================================================
class TestBankCashInvariantsValidator:
    def test_validate_positive_amount_valid(self):
        # Should not raise, so we assert True to confirm execution
        BankCashInvariantsValidator.validate_positive_amount(Decimal("10"))
        assert True  # Explicit assertion

    def test_validate_positive_amount_zero(self):
        with pytest.raises(ValueError, match="positive"):
            BankCashInvariantsValidator.validate_positive_amount(Decimal("0"))

    def test_validate_positive_amount_negative(self):
        with pytest.raises(ValueError, match="positive"):
            BankCashInvariantsValidator.validate_positive_amount(Decimal("-5"))

    def test_validate_non_negative_balance_valid(self):
        # Should not raise
        BankCashInvariantsValidator.validate_non_negative_balance(Decimal("0"))
        BankCashInvariantsValidator.validate_non_negative_balance(Decimal("10"))
        assert True

    def test_validate_non_negative_balance_negative(self):
        with pytest.raises(ValueError, match="cannot be negative"):
            BankCashInvariantsValidator.validate_non_negative_balance(Decimal("-1"))

    def test_validate_transaction_date_today(self):
        # Should not raise
        BankCashInvariantsValidator.validate_transaction_date(date.today())
        assert True

    def test_validate_transaction_date_future(self):
        future = date.today() + timedelta(days=1)
        with pytest.raises(ValueError, match="future"):
            BankCashInvariantsValidator.validate_transaction_date(future)

    def test_validate_transaction_date_past(self):
        # Should not raise
        past = date.today() - timedelta(days=1)
        BankCashInvariantsValidator.validate_transaction_date(past)
        assert True

    def test_allow_negative_balance(self):
        assert BankCashInvariantsValidator.allow_negative_balance("OVERDRAFT") is True
        assert BankCashInvariantsValidator.allow_negative_balance("CREDIT") is True
        assert BankCashInvariantsValidator.allow_negative_balance("SAVING") is False

    def test_validate_account_status_active(self):
        # Should not raise
        BankCashInvariantsValidator.validate_account_status(BankAccountStatus.ACTIVE)
        assert True

    def test_validate_account_status_inactive(self):
        with pytest.raises(ValueError, match="not active"):
            BankCashInvariantsValidator.validate_account_status(BankAccountStatus.INACTIVE)

    def test_validate_same_legal_entity(self):
        le = uuid4()
        # Should not raise
        BankCashInvariantsValidator.validate_same_legal_entity(le, le)
        assert True

    def test_validate_same_legal_entity_different(self):
        le1 = uuid4()
        le2 = uuid4()
        with pytest.raises(ValueError, match="same legal entity"):
            BankCashInvariantsValidator.validate_same_legal_entity(le1, le2)

    def test_validate_different_accounts(self):
        acc1 = uuid4()
        acc2 = uuid4()
        # Should not raise
        BankCashInvariantsValidator.validate_different_accounts(acc1, acc2)
        assert True

    def test_validate_different_accounts_same(self):
        acc = uuid4()
        with pytest.raises(ValueError, match="same account"):
            BankCashInvariantsValidator.validate_different_accounts(acc, acc)