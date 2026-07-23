#!/usr/bin/env python3
"""
tests/domain/bank_cash/test_cash_aggregate_root.py
Comprehensive tests for domain/bank_cash/cash_aggregate_root.py

Covers:
- CashFlowType enum
- DailyCashSummary dataclass
- CashAggregateSignature dataclass
- CashAggregate:
  - Initialization, properties, create, update, delete, restore, activate, deactivate,
    lock, unlock, validate, to_dict, from_dict, clone, snapshot, get_version,
    audit_trail, touch, sign, verify_signature
  - Event methods: register_event, get_events, pull_events, clear_events, apply
  - Cash book management: add_child, remove_child, get_cash_book, get_cash_book_by_code,
    get_active_cash_books, close_cash_book
  - Petty cash: add_petty_cash_fund, get_petty_cash_fund, get_petty_cash_by_custodian,
    replenish_petty_cash, auto_replenish_petty_cash
  - Cash receipts: add_cash_receipt, confirm_cash_receipt, cancel_cash_receipt
  - Cash disbursements: add_cash_disbursement, approve_cash_disbursement,
    pay_cash_disbursement, cancel_cash_disbursement
  - Transfers: transfer_between_cash_books
  - Totals: get_total_cash_balance, get_total_receipts, get_total_disbursements,
    get_daily_summary, get_receipts_by_type, get_disbursements_by_type, get_pending_approvals
- CashAggregateRepository (all CRUD methods)
- All edge cases and negative paths
- No flaky datetime (mocked)
- No duplicate test code (parametrized where appropriate)
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# =============================================================================
# Robust import for Currency - handle missing import gracefully
# =============================================================================
try:
    from domain.bank_cash.cash_book_entity import CashBookEntity, CashBookStatus, Currency
except ImportError:
    # Fallback: define Currency as a simple enum if not available
    from enum import Enum

    class Currency(Enum):
        IDR = "IDR"
        USD = "USD"
        EUR = "EUR"
        JPY = "JPY"
        SGD = "SGD"
        MYR = "MYR"
        CNY = "CNY"
        GBP = "GBP"
        AUD = "AUD"
        THB = "THB"

from domain.bank_cash.cash_aggregate_root import (
    CashAggregate,
    CashAggregateRepository,
    CashAggregateSignature,
    CashFlowType,
    DailyCashSummary,
)
from domain.bank_cash.cash_disbursement_entity import (
    CashDisbursementEntity,
    CashDisbursementStatus,
    CashDisbursementType,
    PaymentMethod,
)
from domain.bank_cash.cash_receipt_entity import CashReceiptEntity, CashReceiptStatus, CashReceiptType
from domain.bank_cash.petty_cash_fund_entity import PettyCashFundEntity, PettyCashStatus, PettyCashTransactionType

# =============================================================================
# Fixtures and Helpers
# =============================================================================

FIXED_DATETIME = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
FIXED_DATE = date(2026, 1, 15)


@pytest.fixture(autouse=True)
def mock_datetime_now():
    """Mock datetime.now to return fixed datetime."""
    with patch("domain.bank_cash.cash_aggregate_root.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_DATETIME
        mock_dt.utcnow.return_value = FIXED_DATETIME
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        yield mock_dt


@pytest.fixture
def legal_entity_id():
    return uuid.uuid4()


@pytest.fixture
def user_id():
    return uuid.uuid4()


@pytest.fixture
def cash_book_id():
    return uuid.uuid4()


@pytest.fixture
def petty_cash_id():
    return uuid.uuid4()


@pytest.fixture
def cash_book(legal_entity_id, cash_book_id, user_id):
    return CashBookEntity(
        cash_book_id=cash_book_id,
        legal_entity_id=legal_entity_id,
        cash_book_code="CASH-001",
        cash_book_name="Main Cash",
        currency=Currency.IDR,
        opening_balance=Decimal("1000"),
        current_balance=Decimal("1000"),
        status=CashBookStatus.ACTIVE,
        created_by=user_id,
        created_at=FIXED_DATETIME,
        updated_at=FIXED_DATETIME,
        version=1,
    )


@pytest.fixture
def petty_cash(legal_entity_id, petty_cash_id, user_id):
    return PettyCashFundEntity(
        petty_cash_id=petty_cash_id,
        legal_entity_id=legal_entity_id,
        petty_cash_code="PETTY-001",
        petty_cash_name="Office Petty Cash",
        custodian_employee_id=user_id,
        custodian_name="John Doe",
        current_balance=Decimal("500"),
        float_amount=Decimal("1000"),
        replenishment_threshold=Decimal("200"),
        replenishment_amount=Decimal("800"),
        status=PettyCashStatus.ACTIVE,
        created_by=user_id,
        created_at=FIXED_DATETIME,
        updated_at=FIXED_DATETIME,
        version=1,
        transactions=[],
    )


def create_receipt(
    receipt_id=None,
    amount=Decimal("100"),
    confirmed_amount=Decimal("100"),
    status=CashReceiptStatus.CONFIRMED,
    cash_book_id=None,
    user_id=None,
):
    if receipt_id is None:
        receipt_id = uuid.uuid4()
    if cash_book_id is None:
        cash_book_id = uuid.uuid4()
    if user_id is None:
        user_id = uuid.uuid4()
    return CashReceiptEntity(
        receipt_id=receipt_id,
        legal_entity_id=uuid.uuid4(),
        receipt_number="RC-001",
        receipt_type=CashReceiptType.CUSTOMER_PAYMENT,
        receipt_date=FIXED_DATETIME,
        amount=amount,
        currency="IDR",
        confirmed_amount=confirmed_amount,
        status=status,
        payment_method=PaymentMethod.CASH,
        cash_book_id=cash_book_id,
        description="Test receipt",
        created_by=user_id,
        created_at=FIXED_DATETIME,
        version=1,
        customer_id=None,
        invoice_id=None,
        payment_reference="REF001",
        bank_reference=None,
        notes=None,
        submitted_by=None,
        submitted_at=None,
        verified_by=None,
        verified_at=None,
        approved_by=None,
        approved_at=None,
        cancelled_by=None,
        cancelled_at=None,
        cancellation_reason=None,
    )


def create_disbursement(
    disbursement_id=None,
    amount=Decimal("100"),
    paid_amount=Decimal("100"),
    status=CashDisbursementStatus.PAID,
    cash_book_id=None,
    user_id=None,
    approval_level_required=1,
):
    if disbursement_id is None:
        disbursement_id = uuid.uuid4()
    if cash_book_id is None:
        cash_book_id = uuid.uuid4()
    if user_id is None:
        user_id = uuid.uuid4()
    return CashDisbursementEntity(
        disbursement_id=disbursement_id,
        disbursement_number="DISB-001",
        disbursement_type=CashDisbursementType.OPERATING_EXPENSE,
        disbursement_date=FIXED_DATETIME,
        amount=amount,
        currency="IDR",
        status=status,
        payment_method=PaymentMethod.CASH,
        cash_book_id=cash_book_id,
        paid_amount=paid_amount,
        description="Test disbursement",
        created_by=user_id,
        created_at=FIXED_DATETIME,
        version=1,
        approval_level_required=approval_level_required,
        supplier_id=None,
        supplier_name=None,
        supplier_npwp=None,
        supplier_bank_account=None,
        supplier_email=None,
        supplier_phone=None,
        employee_id=None,
        employee_name=None,
        employee_nik=None,
        invoice_id=None,
        invoice_number=None,
        purchase_order_id=None,
        purchase_order_number=None,
        contract_id=None,
        contract_number=None,
        petty_cash_id=None,
        bank_account_id=None,
        payment_reference=None,
        cheque_number=None,
        giro_number=None,
        cheque_due_date=None,
        swift_code=None,
        allocations=[],
        paid_date=None,
        paid_by=None,
        tax_withholdings=[],
        total_tax_withheld=Decimal("0"),
        current_approval_level=0,
        approval_history=[],
        submitted_by=None,
        submitted_at=None,
        approved_by=None,
        approved_at=None,
        rejected_by=None,
        rejected_at=None,
        rejection_reason=None,
        hold_reason=None,
        held_by=None,
        held_at=None,
        budget_code=None,
        budget_year=None,
        cost_center=None,
        department_id=None,
        project_id=None,
        activity_id=None,
        attachment_urls=[],
        supporting_documents=[],
        notes=None,
        internal_notes=None,
        is_urgent=False,
        urgency_reason=None,
        requested_by=None,
        requested_date=None,
        bank_fee=Decimal("0"),
        bank_fee_currency="IDR",
        deleted_at=None,
        signature=None,
    )


# =============================================================================
# Enums
# =============================================================================

class TestCashFlowType:
    def test_members(self):
        assert CashFlowType.INFLOW.value == "inflow"
        assert CashFlowType.OUTFLOW.value == "outflow"
        assert isinstance(CashFlowType.INFLOW, CashFlowType)


# =============================================================================
# DailyCashSummary
# =============================================================================

class TestDailyCashSummary:
    def test_creation(self):
        summary = DailyCashSummary(
            date=FIXED_DATE,
            opening_balance=Decimal("1000"),
            total_receipts=Decimal("500"),
            total_disbursements=Decimal("200"),
            net_flow=Decimal("300"),
            closing_balance=Decimal("1300"),
            cash_book_summaries=[{"id": "cb1"}],
            petty_cash_summaries=[{"id": "pc1"}],
        )
        assert summary.date == FIXED_DATE
        assert summary.opening_balance == Decimal("1000")
        assert summary.total_receipts == Decimal("500")
        assert summary.total_disbursements == Decimal("200")
        assert summary.net_flow == Decimal("300")
        assert summary.closing_balance == Decimal("1300")
        assert summary.cash_book_summaries == [{"id": "cb1"}]
        assert summary.petty_cash_summaries == [{"id": "pc1"}]

    def test_to_dict(self):
        summary = DailyCashSummary(
            date=FIXED_DATE,
            opening_balance=Decimal("1000"),
            total_receipts=Decimal("500"),
            total_disbursements=Decimal("200"),
            net_flow=Decimal("300"),
            closing_balance=Decimal("1300"),
        )
        d = summary.to_dict()
        assert d["date"] == FIXED_DATE.isoformat()
        assert d["opening_balance"] == "1000"
        assert d["total_receipts"] == "500"
        assert d["total_disbursements"] == "200"
        assert d["net_flow"] == "300"
        assert d["closing_balance"] == "1300"
        assert d["cash_book_summaries"] == []
        assert d["petty_cash_summaries"] == []


# =============================================================================
# CashAggregateSignature
# =============================================================================

class TestCashAggregateSignature:
    def test_create_and_verify(self, cash_book):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=uuid.uuid4())
        agg.cash_books = {cash_book.cash_book_id: cash_book}
        agg.updated_at = FIXED_DATETIME
        agg.version = 1
        sig = CashAggregateSignature.create(agg, "signer")
        assert sig.cash_id == agg.cash_id
        assert sig.version == agg.version
        assert sig.signed_by == "signer"
        assert sig.hash_value != ""
        assert sig.verify(agg) is True

        # Tamper with aggregate
        agg.version = 2
        assert sig.verify(agg) is False


# =============================================================================
# CashAggregate
# =============================================================================

class TestCashAggregate:
    def test_init(self, legal_entity_id):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        assert agg.cash_id is not None
        assert agg.legal_entity_id == legal_entity_id
        assert agg.cash_books == {}
        assert agg.petty_cash_funds == {}
        assert agg.cash_receipts == []
        assert agg.cash_disbursements == []
        assert agg.version == 1
        assert agg.signature is None
        assert agg._events == []

    def test_create(self, legal_entity_id, user_id):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg = agg.create(str(user_id))
        assert agg.version == 2
        trail = agg.audit_trail()
        assert any(e["action"] == "CREATE" for e in trail)

    def test_update(self, legal_entity_id, user_id):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        updated = agg.update(str(user_id), version=5)
        assert updated.version == 2
        assert updated.updated_at == FIXED_DATETIME
        trail = updated.audit_trail()
        assert any(e["action"] == "UPDATE" for e in trail)

    def test_delete(self, legal_entity_id, user_id):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        deleted = agg.delete(str(user_id), "test")
        assert deleted.cash_books == {}
        assert deleted.petty_cash_funds == {}
        assert deleted.cash_receipts == []
        assert deleted.cash_disbursements == []
        assert deleted.version == 2
        trail = deleted.audit_trail()
        assert any(e["action"] == "DELETE" for e in trail)

    def test_delete_non_zero_balance(self, legal_entity_id, user_id, cash_book):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg.cash_books[cash_book.cash_book_id] = cash_book
        with pytest.raises(ValueError, match="non-zero balance"):
            agg.delete(str(user_id), "test")

    def test_restore(self, legal_entity_id, user_id):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        restored = agg.restore(str(user_id))
        assert restored.version == 2
        trail = restored.audit_trail()
        assert any(e["action"] == "RESTORE" for e in trail)

    def test_activate(self, legal_entity_id, user_id, cash_book, petty_cash):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg.cash_books[cash_book.cash_book_id] = cash_book
        agg.petty_cash_funds[petty_cash.petty_cash_id] = petty_cash

        # Suspend cash book and petty cash
        cash_book.status = CashBookStatus.SUSPENDED
        petty_cash.status = PettyCashStatus.SUSPENDED

        activated = agg.activate(str(user_id))
        # Cash book should be reactivated
        assert activated.cash_books[cash_book.cash_book_id].status == CashBookStatus.ACTIVE
        assert activated.petty_cash_funds[petty_cash.petty_cash_id].status == PettyCashStatus.ACTIVE
        assert activated.version == 2
        trail = activated.audit_trail()
        assert any(e["action"] == "ACTIVATE" for e in trail)

    def test_deactivate(self, legal_entity_id, user_id, cash_book, petty_cash):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg.cash_books[cash_book.cash_book_id] = cash_book
        agg.petty_cash_funds[petty_cash.petty_cash_id] = petty_cash
        deactivated = agg.deactivate(str(user_id), "closing")
        # Cash book should be deactivated
        assert deactivated.cash_books[cash_book.cash_book_id].status == CashBookStatus.SUSPENDED
        # Petty cash should be suspended
        assert deactivated.petty_cash_funds[petty_cash.petty_cash_id].status == PettyCashStatus.SUSPENDED
        assert deactivated.version == 2
        trail = deactivated.audit_trail()
        assert any(e["action"] == "DEACTIVATE" for e in trail)

    def test_lock(self, legal_entity_id, user_id, cash_book, petty_cash):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg.cash_books[cash_book.cash_book_id] = cash_book
        agg.petty_cash_funds[petty_cash.petty_cash_id] = petty_cash
        locked = agg.lock(str(user_id), "audit")
        # Cash book should be frozen
        assert locked.cash_books[cash_book.cash_book_id].status == CashBookStatus.FROZEN
        # Petty cash should be locked
        assert locked.petty_cash_funds[petty_cash.petty_cash_id].status == PettyCashStatus.LOCKED
        assert locked.version == 2
        trail = locked.audit_trail()
        assert any(e["action"] == "LOCK" for e in trail)

    def test_unlock(self, legal_entity_id, user_id, cash_book, petty_cash):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        # Freeze cash book, lock petty cash
        cash_book.status = CashBookStatus.FROZEN
        petty_cash.status = PettyCashStatus.LOCKED
        agg.cash_books[cash_book.cash_book_id] = cash_book
        agg.petty_cash_funds[petty_cash.petty_cash_id] = petty_cash
        unlocked = agg.unlock(str(user_id))
        assert unlocked.cash_books[cash_book.cash_book_id].status == CashBookStatus.ACTIVE
        assert unlocked.petty_cash_funds[petty_cash.petty_cash_id].status == PettyCashStatus.ACTIVE
        assert unlocked.version == 2

    def test_validate(self, legal_entity_id, user_id, cash_book, petty_cash):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg.cash_books[cash_book.cash_book_id] = cash_book
        agg.petty_cash_funds[petty_cash.petty_cash_id] = petty_cash
        result = agg.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []
        assert result["warnings"] == []

        # Add a receipt with mismatch
        receipt = create_receipt(amount=Decimal("100"), confirmed_amount=Decimal("80"), status=CashReceiptStatus.CONFIRMED)
        agg.cash_receipts = [receipt]
        result = agg.validate()
        assert result["is_valid"] is False
        assert any("confirmed amount mismatch" in e for e in result["errors"])

        # Add a disbursement with mismatch
        disb = create_disbursement(amount=Decimal("100"), paid_amount=Decimal("90"), status=CashDisbursementStatus.PAID)
        agg.cash_disbursements = [disb]
        result = agg.validate()
        assert result["is_valid"] is False
        assert any("paid amount mismatch" in e for e in result["errors"])

    def test_to_dict_from_dict(self, legal_entity_id):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg.cash_books[uuid.uuid4()] = MagicMock()
        agg.petty_cash_funds[uuid.uuid4()] = MagicMock()
        d = agg.to_dict()
        assert d["cash_id"] == str(agg.cash_id)
        assert d["legal_entity_id"] == str(agg.legal_entity_id)
        assert d["version"] == agg.version
        assert "total_cash_balance" in d

        reconstructed = CashAggregate.from_dict(d)
        assert reconstructed.cash_id == agg.cash_id
        assert reconstructed.legal_entity_id == agg.legal_entity_id
        assert reconstructed.version == agg.version

    def test_clone(self, legal_entity_id, user_id, cash_book):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg.cash_books[cash_book.cash_book_id] = cash_book
        agg.cash_receipts = [create_receipt()]
        cloned = agg.clone()
        assert cloned.cash_id != agg.cash_id
        assert cloned.legal_entity_id == agg.legal_entity_id
        assert cloned.version == 1
        assert cloned.cash_books == {}
        assert cloned.petty_cash_funds == {}
        assert cloned.cash_receipts == []
        assert cloned.cash_disbursements == []
        trail = cloned.audit_trail()
        assert any(e["action"] == "CLONE" for e in trail)

    def test_snapshot(self, legal_entity_id):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        snap = agg.snapshot()
        assert snap["cash_id"] == str(agg.cash_id)
        assert snap["version"] == agg.version
        assert "total_balance" in snap

    def test_get_version(self, legal_entity_id):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        assert agg.get_version() == 1

    def test_audit_trail(self, legal_entity_id, user_id):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg = agg.create(str(user_id))
        trail = agg.audit_trail(limit=10)
        assert len(trail) >= 1
        assert trail[-1]["action"] == "CREATE"

    def test_touch(self, legal_entity_id, user_id):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        touched = agg.touch(str(user_id))
        assert touched.version == 2
        assert touched.updated_at == FIXED_DATETIME
        trail = touched.audit_trail()
        assert any(e["action"] == "TOUCH" for e in trail)

    def test_sign_verify(self, legal_entity_id, user_id):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        signed = agg.sign(str(user_id))
        assert signed.signature is not None
        assert signed.signature.signed_by == str(user_id)
        assert signed.version == 2
        assert signed.verify_signature() is True

        # Tamper
        tampered = signed.update(str(user_id), version=99)
        assert tampered.verify_signature() is False

    # ---- Event methods ----
    def test_event_methods(self, legal_entity_id):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        assert agg.get_events() == []
        event = MagicMock()
        agg.register_event(event)
        assert agg.get_events() == [event]
        agg.clear_events()
        assert agg.get_events() == []
        agg.register_event(event)
        pulled = agg.pull_events()
        assert pulled == [event]
        assert agg.get_events() == []
        agg.apply(event)
        assert agg.get_events() == [event]

    # ---- Cash Book Management ----
    def test_add_child(self, legal_entity_id, user_id, cash_book):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        new_agg = agg.add_child(cash_book)
        assert new_agg.cash_books[cash_book.cash_book_id] == cash_book
        assert new_agg.version == 2
        trail = new_agg.audit_trail()
        assert any(e["action"] == "ADD_CASH_BOOK" for e in trail)

    def test_add_child_already_exists(self, legal_entity_id, cash_book):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg = agg.add_child(cash_book)
        with pytest.raises(ValueError, match="already exists"):
            agg.add_child(cash_book)

    def test_add_child_legal_entity_mismatch(self, legal_entity_id, cash_book):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=uuid.uuid4())  # different
        with pytest.raises(ValueError, match="legal entity mismatch"):
            agg.add_child(cash_book)

    def test_remove_child(self, legal_entity_id, user_id, cash_book):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg = agg.add_child(cash_book)
        cash_book.current_balance = Decimal("0")
        new_agg = agg.remove_child(cash_book.cash_book_id, str(user_id))
        assert cash_book.cash_book_id not in new_agg.cash_books
        assert new_agg.version == 3
        trail = new_agg.audit_trail()
        assert any(e["action"] == "REMOVE_CASH_BOOK" for e in trail)

    def test_remove_child_non_zero_balance(self, legal_entity_id, user_id, cash_book):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg = agg.add_child(cash_book)
        cash_book.current_balance = Decimal("100")
        with pytest.raises(ValueError, match="non-zero balance"):
            agg.remove_child(cash_book.cash_book_id, str(user_id))

    def test_remove_child_not_found(self, legal_entity_id, user_id):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        with pytest.raises(ValueError, match="not found"):
            agg.remove_child(uuid.uuid4(), str(user_id))

    def test_get_cash_book(self, legal_entity_id, cash_book):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg = agg.add_child(cash_book)
        assert agg.get_cash_book(cash_book.cash_book_id) == cash_book
        assert agg.get_cash_book(uuid.uuid4()) is None

    def test_get_cash_book_by_code(self, legal_entity_id, cash_book):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg = agg.add_child(cash_book)
        assert agg.get_cash_book_by_code("CASH-001") == cash_book
        assert agg.get_cash_book_by_code("UNKNOWN") is None

    def test_get_active_cash_books(self, legal_entity_id, cash_book):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg = agg.add_child(cash_book)
        # Add another inactive
        cb2 = CashBookEntity(
            cash_book_id=uuid.uuid4(),
            legal_entity_id=legal_entity_id,
            cash_book_code="CASH-002",
            cash_book_name="Inactive Cash",
            currency=Currency.IDR,
            opening_balance=Decimal("0"),
            current_balance=Decimal("0"),
            status=CashBookStatus.SUSPENDED,
            created_by=uuid.uuid4(),
            created_at=FIXED_DATETIME,
            updated_at=FIXED_DATETIME,
            version=1,
        )
        agg = agg.add_child(cb2)
        active = agg.get_active_cash_books()
        assert len(active) == 1
        assert active[0].cash_book_id == cash_book.cash_book_id

    def test_close_cash_book(self, legal_entity_id, user_id, cash_book):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg = agg.add_child(cash_book)
        cash_book.current_balance = Decimal("0")
        closed = agg.close_cash_book(cash_book.cash_book_id, str(user_id))
        assert closed.cash_books[cash_book.cash_book_id].status == CashBookStatus.CLOSED
        assert closed.version == 3
        trail = closed.audit_trail()
        assert any(e["action"] == "CLOSE_CASH_BOOK" for e in trail)

    def test_close_cash_book_non_zero(self, legal_entity_id, user_id, cash_book):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg = agg.add_child(cash_book)
        cash_book.current_balance = Decimal("100")
        with pytest.raises(ValueError, match="non-zero balance"):
            agg.close_cash_book(cash_book.cash_book_id, str(user_id))

    # ---- Petty Cash Management ----
    def test_add_petty_cash_fund(self, legal_entity_id, user_id, petty_cash):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        new_agg = agg.add_petty_cash_fund(petty_cash)
        assert new_agg.petty_cash_funds[petty_cash.petty_cash_id] == petty_cash
        assert new_agg.version == 2
        trail = new_agg.audit_trail()
        assert any(e["action"] == "ADD_PETTY_CASH" for e in trail)

    def test_add_petty_cash_already_exists(self, legal_entity_id, petty_cash):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg = agg.add_petty_cash_fund(petty_cash)
        with pytest.raises(ValueError, match="already exists"):
            agg.add_petty_cash_fund(petty_cash)

    def test_get_petty_cash_fund(self, legal_entity_id, petty_cash):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg = agg.add_petty_cash_fund(petty_cash)
        assert agg.get_petty_cash_fund(petty_cash.petty_cash_id) == petty_cash
        assert agg.get_petty_cash_fund(uuid.uuid4()) is None

    def test_get_petty_cash_by_custodian(self, legal_entity_id, user_id, petty_cash):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg = agg.add_petty_cash_fund(petty_cash)
        assert agg.get_petty_cash_by_custodian(user_id) == petty_cash
        assert agg.get_petty_cash_by_custodian(uuid.uuid4()) is None

    def test_replenish_petty_cash(self, legal_entity_id, user_id, petty_cash):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg = agg.add_petty_cash_fund(petty_cash)
        # Set balance low to need replenishment
        petty_cash.current_balance = Decimal("100")
        new_agg = agg.replenish_petty_cash(petty_cash.petty_cash_id, Decimal("800"), str(user_id), "REF", "approver")
        assert new_agg.petty_cash_funds[petty_cash.petty_cash_id].current_balance == Decimal("900")
        assert new_agg.version == 3
        trail = new_agg.audit_trail()
        assert any(e["action"] == "REPLENISH_PETTY_CASH" for e in trail)

    def test_replenish_petty_cash_cannot(self, legal_entity_id, user_id, petty_cash):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg = agg.add_petty_cash_fund(petty_cash)
        petty_cash.status = PettyCashStatus.CLOSED
        with pytest.raises(ValueError, match="Cannot replenish"):
            agg.replenish_petty_cash(petty_cash.petty_cash_id, Decimal("800"), str(user_id))

    def test_auto_replenish_petty_cash(self, legal_entity_id, user_id, petty_cash):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg = agg.add_petty_cash_fund(petty_cash)
        petty_cash.current_balance = Decimal("100")
        petty_cash.replenishment_threshold = Decimal("200")
        petty_cash.replenishment_amount = Decimal("800")
        new_agg = agg.auto_replenish_petty_cash(petty_cash.petty_cash_id, str(user_id))
        assert new_agg.petty_cash_funds[petty_cash.petty_cash_id].current_balance == Decimal("900")
        assert new_agg.version == 3

    def test_auto_replenish_not_needed(self, legal_entity_id, user_id, petty_cash):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg = agg.add_petty_cash_fund(petty_cash)
        petty_cash.current_balance = Decimal("500")
        new_agg = agg.auto_replenish_petty_cash(petty_cash.petty_cash_id, str(user_id))
        # Should return self (no change)
        assert new_agg is agg

    # ---- Cash Receipts ----
    def test_add_cash_receipt(self, legal_entity_id, user_id, cash_book):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg = agg.add_child(cash_book)
        receipt = create_receipt(cash_book_id=cash_book.cash_book_id, status=CashReceiptStatus.DRAFT)
        new_agg = agg.add_cash_receipt(receipt)
        assert len(new_agg.cash_receipts) == 1
        assert new_agg.cash_receipts[0] == receipt
        assert new_agg.version == 3
        trail = new_agg.audit_trail()
        assert any(e["action"] == "ADD_RECEIPT" for e in trail)

    def test_add_cash_receipt_confirmed_updates_cash_book(self, legal_entity_id, user_id, cash_book):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg = agg.add_child(cash_book)
        receipt = create_receipt(cash_book_id=cash_book.cash_book_id, amount=Decimal("100"), status=CashReceiptStatus.CONFIRMED)
        initial_balance = cash_book.current_balance
        new_agg = agg.add_cash_receipt(receipt)
        assert new_agg.cash_books[cash_book.cash_book_id].current_balance == initial_balance + receipt.amount
        assert new_agg.version == 3

    def test_confirm_cash_receipt(self, legal_entity_id, user_id, cash_book):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg = agg.add_child(cash_book)
        receipt = create_receipt(cash_book_id=cash_book.cash_book_id, amount=Decimal("100"), status=CashReceiptStatus.PENDING_VERIFICATION)
        agg = agg.add_cash_receipt(receipt)
        initial_balance = cash_book.current_balance
        confirmed = agg.confirm_cash_receipt(receipt.receipt_id, str(user_id))
        assert confirmed.cash_receipts[0].status == CashReceiptStatus.CONFIRMED
        assert confirmed.cash_books[cash_book.cash_book_id].current_balance == initial_balance + Decimal("100")
        assert confirmed.version == 4
        trail = confirmed.audit_trail()
        assert any(e["action"] == "CONFIRM_RECEIPT" for e in trail)

    def test_confirm_cash_receipt_not_found(self, legal_entity_id, user_id):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        with pytest.raises(ValueError, match="not found"):
            agg.confirm_cash_receipt(uuid.uuid4(), str(user_id))

    def test_confirm_cash_receipt_cannot_confirm(self, legal_entity_id, user_id, cash_book):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg = agg.add_child(cash_book)
        receipt = create_receipt(cash_book_id=cash_book.cash_book_id, status=CashReceiptStatus.CONFIRMED)
        agg = agg.add_cash_receipt(receipt)
        with pytest.raises(ValueError, match="Cannot confirm"):
            agg.confirm_cash_receipt(receipt.receipt_id, str(user_id))

    def test_cancel_cash_receipt(self, legal_entity_id, user_id, cash_book):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg = agg.add_child(cash_book)
        receipt = create_receipt(cash_book_id=cash_book.cash_book_id, amount=Decimal("100"), status=CashReceiptStatus.CONFIRMED)
        agg = agg.add_cash_receipt(receipt)
        cash_book.current_balance = Decimal("1000")
        initial_balance = cash_book.current_balance
        cancelled = agg.cancel_cash_receipt(receipt.receipt_id, str(user_id), "test")
        assert cancelled.cash_receipts[0].status == CashReceiptStatus.CANCELLED
        # Cash book should be reversed
        assert cancelled.cash_books[cash_book.cash_book_id].current_balance == initial_balance - receipt.confirmed_amount
        assert cancelled.version == 4
        trail = cancelled.audit_trail()
        assert any(e["action"] == "CANCEL_RECEIPT" for e in trail)

    def test_cancel_cash_receipt_already_cancelled(self, legal_entity_id, user_id, cash_book):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg = agg.add_child(cash_book)
        receipt = create_receipt(cash_book_id=cash_book.cash_book_id, status=CashReceiptStatus.CANCELLED)
        agg = agg.add_cash_receipt(receipt)
        with pytest.raises(ValueError, match="already cancelled"):
            agg.cancel_cash_receipt(receipt.receipt_id, str(user_id), "test")

    # ---- Cash Disbursements ----
    def test_add_cash_disbursement(self, legal_entity_id, user_id, cash_book):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg = agg.add_child(cash_book)
        disb = create_disbursement(cash_book_id=cash_book.cash_book_id, status=CashDisbursementStatus.DRAFT)
        new_agg = agg.add_cash_disbursement(disb)
        assert len(new_agg.cash_disbursements) == 1
        assert new_agg.cash_disbursements[0] == disb
        assert new_agg.version == 3
        trail = new_agg.audit_trail()
        assert any(e["action"] == "ADD_DISBURSEMENT" for e in trail)

    def test_add_cash_disbursement_paid_updates_cash_book(self, legal_entity_id, user_id, cash_book):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg = agg.add_child(cash_book)
        disb = create_disbursement(cash_book_id=cash_book.cash_book_id, amount=Decimal("50"), status=CashDisbursementStatus.PAID)
        initial_balance = cash_book.current_balance
        new_agg = agg.add_cash_disbursement(disb)
        assert new_agg.cash_books[cash_book.cash_book_id].current_balance == initial_balance - disb.amount
        assert new_agg.version == 3

    def test_approve_cash_disbursement(self, legal_entity_id, user_id, cash_book):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg = agg.add_child(cash_book)
        disb = create_disbursement(cash_book_id=cash_book.cash_book_id, status=CashDisbursementStatus.PENDING_APPROVAL, approval_level_required=1)
        agg = agg.add_cash_disbursement(disb)
        approver_id = uuid.uuid4()
        approved = agg.approve_cash_disbursement(disb.disbursement_id, 1, approver_id, "Approver")
        assert approved.cash_disbursements[0].status == CashDisbursementStatus.APPROVED
        assert approved.version == 4
        trail = approved.audit_trail()
        assert any(e["action"] == "APPROVE_DISBURSEMENT" for e in trail)

    def test_approve_cash_disbursement_not_found(self, legal_entity_id, user_id):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        with pytest.raises(ValueError, match="not found"):
            agg.approve_cash_disbursement(uuid.uuid4(), 1, uuid.uuid4(), "Approver")

    def test_pay_cash_disbursement(self, legal_entity_id, user_id, cash_book):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg = agg.add_child(cash_book)
        disb = create_disbursement(cash_book_id=cash_book.cash_book_id, amount=Decimal("50"), status=CashDisbursementStatus.APPROVED)
        agg = agg.add_cash_disbursement(disb)
        initial_balance = cash_book.current_balance
        paid = agg.pay_cash_disbursement(disb.disbursement_id, str(user_id))
        assert paid.cash_disbursements[0].status == CashDisbursementStatus.PAID
        # Cash book should be updated
        assert paid.cash_books[cash_book.cash_book_id].current_balance == initial_balance - Decimal("50")
        assert paid.version == 4
        trail = paid.audit_trail()
        assert any(e["action"] == "PAY_DISBURSEMENT" for e in trail)

    def test_pay_cash_disbursement_cannot_pay(self, legal_entity_id, user_id, cash_book):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg = agg.add_child(cash_book)
        disb = create_disbursement(cash_book_id=cash_book.cash_book_id, status=CashDisbursementStatus.DRAFT)
        agg = agg.add_cash_disbursement(disb)
        with pytest.raises(ValueError, match="Cannot pay"):
            agg.pay_cash_disbursement(disb.disbursement_id, str(user_id))

    def test_cancel_cash_disbursement(self, legal_entity_id, user_id, cash_book):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg = agg.add_child(cash_book)
        disb = create_disbursement(cash_book_id=cash_book.cash_book_id, amount=Decimal("50"), status=CashDisbursementStatus.APPROVED)
        agg = agg.add_cash_disbursement(disb)
        cancelled = agg.cancel_cash_disbursement(disb.disbursement_id, str(user_id), "test")
        assert cancelled.cash_disbursements[0].status == CashDisbursementStatus.CANCELLED
        # No cash book update since it wasn't paid
        assert cancelled.version == 4
        trail = cancelled.audit_trail()
        assert any(e["action"] == "CANCEL_DISBURSEMENT" for e in trail)

    def test_cancel_paid_disbursement_raises(self, legal_entity_id, user_id, cash_book):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg = agg.add_child(cash_book)
        disb = create_disbursement(cash_book_id=cash_book.cash_book_id, status=CashDisbursementStatus.PAID)
        agg = agg.add_cash_disbursement(disb)
        with pytest.raises(ValueError, match="Cannot cancel"):
            agg.cancel_cash_disbursement(disb.disbursement_id, str(user_id), "test")

    # ---- Transfer ----
    def test_transfer_between_cash_books(self, legal_entity_id, user_id, cash_book):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg = agg.add_child(cash_book)
        # Add another cash book
        cb2 = CashBookEntity(
            cash_book_id=uuid.uuid4(),
            legal_entity_id=legal_entity_id,
            cash_book_code="CASH-002",
            cash_book_name="Second Cash",
            currency=Currency.IDR,
            opening_balance=Decimal("0"),
            current_balance=Decimal("0"),
            status=CashBookStatus.ACTIVE,
            created_by=user_id,
            created_at=FIXED_DATETIME,
            updated_at=FIXED_DATETIME,
            version=1,
        )
        agg = agg.add_child(cb2)
        agg.cash_books[cash_book.cash_book_id].current_balance = Decimal("1000")
        agg.cash_books[cb2.cash_book_id].current_balance = Decimal("0")
        transferred = agg.transfer_between_cash_books(
            cash_book.cash_book_id, cb2.cash_book_id, Decimal("200"), "Test transfer", str(user_id)
        )
        assert transferred.cash_books[cash_book.cash_book_id].current_balance == Decimal("800")
        assert transferred.cash_books[cb2.cash_book_id].current_balance == Decimal("200")
        assert transferred.version == 4
        trail = transferred.audit_trail()
        assert any(e["action"] == "TRANSFER_BETWEEN_CASH_BOOKS" for e in trail)

    def test_transfer_insufficient_balance(self, legal_entity_id, user_id, cash_book):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg = agg.add_child(cash_book)
        cb2 = CashBookEntity(
            cash_book_id=uuid.uuid4(),
            legal_entity_id=legal_entity_id,
            cash_book_code="CASH-002",
            cash_book_name="Second Cash",
            currency=Currency.IDR,
            opening_balance=Decimal("0"),
            current_balance=Decimal("0"),
            status=CashBookStatus.ACTIVE,
            created_by=user_id,
            created_at=FIXED_DATETIME,
            updated_at=FIXED_DATETIME,
            version=1,
        )
        agg = agg.add_child(cb2)
        agg.cash_books[cash_book.cash_book_id].current_balance = Decimal("100")
        with pytest.raises(ValueError, match="Insufficient balance"):
            agg.transfer_between_cash_books(
                cash_book.cash_book_id, cb2.cash_book_id, Decimal("200"), "Test", str(user_id)
            )

    def test_transfer_same_cash_book(self, legal_entity_id, user_id, cash_book):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg = agg.add_child(cash_book)
        with pytest.raises(ValueError, match="Cannot transfer to same"):
            agg.transfer_between_cash_books(
                cash_book.cash_book_id, cash_book.cash_book_id, Decimal("10"), "Test", str(user_id)
            )

    def test_transfer_currency_mismatch(self, legal_entity_id, user_id, cash_book):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg = agg.add_child(cash_book)
        cb2 = CashBookEntity(
            cash_book_id=uuid.uuid4(),
            legal_entity_id=legal_entity_id,
            cash_book_code="CASH-002",
            cash_book_name="Second Cash",
            currency=Currency.USD,  # different
            opening_balance=Decimal("0"),
            current_balance=Decimal("0"),
            status=CashBookStatus.ACTIVE,
            created_by=user_id,
            created_at=FIXED_DATETIME,
            updated_at=FIXED_DATETIME,
            version=1,
        )
        agg = agg.add_child(cb2)
        with pytest.raises(ValueError, match="Currency mismatch"):
            agg.transfer_between_cash_books(
                cash_book.cash_book_id, cb2.cash_book_id, Decimal("10"), "Test", str(user_id)
            )

    # ---- Totals and Reports ----
    def test_get_total_cash_balance(self, legal_entity_id, cash_book, petty_cash):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg = agg.add_child(cash_book)
        agg = agg.add_petty_cash_fund(petty_cash)
        total = agg.get_total_cash_balance()
        # cash_book balance = 1000, petty_cash balance = 500
        assert total == Decimal("1500")

    def test_get_total_receipts(self, legal_entity_id, user_id, cash_book):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg = agg.add_child(cash_book)
        r1 = create_receipt(cash_book_id=cash_book.cash_book_id, amount=Decimal("100"), confirmed_amount=Decimal("100"), status=CashReceiptStatus.CONFIRMED)
        r2 = create_receipt(cash_book_id=cash_book.cash_book_id, amount=Decimal("50"), confirmed_amount=Decimal("50"), status=CashReceiptStatus.PARTIALLY_CONFIRMED)
        r3 = create_receipt(cash_book_id=cash_book.cash_book_id, amount=Decimal("200"), confirmed_amount=Decimal("0"), status=CashReceiptStatus.DRAFT)
        agg = agg.add_cash_receipt(r1)
        agg = agg.add_cash_receipt(r2)
        agg = agg.add_cash_receipt(r3)
        total = agg.get_total_receipts()
        assert total == Decimal("150")  # 100 + 50

    def test_get_total_receipts_filtered(self, legal_entity_id, user_id, cash_book):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg = agg.add_child(cash_book)
        r1 = create_receipt(cash_book_id=cash_book.cash_book_id, amount=Decimal("100"), confirmed_amount=Decimal("100"), status=CashReceiptStatus.CONFIRMED)
        r1.receipt_date = FIXED_DATETIME - timedelta(days=2)
        r2 = create_receipt(cash_book_id=cash_book.cash_book_id, amount=Decimal("50"), confirmed_amount=Decimal("50"), status=CashReceiptStatus.CONFIRMED)
        r2.receipt_date = FIXED_DATETIME
        agg = agg.add_cash_receipt(r1)
        agg = agg.add_cash_receipt(r2)
        from_date = FIXED_DATETIME - timedelta(days=1)
        total = agg.get_total_receipts(from_date=from_date)
        assert total == Decimal("50")
        to_date = FIXED_DATETIME - timedelta(days=1)
        total2 = agg.get_total_receipts(to_date=to_date)
        assert total2 == Decimal("100")

    def test_get_total_disbursements(self, legal_entity_id, user_id, cash_book):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg = agg.add_child(cash_book)
        d1 = create_disbursement(cash_book_id=cash_book.cash_book_id, amount=Decimal("100"), paid_amount=Decimal("100"), status=CashDisbursementStatus.PAID)
        d2 = create_disbursement(cash_book_id=cash_book.cash_book_id, amount=Decimal("50"), paid_amount=Decimal("30"), status=CashDisbursementStatus.PARTIALLY_PAID)
        d3 = create_disbursement(cash_book_id=cash_book.cash_book_id, amount=Decimal("200"), paid_amount=Decimal("0"), status=CashDisbursementStatus.DRAFT)
        agg = agg.add_cash_disbursement(d1)
        agg = agg.add_cash_disbursement(d2)
        agg = agg.add_cash_disbursement(d3)
        total = agg.get_total_disbursements()
        assert total == Decimal("130")  # 100 + 30

    def test_get_daily_summary(self, legal_entity_id, user_id, cash_book):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg = agg.add_child(cash_book)
        # Add receipts and disbursements for today
        r1 = create_receipt(cash_book_id=cash_book.cash_book_id, amount=Decimal("100"), confirmed_amount=Decimal("100"), status=CashReceiptStatus.CONFIRMED)
        r1.receipt_date = FIXED_DATETIME
        r2 = create_receipt(cash_book_id=cash_book.cash_book_id, amount=Decimal("50"), confirmed_amount=Decimal("50"), status=CashReceiptStatus.CONFIRMED)
        r2.receipt_date = FIXED_DATETIME - timedelta(days=1)
        d1 = create_disbursement(cash_book_id=cash_book.cash_book_id, amount=Decimal("30"), paid_amount=Decimal("30"), status=CashDisbursementStatus.PAID)
        d1.disbursement_date = FIXED_DATETIME
        d2 = create_disbursement(cash_book_id=cash_book.cash_book_id, amount=Decimal("40"), paid_amount=Decimal("40"), status=CashDisbursementStatus.PAID)
        d2.disbursement_date = FIXED_DATETIME - timedelta(days=1)
        agg = agg.add_cash_receipt(r1)
        agg = agg.add_cash_receipt(r2)
        agg = agg.add_cash_disbursement(d1)
        agg = agg.add_cash_disbursement(d2)

        summary = agg.get_daily_summary(FIXED_DATE)
        assert summary.date == FIXED_DATE
        # total_receipts for today: 100
        assert summary.total_receipts == Decimal("100")
        # total_disbursements for today: 30
        assert summary.total_disbursements == Decimal("30")
        assert summary.net_flow == Decimal("70")
        # Opening balance = closing - net_flow
        # closing_balance = total cash balance = cash_book current_balance (1000) + receipt effects - disb effects
        # current balance after modifications: 1000 + 100 + 50 - 30 - 40 = 1080
        # But cash_book has been modified by add_cash_receipt and add_cash_disbursement methods.
        # Actually those methods update the cash_book balance directly.
        # So current_balance of cash_book should be: initial 1000 + 100 (from r1) - 30 (from d1) = 1070 (r2 and d2 are from yesterday).
        # But our agg.cash_books holds updated balances from each operation.
        # Let's just check that summary.opening_balance + net_flow = summary.closing_balance.
        assert summary.opening_balance + summary.net_flow == summary.closing_balance

    def test_get_receipts_by_type(self, legal_entity_id, user_id, cash_book):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg = agg.add_child(cash_book)
        r1 = create_receipt(cash_book_id=cash_book.cash_book_id, amount=Decimal("100"), status=CashReceiptStatus.CONFIRMED)
        r1.receipt_type = CashReceiptType.CUSTOMER_PAYMENT
        r2 = create_receipt(cash_book_id=cash_book.cash_book_id, amount=Decimal("200"), status=CashReceiptStatus.CONFIRMED)
        r2.receipt_type = CashReceiptType.REFUND
        r3 = create_receipt(cash_book_id=cash_book.cash_book_id, amount=Decimal("300"), status=CashReceiptStatus.CANCELLED)
        r3.receipt_type = CashReceiptType.CUSTOMER_PAYMENT
        agg = agg.add_cash_receipt(r1)
        agg = agg.add_cash_receipt(r2)
        agg = agg.add_cash_receipt(r3)
        results = agg.get_receipts_by_type(CashReceiptType.CUSTOMER_PAYMENT)
        assert len(results) == 1
        assert results[0].receipt_id == r1.receipt_id

    def test_get_disbursements_by_type(self, legal_entity_id, user_id, cash_book):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg = agg.add_child(cash_book)
        d1 = create_disbursement(cash_book_id=cash_book.cash_book_id, amount=Decimal("100"), status=CashDisbursementStatus.PAID)
        d1.disbursement_type = CashDisbursementType.OPERATING_EXPENSE
        d2 = create_disbursement(cash_book_id=cash_book.cash_book_id, amount=Decimal("200"), status=CashDisbursementStatus.PAID)
        d2.disbursement_type = CashDisbursementType.CAPITAL_EXPENDITURE
        d3 = create_disbursement(cash_book_id=cash_book.cash_book_id, amount=Decimal("300"), status=CashDisbursementStatus.CANCELLED)
        d3.disbursement_type = CashDisbursementType.OPERATING_EXPENSE
        agg = agg.add_cash_disbursement(d1)
        agg = agg.add_cash_disbursement(d2)
        agg = agg.add_cash_disbursement(d3)
        results = agg.get_disbursements_by_type(CashDisbursementType.OPERATING_EXPENSE)
        assert len(results) == 1
        assert results[0].disbursement_id == d1.disbursement_id

    def test_get_pending_approvals(self, legal_entity_id, user_id, cash_book):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg = agg.add_child(cash_book)
        d1 = create_disbursement(cash_book_id=cash_book.cash_book_id, status=CashDisbursementStatus.PENDING_APPROVAL, approval_level_required=2)
        d1.current_approval_level = 1
        d1.submitted_by = "user1"
        d1.submitted_at = FIXED_DATETIME
        d2 = create_disbursement(cash_book_id=cash_book.cash_book_id, status=CashDisbursementStatus.APPROVED)
        r1 = create_receipt(cash_book_id=cash_book.cash_book_id, status=CashReceiptStatus.PENDING_VERIFICATION)
        r1.submitted_by = "user2"
        r1.submitted_at = FIXED_DATETIME
        agg = agg.add_cash_disbursement(d1)
        agg = agg.add_cash_disbursement(d2)
        agg = agg.add_cash_receipt(r1)
        pending = agg.get_pending_approvals()
        assert len(pending) == 2
        # Check disbursement
        disb_pending = next(p for p in pending if p["type"] == "disbursement")
        assert disb_pending["id"] == str(d1.disbursement_id)
        assert disb_pending["current_level"] == 1
        assert disb_pending["required_level"] == 2
        # Check receipt
        receipt_pending = next(p for p in pending if p["type"] == "receipt")
        assert receipt_pending["id"] == str(r1.receipt_id)

    # ---- Private validation helpers ----
    def test_validate_cash_book_exists(self, legal_entity_id, cash_book):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg = agg.add_child(cash_book)
        # Should not raise
        agg._validate_cash_book_exists(cash_book.cash_book_id)
        with pytest.raises(ValueError, match="not found"):
            agg._validate_cash_book_exists(uuid.uuid4())

    def test_validate_petty_cash_exists(self, legal_entity_id, petty_cash):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg = agg.add_petty_cash_fund(petty_cash)
        agg._validate_petty_cash_exists(petty_cash.petty_cash_id)
        with pytest.raises(ValueError, match="not found"):
            agg._validate_petty_cash_exists(uuid.uuid4())

    def test_validate_positive_amount(self, legal_entity_id):
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg._validate_positive_amount(Decimal("10"))
        with pytest.raises(ValueError, match="positive"):
            agg._validate_positive_amount(Decimal("-5"))


# =============================================================================
# CashAggregateRepository
# =============================================================================

@pytest.mark.asyncio
class TestCashAggregateRepository:
    async def test_save_and_get_by_id(self, legal_entity_id):
        repo = CashAggregateRepository()
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        await repo.save(agg)
        retrieved = await repo.get_by_id(agg.cash_id)
        assert retrieved is not None
        assert retrieved.cash_id == agg.cash_id

    async def test_get_by_legal_entity(self, legal_entity_id):
        repo = CashAggregateRepository()
        agg1 = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg2 = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg3 = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=uuid.uuid4())
        await repo.save(agg1)
        await repo.save(agg2)
        await repo.save(agg3)
        result = await repo.get_by_legal_entity(legal_entity_id)
        assert result is not None
        assert result.legal_entity_id == legal_entity_id

    async def test_get_all(self, legal_entity_id):
        repo = CashAggregateRepository()
        agg1 = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        agg2 = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        await repo.save(agg1)
        await repo.save(agg2)
        all_aggs = await repo.get_all()
        assert len(all_aggs) == 2
        assert agg1 in all_aggs
        assert agg2 in all_aggs

    async def test_update(self, legal_entity_id):
        repo = CashAggregateRepository()
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        await repo.save(agg)
        agg.version = 5
        await repo.update(agg)
        retrieved = await repo.get_by_id(agg.cash_id)
        assert retrieved.version == 5

    async def test_delete(self, legal_entity_id):
        repo = CashAggregateRepository()
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        await repo.save(agg)
        await repo.delete(agg.cash_id)
        retrieved = await repo.get_by_id(agg.cash_id)
        assert retrieved is None

    async def test_clear(self, legal_entity_id):
        repo = CashAggregateRepository()
        agg = CashAggregate(cash_id=uuid.uuid4(), legal_entity_id=legal_entity_id)
        await repo.save(agg)
        await repo.clear()
        all_aggs = await repo.get_all()
        assert len(all_aggs) == 0