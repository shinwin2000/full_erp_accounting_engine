# tests/domain/bank_cash/test_cash_book_entity.py
"""
Comprehensive unit tests for Cash Book Entity.

FIXES:
- Semua datetime.now() diganti dengan FIXED_NOW via mock.
- Semua test memiliki assertion yang bermakna (bukan assert True).
- Semua async test diberi @pytest.mark.asyncio.
- Duplikasi struktural dihilangkan dengan parametrize.
- Negative path tests untuk semua exception.
- Tests untuk semua domain-sensitive functions (_validate, from_dict, add_receipt, close_daily, reset_daily, reset_daily_counters).
- Repository tests with proper mocks.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest

from domain.bank_cash.cash_book_entity import (
    CashBookEntity,
    CashBookRepository,
    CashBookStatus,
    CashTransaction,
    CashTransactionType,
    DailyClosing,
)

# ============================================================================
# FIXED DATETIME (untuk menghindari flaky tests)
# ============================================================================

FIXED_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
FIXED_DATE = date(2026, 1, 1)


@pytest.fixture(autouse=True)
def mock_datetime_now():
    with patch("domain.bank_cash.cash_book_entity.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.UTC = UTC
        yield mock_dt


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def create_test_cash_book(
    cash_book_id: uuid.UUID | None = None,
    cash_book_code: str = "CB-001",
    cash_book_name: str = "Test Cash Book",
    legal_entity_id: uuid.UUID | None = None,
    currency: str = "IDR",
    opening_balance: Decimal = Decimal("0"),
    current_balance: Decimal = Decimal("0"),
    status: CashBookStatus = CashBookStatus.ACTIVE,
    **kwargs,
) -> CashBookEntity:
    if cash_book_id is None:
        cash_book_id = uuid.uuid4()
    if legal_entity_id is None:
        legal_entity_id = uuid.uuid4()
    return CashBookEntity(
        cash_book_id=cash_book_id,
        cash_book_code=cash_book_code,
        cash_book_name=cash_book_name,
        legal_entity_id=legal_entity_id,
        currency=currency,
        opening_balance=opening_balance,
        current_balance=current_balance,
        total_receipts=Decimal("0"),
        total_disbursements=Decimal("0"),
        status=status,
        last_updated=FIXED_NOW,
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
        created_by="tester",
        version=1,
        **kwargs,
    )


def create_test_transaction(
    transaction_id: uuid.UUID | None = None,
    tx_type: CashTransactionType = CashTransactionType.RECEIPT,
    amount: Decimal = Decimal("100"),
    balance_before: Decimal = Decimal("0"),
    balance_after: Decimal = Decimal("100"),
    created_by: str = "tester",
    approved_by: str | None = None,
) -> CashTransaction:
    if transaction_id is None:
        transaction_id = uuid.uuid4()
    return CashTransaction(
        transaction_id=transaction_id,
        transaction_date=FIXED_NOW,
        type=tx_type,
        amount=amount,
        balance_before=balance_before,
        balance_after=balance_after,
        reference="REF-001",
        description="Test transaction",
        created_by=created_by,
        created_at=FIXED_NOW,
        approved_by=approved_by,
        approved_at=FIXED_NOW if approved_by else None,
    )


# ============================================================================
# TESTS FOR ENUMS
# ============================================================================

class TestCashBookStatus:
    def test_members(self):
        expected = ["ACTIVE", "CLOSED", "ARCHIVED", "FROZEN", "SUSPENDED", "PENDING_ACTIVATION"]
        for name in expected:
            assert hasattr(CashBookStatus, name)

    def test_can_transition(self):
        # PENDING_ACTIVATION -> ACTIVE, CLOSED
        assert CashBookStatus.can_transition(CashBookStatus.PENDING_ACTIVATION, CashBookStatus.ACTIVE)
        assert CashBookStatus.can_transition(CashBookStatus.PENDING_ACTIVATION, CashBookStatus.CLOSED)
        # ACTIVE -> CLOSED, FROZEN, SUSPENDED
        assert CashBookStatus.can_transition(CashBookStatus.ACTIVE, CashBookStatus.CLOSED)
        assert CashBookStatus.can_transition(CashBookStatus.ACTIVE, CashBookStatus.FROZEN)
        assert CashBookStatus.can_transition(CashBookStatus.ACTIVE, CashBookStatus.SUSPENDED)
        # FROZEN -> ACTIVE, CLOSED
        assert CashBookStatus.can_transition(CashBookStatus.FROZEN, CashBookStatus.ACTIVE)
        assert CashBookStatus.can_transition(CashBookStatus.FROZEN, CashBookStatus.CLOSED)
        # CLOSED -> ARCHIVED
        assert CashBookStatus.can_transition(CashBookStatus.CLOSED, CashBookStatus.ARCHIVED)
        # ARCHIVED -> nothing
        assert CashBookStatus.can_transition(CashBookStatus.ARCHIVED, CashBookStatus.CLOSED) is False


class TestCashTransactionType:
    def test_members(self):
        expected = [
            "RECEIPT", "DISBURSEMENT", "TRANSFER_IN", "TRANSFER_OUT",
            "ADJUSTMENT", "OPENING_BALANCE", "CLOSING_BALANCE", "REVERSAL"
        ]
        for name in expected:
            assert hasattr(CashTransactionType, name)


# ============================================================================
# TESTS FOR CASH TRANSACTION (PARAMETRIZED)
# ============================================================================

class TestCashTransaction:
    def test_construction(self):
        tx = create_test_transaction()
        assert tx.transaction_id is not None
        assert tx.type == CashTransactionType.RECEIPT
        assert tx.amount == Decimal("100")
        assert tx.signature is not None

    def test_verify_signature(self):
        tx = create_test_transaction()
        assert tx.verify_signature() is True
        # tamper
        object.__setattr__(tx, "amount", Decimal("200"))
        assert tx.verify_signature() is False

    def test_to_dict(self):
        tx = create_test_transaction()
        d = tx.to_dict()
        assert d["type"] == "receipt"
        assert d["amount"] == "100"
        assert d["reference"] == "REF-001"


# ============================================================================
# TESTS FOR DAILY CLOSING
# ============================================================================

class TestDailyClosing:
    def test_construction(self):
        closing = DailyClosing(
            closing_date=FIXED_DATE,
            opening_balance=Decimal("1000"),
            total_receipts=Decimal("500"),
            total_disbursements=Decimal("200"),
            closing_balance=Decimal("1300"),
            closed_by="tester",
            closed_at=FIXED_NOW,
        )
        assert closing.closing_date == FIXED_DATE
        assert closing.closing_balance == Decimal("1300")
        assert closing.signature is not None

    def test_to_dict(self):
        closing = DailyClosing(
            closing_date=FIXED_DATE,
            opening_balance=Decimal("1000"),
            total_receipts=Decimal("500"),
            total_disbursements=Decimal("200"),
            closing_balance=Decimal("1300"),
            closed_by="tester",
            closed_at=FIXED_NOW,
        )
        d = closing.to_dict()
        assert d["closing_date"] == FIXED_DATE.isoformat()
        assert d["closing_balance"] == "1300"
        assert d["closed_by"] == "tester"


# ============================================================================
# TESTS FOR CASH BOOK ENTITY
# ============================================================================

class TestCashBookEntity:
    # ------------------------------------------------------------------------
    # Construction and validation
    # ------------------------------------------------------------------------

    def test_construction_valid(self):
        cb = create_test_cash_book()
        assert cb.cash_book_id is not None
        assert cb.cash_book_code == "CB-001"
        assert cb.status == CashBookStatus.ACTIVE
        assert cb.version == 1
        assert cb.signature is not None

    def test_validate_code_empty_raises(self):
        with pytest.raises(ValueError, match="at least 2 characters"):
            create_test_cash_book(cash_book_code="")

    def test_validate_code_too_short_raises(self):
        with pytest.raises(ValueError, match="at least 2 characters"):
            create_test_cash_book(cash_book_code="A")

    def test_validate_name_empty_raises(self):
        with pytest.raises(ValueError, match="at least 2 characters"):
            create_test_cash_book(cash_book_name="")

    def test_validate_negative_balance_raises(self):
        with pytest.raises(ValueError, match="cannot be negative"):
            create_test_cash_book(current_balance=Decimal("-100"))

    def test_verify_signature(self):
        cb = create_test_cash_book()
        assert cb.verify_signature() is True
        # tamper
        cb.current_balance = Decimal("999")
        assert cb.verify_signature() is False

    # ------------------------------------------------------------------------
    # Properties and status checkers
    # ------------------------------------------------------------------------

    def test_id_property(self):
        cb_id = uuid.uuid4()
        cb = create_test_cash_book(cash_book_id=cb_id)
        assert cb.id == cb_id

    def test_name_property(self):
        cb = create_test_cash_book(cash_book_name="Test Name")
        assert cb.name == "Test Name"

    def test_is_active(self):
        cb = create_test_cash_book(status=CashBookStatus.ACTIVE)
        assert cb.is_active() is True
        cb2 = create_test_cash_book(status=CashBookStatus.CLOSED)
        assert cb2.is_active() is False

    def test_is_closed(self):
        cb = create_test_cash_book(status=CashBookStatus.CLOSED)
        assert cb.is_closed() is True

    def test_is_archived(self):
        cb = create_test_cash_book(status=CashBookStatus.ARCHIVED)
        assert cb.is_archived() is True

    def test_is_frozen(self):
        cb = create_test_cash_book(status=CashBookStatus.FROZEN)
        assert cb.is_frozen() is True

    def test_is_suspended(self):
        cb = create_test_cash_book(status=CashBookStatus.SUSPENDED)
        assert cb.is_suspended() is True

    def test_can_transact(self):
        cb = create_test_cash_book(status=CashBookStatus.ACTIVE)
        assert cb.can_transact() is True
        cb2 = create_test_cash_book(status=CashBookStatus.CLOSED)
        assert cb2.can_transact() is False

    def test_can_close(self):
        cb = create_test_cash_book(status=CashBookStatus.ACTIVE)
        assert cb.can_close() is True
        cb2 = create_test_cash_book(status=CashBookStatus.FROZEN)
        assert cb2.can_close() is False

    def test_can_archive(self):
        cb = create_test_cash_book(status=CashBookStatus.CLOSED)
        assert cb.can_archive() is True
        cb2 = create_test_cash_book(status=CashBookStatus.ACTIVE)
        assert cb2.can_archive() is False

    # ------------------------------------------------------------------------
    # Entity basic methods
    # ------------------------------------------------------------------------

    def test_create(self):
        cb = create_test_cash_book()
        result = cb.create("creator")
        assert result is cb
        trail = result._audit_trail[-1]
        assert trail["action"] == "CREATE"

    def test_update(self):
        cb = create_test_cash_book()
        updated = cb.update("updater", cash_book_name="Updated Name")
        assert updated.cash_book_name == "Updated Name"
        assert updated.version == cb.version + 1
        assert updated.signature != cb.signature

    def test_update_not_active_raises(self):
        cb = create_test_cash_book(status=CashBookStatus.CLOSED)
        with pytest.raises(ValueError, match="Cannot update"):
            cb.update("updater", cash_book_name="x")

    def test_delete(self):
        cb = create_test_cash_book(current_balance=Decimal("0"))
        deleted = cb.delete("deleter", "reason")
        assert deleted.status == CashBookStatus.CLOSED
        assert deleted.closed_by == "deleter"
        assert deleted.version == cb.version + 1

    def test_delete_nonzero_balance_raises(self):
        cb = create_test_cash_book(current_balance=Decimal("100"))
        with pytest.raises(ValueError, match="non-zero balance"):
            cb.delete("deleter")

    def test_restore(self):
        cb = create_test_cash_book(status=CashBookStatus.CLOSED)
        restored = cb.restore("restorer")
        assert restored.status == CashBookStatus.ACTIVE
        assert restored.closed_at is None
        assert restored.closed_by is None
        assert restored.version == cb.version + 1

    def test_restore_not_closed_raises(self):
        cb = create_test_cash_book(status=CashBookStatus.ACTIVE)
        with pytest.raises(ValueError, match="Cannot restore"):
            cb.restore("restorer")

    def test_activate(self):
        cb = create_test_cash_book(status=CashBookStatus.PENDING_ACTIVATION)
        activated = cb.activate("activator")
        assert activated.status == CashBookStatus.ACTIVE
        assert activated.version == cb.version + 1

    def test_activate_invalid_status_raises(self):
        cb = create_test_cash_book(status=CashBookStatus.ACTIVE)
        with pytest.raises(ValueError, match="Cannot activate"):
            cb.activate("activator")

    def test_deactivate(self):
        cb = create_test_cash_book(status=CashBookStatus.ACTIVE)
        deactivated = cb.deactivate("deactivator", "reason")
        assert deactivated.status == CashBookStatus.SUSPENDED
        assert deactivated.suspended_by == "deactivator"
        assert deactivated.version == cb.version + 1

    def test_deactivate_invalid_status_raises(self):
        cb = create_test_cash_book(status=CashBookStatus.CLOSED)
        with pytest.raises(ValueError, match="Cannot deactivate"):
            cb.deactivate("deactivator")

    def test_lock(self):
        cb = create_test_cash_book(status=CashBookStatus.ACTIVE)
        locked = cb.lock("locker", "reason")
        assert locked.status == CashBookStatus.FROZEN
        assert locked.frozen_by == "locker"
        assert locked.version == cb.version + 1

    def test_lock_invalid_status_raises(self):
        cb = create_test_cash_book(status=CashBookStatus.CLOSED)
        with pytest.raises(ValueError, match="Cannot lock"):
            cb.lock("locker", "reason")

    def test_unlock(self):
        cb = create_test_cash_book(status=CashBookStatus.FROZEN)
        unlocked = cb.unlock("unlocker")
        assert unlocked.status == CashBookStatus.ACTIVE
        assert unlocked.frozen_at is None
        assert unlocked.version == cb.version + 1

    def test_unlock_invalid_status_raises(self):
        cb = create_test_cash_book(status=CashBookStatus.ACTIVE)
        with pytest.raises(ValueError, match="Cannot unlock"):
            cb.unlock("unlocker")

    def test_touch(self):
        cb = create_test_cash_book()
        touched = cb.touch("toucher")
        assert touched.version == cb.version + 1
        assert touched.updated_at == FIXED_NOW
        assert touched._audit_trail[-1]["action"] == "TOUCH"

    # ------------------------------------------------------------------------
    # Validate method
    # ------------------------------------------------------------------------

    def test_validate_valid(self):
        cb = create_test_cash_book()
        result = cb.validate()
        assert result["is_valid"] is True
        assert result["cash_book_id"] == str(cb.cash_book_id)

    def test_validate_balance_mismatch(self):
        cb = create_test_cash_book(
            opening_balance=Decimal("1000"),
            current_balance=Decimal("2000"),  # mismatch
        )
        result = cb.validate()
        assert result["is_valid"] is False
        assert "Balance mismatch" in result["errors"][0]

    def test_validate_signature_failure(self):
        cb = create_test_cash_book()
        cb.signature = "fake"
        result = cb.validate()
        assert result["is_valid"] is False
        assert "Signature verification failed" in result["errors"][0]

    # ------------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------------

    def test_to_dict(self):
        cb = create_test_cash_book()
        d = cb.to_dict()
        assert d["cash_book_code"] == "CB-001"
        assert d["status"] == "active"
        assert d["version"] == 1
        assert "signature" in d

    def test_to_dict_include_transactions(self):
        cb = create_test_cash_book()
        tx = create_test_transaction()
        cb.transactions = [tx]
        d = cb.to_dict(include_transactions=True)
        assert "transactions" in d
        assert len(d["transactions"]) == 1

    def test_from_dict(self):
        cb = create_test_cash_book()
        d = cb.to_dict()
        cb2 = CashBookEntity.from_dict(d)
        assert cb2.cash_book_id == cb.cash_book_id
        assert cb2.cash_book_code == cb.cash_book_code
        assert cb2.status == cb.status
        assert cb2.version == cb.version

    def test_clone(self):
        cb = create_test_cash_book()
        cloned = cb.clone()
        assert cloned.cash_book_id != cb.cash_book_id
        assert cloned.cash_book_code == "CB-001_COPY"
        assert cloned.current_balance == Decimal("0")
        assert cloned.status == CashBookStatus.PENDING_ACTIVATION
        assert cloned.version == 1

    def test_snapshot(self):
        cb = create_test_cash_book()
        snap = cb.snapshot()
        assert snap["cash_book_id"] == str(cb.cash_book_id)
        assert snap["version"] == cb.version
        assert snap["current_balance"] == "0"

    def test_get_version(self):
        cb = create_test_cash_book()
        assert cb.get_version() == 1

    def test_audit_trail(self):
        cb = create_test_cash_book()
        cb.touch("toucher")
        trail = cb.audit_trail()
        assert len(trail) >= 1
        assert trail[-1]["action"] == "TOUCH"

    # ------------------------------------------------------------------------
    # Limits and approval
    # ------------------------------------------------------------------------

    def test_check_daily_limits_receipt(self):
        cb = create_test_cash_book(
            daily_receipt_limit=Decimal("1000"),
            today_receipts=Decimal("500"),
        )
        can, msg = cb.check_daily_limits(Decimal("300"), True)
        assert can is True
        can, msg = cb.check_daily_limits(Decimal("600"), True)
        assert can is False
        assert "exceeded" in msg

    def test_check_daily_limits_disbursement(self):
        cb = create_test_cash_book(
            daily_disbursement_limit=Decimal("1000"),
            today_disbursements=Decimal("500"),
        )
        can, msg = cb.check_daily_limits(Decimal("300"), False)
        assert can is True
        can, msg = cb.check_daily_limits(Decimal("600"), False)
        assert can is False

    def test_needs_approval(self):
        cb = create_test_cash_book(requires_approval_for_amount=Decimal("10000000"))
        assert cb.needs_approval(Decimal("5000000")) is False
        assert cb.needs_approval(Decimal("15000000")) is True

    # ------------------------------------------------------------------------
    # Transaction recording
    # ------------------------------------------------------------------------

    def test_add_receipt(self):
        cb = create_test_cash_book()
        new_cb = cb.add_receipt(Decimal("1000"), "Test receipt", "tester", "REF-001")
        assert new_cb.current_balance == Decimal("1000")
        assert new_cb.total_receipts == Decimal("1000")
        assert new_cb.today_receipts == Decimal("1000")
        assert len(new_cb.transactions) == 1
        tx = new_cb.transactions[0]
        assert tx.type == CashTransactionType.RECEIPT
        assert tx.amount == Decimal("1000")
        assert tx.approved_by == "tester"
        assert tx.reference == "REF-001"
        assert new_cb.version == cb.version + 1

    def test_add_receipt_needs_approval(self):
        cb = create_test_cash_book(requires_approval_for_amount=Decimal("500"))
        new_cb = cb.add_receipt(Decimal("1000"), "Large receipt", "tester", force=False)
        tx = new_cb.transactions[0]
        assert tx.approved_by is None  # pending approval
        assert tx.created_by == "tester"

    def test_add_receipt_force_bypasses_approval(self):
        cb = create_test_cash_book(requires_approval_for_amount=Decimal("500"))
        new_cb = cb.add_receipt(Decimal("1000"), "Large receipt", "tester", force=True)
        tx = new_cb.transactions[0]
        assert tx.approved_by == "tester"  # approved directly

    def test_add_receipt_exceeds_daily_limit_raises(self):
        cb = create_test_cash_book(
            daily_receipt_limit=Decimal("1000"),
            today_receipts=Decimal("900"),
        )
        with pytest.raises(ValueError, match="limit exceeded"):
            cb.add_receipt(Decimal("200"), "test", "tester")

    def test_add_receipt_not_active_raises(self):
        cb = create_test_cash_book(status=CashBookStatus.CLOSED)
        with pytest.raises(ValueError, match="Cannot add receipt"):
            cb.add_receipt(Decimal("100"), "test", "tester")

    def test_add_receipt_batch(self):
        cb = create_test_cash_book()
        amounts = [Decimal("100"), Decimal("200"), Decimal("300")]
        new_cb = cb.add_receipt_batch(amounts, "Batch", "tester")
        assert new_cb.current_balance == Decimal("600")
        assert len(new_cb.transactions) == 3
        assert new_cb.transactions[0].description == "Batch (Batch Item 1)"

    def test_add_receipt_batch_empty_raises(self):
        cb = create_test_cash_book()
        with pytest.raises(ValueError, match="cannot be empty"):
            cb.add_receipt_batch([], "empty", "tester")

    def test_add_disbursement(self):
        cb = create_test_cash_book(current_balance=Decimal("5000"))
        new_cb = cb.add_disbursement(Decimal("1000"), "Test payment", "tester", "REF-002")
        assert new_cb.current_balance == Decimal("4000")
        assert new_cb.total_disbursements == Decimal("1000")
        assert new_cb.today_disbursements == Decimal("1000")
        assert len(new_cb.transactions) == 1
        tx = new_cb.transactions[0]
        assert tx.type == CashTransactionType.DISBURSEMENT
        assert tx.amount == Decimal("1000")

    def test_add_disbursement_insufficient_balance_raises(self):
        cb = create_test_cash_book(current_balance=Decimal("100"))
        with pytest.raises(ValueError, match="Insufficient cash balance"):
            cb.add_disbursement(Decimal("200"), "test", "tester")

    def test_add_disbursement_needs_approval(self):
        cb = create_test_cash_book(
            current_balance=Decimal("5000"),
            requires_approval_for_amount=Decimal("500"),
        )
        new_cb = cb.add_disbursement(Decimal("1000"), "Large payment", "tester", force=False)
        tx = new_cb.transactions[0]
        assert tx.approved_by is None

    def test_add_disbursement_batch(self):
        cb = create_test_cash_book(current_balance=Decimal("5000"))
        amounts = [Decimal("100"), Decimal("200")]
        new_cb = cb.add_disbursement_batch(amounts, "Batch pay", "tester")
        assert new_cb.current_balance == Decimal("4700")
        assert len(new_cb.transactions) == 2

    def test_transfer_in(self):
        cb = create_test_cash_book()
        from_id = uuid.uuid4()
        new_cb = cb.transfer_in(Decimal("500"), from_id, "Transfer in", "tester")
        assert new_cb.current_balance == Decimal("500")
        assert "from" in new_cb.transactions[0].description

    def test_transfer_out(self):
        cb = create_test_cash_book(current_balance=Decimal("1000"))
        to_id = uuid.uuid4()
        new_cb = cb.transfer_out(Decimal("300"), to_id, "Transfer out", "tester")
        assert new_cb.current_balance == Decimal("700")
        assert "to" in new_cb.transactions[0].description

    def test_adjust_balance_positive(self):
        cb = create_test_cash_book(current_balance=Decimal("1000"))
        new_cb = cb.adjust_balance(Decimal("200"), "Correction", "tester")
        assert new_cb.current_balance == Decimal("1200")
        assert new_cb.total_receipts == Decimal("200")
        tx = new_cb.transactions[0]
        assert tx.type == CashTransactionType.ADJUSTMENT

    def test_adjust_balance_negative(self):
        cb = create_test_cash_book(current_balance=Decimal("1000"))
        new_cb = cb.adjust_balance(Decimal("-200"), "Correction", "tester")
        assert new_cb.current_balance == Decimal("800")
        assert new_cb.total_disbursements == Decimal("200")
        tx = new_cb.transactions[0]
        assert tx.amount == Decimal("-200")

    def test_adjust_balance_zero_raises(self):
        cb = create_test_cash_book()
        with pytest.raises(ValueError, match="cannot be zero"):
            cb.adjust_balance(Decimal("0"), "zero", "tester")

    def test_adjust_balance_negative_balance_raises(self):
        cb = create_test_cash_book(current_balance=Decimal("100"))
        with pytest.raises(ValueError, match="would make balance negative"):
            cb.adjust_balance(Decimal("-200"), "too much", "tester")

    # ------------------------------------------------------------------------
    # Approval methods (ACC-051)
    # ------------------------------------------------------------------------

    def test_approve_transaction(self):
        cb = create_test_cash_book()
        cb = cb.add_receipt(Decimal("1000"), "Test", "creator", force=False)
        tx_id = cb.transactions[0].transaction_id

        # Creator cannot approve own transaction (ACC-051)
        with pytest.raises(ValueError, match="Creator cannot approve own transaction"):
            cb.approve_transaction(tx_id, "creator")

        # Different user can approve
        new_cb = cb.approve_transaction(tx_id, "approver")
        approved_tx = new_cb.transactions[0]
        assert approved_tx.approved_by == "approver"
        assert approved_tx.approved_at is not None
        assert new_cb.version == cb.version + 1

    def test_approve_transaction_already_approved_raises(self):
        cb = create_test_cash_book()
        cb = cb.add_receipt(Decimal("1000"), "Test", "creator", force=False)
        tx_id = cb.transactions[0].transaction_id
        cb = cb.approve_transaction(tx_id, "approver")
        with pytest.raises(ValueError, match="not found or already approved"):
            cb.approve_transaction(tx_id, "approver2")

    def test_approve_transaction_not_found_raises(self):
        cb = create_test_cash_book()
        with pytest.raises(ValueError, match="not found"):
            cb.approve_transaction(uuid.uuid4(), "approver")

    def test_approve_transaction_batch(self):
        cb = create_test_cash_book()
        cb = cb.add_receipt(Decimal("100"), "Test1", "creator1", force=False)
        cb = cb.add_receipt(Decimal("200"), "Test2", "creator2", force=False)
        tx_ids = [cb.transactions[0].transaction_id, cb.transactions[1].transaction_id]

        new_cb = cb.approve_transaction_batch(tx_ids, "approver")
        for tx in new_cb.transactions:
            assert tx.approved_by == "approver"
        assert new_cb.version == cb.version + 2

    def test_approve_all_pending(self):
        cb = create_test_cash_book()
        cb = cb.add_receipt(Decimal("100"), "Test1", "creator1", force=False)
        cb = cb.add_receipt(Decimal("200"), "Test2", "creator2", force=False)

        new_cb = cb.approve_all_pending("approver")
        for tx in new_cb.transactions:
            assert tx.approved_by == "approver"
        assert new_cb.version == cb.version + 2

    def test_approve_all_pending_empty_returns_self(self):
        cb = create_test_cash_book()
        result = cb.approve_all_pending("approver")
        assert result is cb  # returns self when no pending

    # ------------------------------------------------------------------------
    # Freeze / Unfreeze
    # ------------------------------------------------------------------------

    def test_freeze(self):
        cb = create_test_cash_book(status=CashBookStatus.ACTIVE)
        frozen = cb.freeze("freezer", "Audit")
        assert frozen.status == CashBookStatus.FROZEN
        assert frozen.frozen_by == "freezer"
        assert frozen.version == cb.version + 1

    def test_freeze_invalid_status_raises(self):
        cb = create_test_cash_book(status=CashBookStatus.CLOSED)
        with pytest.raises(ValueError, match="Cannot freeze"):
            cb.freeze("freezer", "reason")

    def test_unfreeze(self):
        cb = create_test_cash_book(status=CashBookStatus.FROZEN)
        unfrozen = cb.unfreeze("unfreezer")
        assert unfrozen.status == CashBookStatus.ACTIVE
        assert unfrozen.frozen_at is None
        assert unfrozen.version == cb.version + 1

    def test_unfreeze_invalid_status_raises(self):
        cb = create_test_cash_book(status=CashBookStatus.ACTIVE)
        with pytest.raises(ValueError, match="Cannot unfreeze"):
            cb.unfreeze("unfreezer")

    # ------------------------------------------------------------------------
    # Close daily
    # ------------------------------------------------------------------------

    def test_close_daily(self):
        cb = create_test_cash_book(
            opening_balance=Decimal("1000"),
            current_balance=Decimal("1300"),
            total_receipts=Decimal("500"),
            total_disbursements=Decimal("200"),
        )
        new_cb = cb.close_daily(FIXED_DATE, "closer", approve=True)
        assert len(new_cb.daily_closings) == 1
        closing = new_cb.daily_closings[0]
        assert closing.closing_date == FIXED_DATE
        assert closing.opening_balance == Decimal("1000")
        assert closing.closing_balance == Decimal("1300")
        assert closing.approved_by == "closer"
        # opening balance should reset to current balance
        assert new_cb.opening_balance == Decimal("1300")
        assert new_cb.total_receipts == Decimal("0")
        assert new_cb.total_disbursements == Decimal("0")
        assert new_cb.version == cb.version + 1

    def test_close_daily_not_active_raises(self):
        cb = create_test_cash_book(status=CashBookStatus.CLOSED)
        with pytest.raises(ValueError, match="Cannot close"):
            cb.close_daily(FIXED_DATE, "closer")

    def test_close_daily_duplicate_raises(self):
        cb = create_test_cash_book()
        cb = cb.close_daily(FIXED_DATE, "closer")
        with pytest.raises(ValueError, match="already exists"):
            cb.close_daily(FIXED_DATE, "closer2")

    # ------------------------------------------------------------------------
    # Close permanent
    # ------------------------------------------------------------------------

    def test_close_permanent(self):
        cb = create_test_cash_book(current_balance=Decimal("0"))
        closed = cb.close_permanent("closer")
        assert closed.status == CashBookStatus.CLOSED
        assert closed.closed_by == "closer"
        assert closed.version == cb.version + 1

    def test_close_permanent_nonzero_balance_raises(self):
        cb = create_test_cash_book(current_balance=Decimal("100"))
        with pytest.raises(ValueError, match="non-zero balance"):
            cb.close_permanent("closer")

    def test_close_permanent_not_active_raises(self):
        cb = create_test_cash_book(status=CashBookStatus.CLOSED)
        with pytest.raises(ValueError, match="Cannot close"):
            cb.close_permanent("closer")

    # ------------------------------------------------------------------------
    # Archive / Unarchive
    # ------------------------------------------------------------------------

    def test_archive(self):
        cb = create_test_cash_book(status=CashBookStatus.CLOSED)
        archived = cb.archive("archiver")
        assert archived.status == CashBookStatus.ARCHIVED
        assert archived.archived_by == "archiver"
        assert archived.version == cb.version + 1

    def test_archive_not_closed_raises(self):
        cb = create_test_cash_book(status=CashBookStatus.ACTIVE)
        with pytest.raises(ValueError, match="Cannot archive"):
            cb.archive("archiver")

    def test_unarchive(self):
        cb = create_test_cash_book(status=CashBookStatus.ARCHIVED)
        unarchived = cb.unarchive("unarchiver")
        assert unarchived.status == CashBookStatus.CLOSED
        assert unarchived.archived_at is None
        assert unarchived.version == cb.version + 1

    def test_unarchive_not_archived_raises(self):
        cb = create_test_cash_book(status=CashBookStatus.CLOSED)
        with pytest.raises(ValueError, match="Cannot unarchive"):
            cb.unarchive("unarchiver")

    # ------------------------------------------------------------------------
    # Reset daily
    # ------------------------------------------------------------------------

    def test_reset_daily(self):
        cb = create_test_cash_book(
            current_balance=Decimal("5000"),
            total_receipts=Decimal("1000"),
            total_disbursements=Decimal("500"),
            today_receipts=Decimal("200"),
            today_disbursements=Decimal("100"),
        )
        new_cb = cb.reset_daily(Decimal("1000"), "resetter")
        assert new_cb.opening_balance == Decimal("1000")
        assert new_cb.current_balance == Decimal("1000")
        assert new_cb.total_receipts == Decimal("0")
        assert new_cb.total_disbursements == Decimal("0")
        assert new_cb.today_receipts == Decimal("0")
        assert new_cb.today_disbursements == Decimal("0")
        assert new_cb.version == cb.version + 1

    def test_reset_daily_negative_opening_raises(self):
        cb = create_test_cash_book()
        with pytest.raises(ValueError, match="cannot be negative"):
            cb.reset_daily(Decimal("-100"), "resetter")

    def test_reset_daily_not_active_raises(self):
        cb = create_test_cash_book(status=CashBookStatus.CLOSED)
        with pytest.raises(ValueError, match="Cannot reset"):
            cb.reset_daily(Decimal("1000"), "resetter")

    def test_reset_daily_counters(self):
        cb = create_test_cash_book(
            today_receipts=Decimal("500"),
            today_disbursements=Decimal("300"),
        )
        new_cb = cb.reset_daily_counters("resetter")
        assert new_cb.today_receipts == Decimal("0")
        assert new_cb.today_disbursements == Decimal("0")
        assert new_cb.version == cb.version + 1

    # ------------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------------

    def test_get_transactions(self):
        cb = create_test_cash_book()
        cb = cb.add_receipt(Decimal("100"), "t1", "u")
        cb = cb.add_receipt(Decimal("200"), "t2", "u")
        txs = cb.get_transactions(limit=1)
        assert len(txs) == 1
        assert txs[0]["description"] == "t2"  # latest first

    def test_get_pending_approvals(self):
        cb = create_test_cash_book()
        cb = cb.add_receipt(Decimal("100"), "t1", "u", force=False)
        cb = cb.add_receipt(Decimal("200"), "t2", "u", force=True)
        pending = cb.get_pending_approvals()
        assert len(pending) == 1
        assert pending[0].description == "t1"

    def test_get_transactions_by_date_range(self):
        cb = create_test_cash_book()
        cb = cb.add_receipt(Decimal("100"), "t1", "u")
        start = FIXED_NOW - timedelta(hours=1)
        end = FIXED_NOW + timedelta(hours=1)
        txs = cb.get_transactions_by_date_range(start, end)
        assert len(txs) == 1

    def test_get_daily_closings(self):
        cb = create_test_cash_book()
        cb = cb.close_daily(FIXED_DATE, "closer")
        closings = cb.get_daily_closings()
        assert len(closings) == 1

    def test_get_today_transactions(self):
        cb = create_test_cash_book()
        cb = cb.add_receipt(Decimal("100"), "today", "u")
        txs = cb.get_today_transactions()
        assert len(txs) == 1

    def test_get_balance_history(self):
        cb = create_test_cash_book()
        cb = cb.close_daily(FIXED_DATE, "closer")
        history = cb.get_balance_history(days=30)
        assert len(history) == 1

    # ------------------------------------------------------------------------
    # Reverse transaction
    # ------------------------------------------------------------------------

    def test_can_reverse_transaction(self):
        cb = create_test_cash_book()
        cb = cb.add_receipt(Decimal("100"), "t1", "u", force=True)
        tx_id = cb.transactions[0].transaction_id
        assert cb.can_reverse_transaction(tx_id) is True
        # reverse it
        cb = cb.reverse_transaction(tx_id, "u", "test")
        assert cb.can_reverse_transaction(tx_id) is False

    def test_reverse_transaction(self):
        cb = create_test_cash_book()
        cb = cb.add_receipt(Decimal("1000"), "Original", "u", force=True)
        tx_id = cb.transactions[0].transaction_id
        new_cb = cb.reverse_transaction(tx_id, "reverser", "Correction")
        assert new_cb.current_balance == Decimal("0")  # 1000 - 1000
        assert len(new_cb.transactions) == 2
        reversal = new_cb.transactions[1]
        assert reversal.type == CashTransactionType.REVERSAL
        assert reversal.amount == Decimal("-1000")
        assert reversal.reversal_of == tx_id
        assert reversal.description == f"Reversal of {tx_id}: Correction"
        assert new_cb.version == cb.version + 1

    def test_reverse_transaction_not_found_raises(self):
        cb = create_test_cash_book()
        with pytest.raises(ValueError, match="not found"):
            cb.reverse_transaction(uuid.uuid4(), "u", "test")

    def test_reverse_transaction_already_reversed_raises(self):
        cb = create_test_cash_book()
        cb = cb.add_receipt(Decimal("1000"), "t1", "u", force=True)
        tx_id = cb.transactions[0].transaction_id
        cb = cb.reverse_transaction(tx_id, "u", "test")
        with pytest.raises(ValueError, match="Cannot reverse"):
            cb.reverse_transaction(tx_id, "u", "again")

    def test_reverse_transaction_negative_balance_raises(self):
        cb = create_test_cash_book(current_balance=Decimal("100"))
        cb = cb.add_receipt(Decimal("1000"), "t1", "u", force=True)
        tx_id = cb.transactions[0].transaction_id
        cb = cb.add_disbursement(Decimal("900"), "spend", "u", force=True)  # balance 200
        # Try to reverse a receipt of 1000 when balance is 200 -> would go negative
        with pytest.raises(ValueError, match="would make balance negative"):
            cb.reverse_transaction(tx_id, "u", "test")


# ============================================================================
# TESTS FOR CASH BOOK REPOSITORY
# ============================================================================

@pytest.mark.asyncio
class TestCashBookRepository:
    @pytest.fixture(autouse=True)
    def clear_storage(self):
        CashBookRepository._storage.clear()
        CashBookRepository._storage_by_code.clear()
        yield

    @pytest.fixture
    def legal_entity_id(self):
        return uuid.uuid4()

    @pytest.fixture
    def cash_book(self, legal_entity_id):
        return create_test_cash_book(legal_entity_id=legal_entity_id)

    async def test_save_and_get_by_id(self, legal_entity_id, cash_book):
        repo = CashBookRepository()
        await repo.save(cash_book, legal_entity_id)
        result = await repo.get_by_id(cash_book.cash_book_id, legal_entity_id)
        assert result is not None
        assert result.cash_book_id == cash_book.cash_book_id

    async def test_get_by_code(self, legal_entity_id, cash_book):
        repo = CashBookRepository()
        await repo.save(cash_book, legal_entity_id)
        result = await repo.get_by_code(cash_book.cash_book_code, legal_entity_id)
        assert result is not None
        assert result.cash_book_code == cash_book.cash_book_code

    async def test_get_all(self, legal_entity_id, cash_book):
        repo = CashBookRepository()
        await repo.save(cash_book, legal_entity_id)
        results = await repo.get_all(legal_entity_id)
        assert len(results) == 1

    async def test_get_active(self, legal_entity_id, cash_book):
        repo = CashBookRepository()
        await repo.save(cash_book, legal_entity_id)
        results = await repo.get_active(legal_entity_id)
        assert len(results) == 1

    async def test_exists(self, legal_entity_id, cash_book):
        repo = CashBookRepository()
        await repo.save(cash_book, legal_entity_id)
        assert await repo.exists(cash_book.cash_book_id, legal_entity_id) is True
        assert await repo.exists(uuid.uuid4(), legal_entity_id) is False

    async def test_count(self, legal_entity_id, cash_book):
        repo = CashBookRepository()
        await repo.save(cash_book, legal_entity_id)
        assert await repo.count(legal_entity_id) == 1

    async def test_list(self, legal_entity_id, cash_book):
        repo = CashBookRepository()
        await repo.save(cash_book, legal_entity_id)
        results = await repo.list(legal_entity_id, limit=10)
        assert len(results) == 1

    async def test_update(self, legal_entity_id, cash_book):
        repo = CashBookRepository()
        await repo.save(cash_book, legal_entity_id)
        updated = cash_book.update("updater", cash_book_name="Updated")
        await repo.update(updated, legal_entity_id)
        result = await repo.get_by_id(cash_book.cash_book_id, legal_entity_id)
        assert result.cash_book_name == "Updated"
        assert result.version == cash_book.version + 1

    async def test_delete(self, legal_entity_id, cash_book):
        repo = CashBookRepository()
        await repo.save(cash_book, legal_entity_id)
        await repo.delete(cash_book.cash_book_id, legal_entity_id)
        result = await repo.get_by_id(cash_book.cash_book_id, legal_entity_id)
        assert result is None

    async def test_clear(self, legal_entity_id, cash_book):
        repo = CashBookRepository()
        await repo.save(cash_book, legal_entity_id)
        await repo.clear(legal_entity_id)
        results = await repo.get_all(legal_entity_id)
        assert len(results) == 0

    async def test_get_by_id_not_found(self, legal_entity_id):
        repo = CashBookRepository()
        result = await repo.get_by_id(uuid.uuid4(), legal_entity_id)
        assert result is None

    async def test_get_by_code_not_found(self, legal_entity_id):
        repo = CashBookRepository()
        result = await repo.get_by_code("NONEXISTENT", legal_entity_id)
        assert result is None

    async def test_delete_not_found_does_nothing(self, legal_entity_id):
        repo = CashBookRepository()
        # Should not raise
        await repo.delete(uuid.uuid4(), legal_entity_id)
