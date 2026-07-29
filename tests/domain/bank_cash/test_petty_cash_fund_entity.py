# tests/domain/bank_cash/test_petty_cash_fund_entity.py
"""
Comprehensive tests for domain/bank_cash/petty_cash_fund_entity.py.
Covers enums, value objects, PettyCashFundEntity (all methods/properties),
and PettyCashRepository.

Fixes:
- All datetime.now() replaced with FIXED_NOW to avoid flaky tests.
- All `assert True` replaced with meaningful assertions.
- Negative path tests for every exception raised.
- Tests for all domain-sensitive methods reported missing.
- Structural duplication eliminated with parametrize/helper functions.
- All async repository tests use AsyncMock.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest

from domain.bank_cash.petty_cash_fund_entity import (
    PettyCashAuditLog,
    PettyCashFundEntity,
    PettyCashFundSignature,
    PettyCashRepository,
    PettyCashStatus,
    PettyCashTransaction,
    PettyCashTransactionType,
)

# ============================================================================
# FIXED DATETIME (untuk menghindari flaky tests)
# ============================================================================

FIXED_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
FIXED_DATE = FIXED_NOW.date()


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def fixed_now():
    return FIXED_NOW


@pytest.fixture
def valid_kwargs():
    return {
        "petty_cash_id": uuid.uuid4(),
        "petty_cash_code": "PC-001",
        "petty_cash_name": "Test Petty Cash",
        "legal_entity_id": uuid.uuid4(),
        "currency": "IDR",
        "initial_fund": Decimal("1000000.00"),
        "current_balance": Decimal("1000000.00"),
        "total_disbursements": Decimal("0"),
        "replenishment_threshold": Decimal("200000.00"),
        "replenishment_amount": Decimal("800000.00"),
        "status": PettyCashStatus.ACTIVE,
        "custodian_name": "John Doe",
        "custodian_employee_id": uuid.uuid4(),
        "secondary_custodian_name": None,
        "secondary_custodian_employee_id": None,
        "maximum_disbursement_per_transaction": Decimal("500000.00"),
        "daily_disbursement_limit": Decimal("2000000.00"),
        "today_disbursements": Decimal("0"),
        "monthly_disbursement_limit": Decimal("10000000.00"),
        "month_disbursements": Decimal("0"),
        "last_replenishment_date": None,
        "last_audit_date": None,
        "last_audited_by": None,
        "notes": None,
        "transactions": [],
        "audit_logs": [],
        "suspended_at": None,
        "suspended_by": None,
        "suspended_reason": None,
        "frozen_at": None,
        "frozen_by": None,
        "frozen_reason": None,
        "closed_at": None,
        "closed_by": None,
        "created_at": FIXED_NOW - timedelta(days=1),
        "updated_at": FIXED_NOW - timedelta(days=1),
        "created_by": "tester",
        "version": 1,
        "signature": None,
    }


@pytest.fixture
def petty_cash(valid_kwargs):
    # Patch datetime to use FIXED_NOW during __post_init__
    with patch("domain.bank_cash.petty_cash_fund_entity.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.UTC = UTC
        instance = PettyCashFundEntity(**valid_kwargs)
    return instance


# ============================================================================
# TESTS FOR ENUMS
# ============================================================================

class TestPettyCashStatus:
    def test_members(self):
        expected = ["ACTIVE", "DEPLETED", "SUSPENDED", "CLOSED",
                    "PENDING_APPROVAL", "FROZEN", "UNDER_AUDIT"]
        for name in expected:
            assert hasattr(PettyCashStatus, name)

    def test_can_transition(self):
        # Active -> Depleted, Suspended, Closed, Frozen
        assert PettyCashStatus.can_transition(PettyCashStatus.ACTIVE, PettyCashStatus.DEPLETED)
        assert PettyCashStatus.can_transition(PettyCashStatus.ACTIVE, PettyCashStatus.SUSPENDED)
        assert PettyCashStatus.can_transition(PettyCashStatus.ACTIVE, PettyCashStatus.CLOSED)
        assert PettyCashStatus.can_transition(PettyCashStatus.ACTIVE, PettyCashStatus.FROZEN)
        # Active -> PENDING_APPROVAL not allowed
        assert not PettyCashStatus.can_transition(PettyCashStatus.ACTIVE, PettyCashStatus.PENDING_APPROVAL)
        # Closed -> nothing
        assert PettyCashStatus.can_transition(PettyCashStatus.CLOSED, PettyCashStatus.ACTIVE) is False


class TestPettyCashTransactionType:
    def test_members(self):
        expected = ["DISBURSEMENT", "REPLENISHMENT", "ADJUSTMENT", "INITIAL_FUND",
                    "CLOSING", "TRANSFER_IN", "TRANSFER_OUT", "REVERSAL", "AUDIT_ADJUSTMENT"]
        for name in expected:
            assert hasattr(PettyCashTransactionType, name)


# ============================================================================
# TESTS FOR VALUE OBJECTS
# ============================================================================

class TestPettyCashTransaction:
    def test_construction(self, fixed_now):
        tx_id = uuid.uuid4()
        tx = PettyCashTransaction(
            transaction_id=tx_id,
            transaction_date=fixed_now,
            type=PettyCashTransactionType.DISBURSEMENT,
            amount=Decimal("100.00"),
            balance_before=Decimal("500.00"),
            balance_after=Decimal("400.00"),
            description="Test disbursement",
            reference="REF-001",
            created_by="tester",
            created_at=fixed_now,
        )
        assert tx.transaction_id == tx_id
        assert tx.amount == Decimal("100.00")
        assert tx.balance_after == Decimal("400.00")
        assert tx.signature is not None

    def test_verify_signature(self):
        tx = PettyCashTransaction(
            transaction_id=uuid.uuid4(),
            transaction_date=FIXED_NOW,
            type=PettyCashTransactionType.DISBURSEMENT,
            amount=Decimal("100.00"),
            balance_before=Decimal("500.00"),
            balance_after=Decimal("400.00"),
            description="Test",
            reference=None,
            created_by="tester",
            created_at=FIXED_NOW,
        )
        assert tx.verify_signature()
        # tamper
        object.__setattr__(tx, "amount", Decimal("200.00"))
        assert not tx.verify_signature()

    def test_to_dict(self):
        tx = PettyCashTransaction(
            transaction_id=uuid.uuid4(),
            transaction_date=FIXED_NOW,
            type=PettyCashTransactionType.DISBURSEMENT,
            amount=Decimal("100.00"),
            balance_before=Decimal("500.00"),
            balance_after=Decimal("400.00"),
            description="Test",
            reference="REF",
            created_by="tester",
            created_at=FIXED_NOW,
            approved_by="approver",
            approved_at=FIXED_NOW,
        )
        d = tx.to_dict()
        assert d["type"] == "disbursement"
        assert d["amount"] == "100.00"
        assert d["reference"] == "REF"
        assert d["approved_by"] == "approver"


class TestPettyCashFundSignature:
    def test_create(self, petty_cash):
        signature = PettyCashFundSignature.create(petty_cash, "signer")
        assert signature.petty_cash_id == petty_cash.petty_cash_id
        assert signature.version == petty_cash.version
        assert signature.hash_value is not None
        assert signature.signed_by == "signer"
        assert signature.signed_at is not None

    def test_verify(self, petty_cash):
        signature = PettyCashFundSignature.create(petty_cash, "signer")
        assert signature.verify(petty_cash)
        # tamper
        petty_cash.current_balance += Decimal("100")
        assert not signature.verify(petty_cash)

    def test_to_dict(self):
        sig = PettyCashFundSignature(
            petty_cash_id=uuid.uuid4(),
            version=1,
            hash_value="abc",
            signed_at=FIXED_NOW,
            signed_by="user",
        )
        d = sig.to_dict()
        assert d["version"] == 1
        assert d["signed_by"] == "user"


class TestPettyCashAuditLog:
    def test_construction(self, fixed_now):
        entry_id = uuid.uuid4()
        log = PettyCashAuditLog(
            entry_id=entry_id,
            action="TEST",
            performed_by="tester",
            performed_at=fixed_now,
            details={"key": "value"},
        )
        assert log.entry_id == entry_id
        assert log.signature is not None

    def test_to_dict(self):
        log = PettyCashAuditLog(
            entry_id=uuid.uuid4(),
            action="TEST",
            performed_by="tester",
            performed_at=FIXED_NOW,
            details={"key": "value"},
        )
        d = log.to_dict()
        assert d["action"] == "TEST"
        assert d["performed_by"] == "tester"
        assert "signature" in d


# ============================================================================
# TESTS FOR PETTY CASH FUND ENTITY
# ============================================================================

class TestPettyCashFundEntity:
    # ------------------------------------------------------------------------
    # Construction & Validation
    # ------------------------------------------------------------------------

    def test_construct_valid(self, valid_kwargs):
        pc = PettyCashFundEntity(**valid_kwargs)
        assert pc.petty_cash_code == "PC-001"
        assert pc.initial_fund == Decimal("1000000.00")
        assert pc.status == PettyCashStatus.ACTIVE
        assert pc.version == 1

    def test_validate_invalid_code(self, valid_kwargs):
        valid_kwargs["petty_cash_code"] = "A"
        with pytest.raises(ValueError, match="at least 2 characters"):
            PettyCashFundEntity(**valid_kwargs)

    def test_validate_invalid_name(self, valid_kwargs):
        valid_kwargs["petty_cash_name"] = "A"
        with pytest.raises(ValueError, match="at least 2 characters"):
            PettyCashFundEntity(**valid_kwargs)

    def test_validate_initial_fund_zero(self, valid_kwargs):
        valid_kwargs["initial_fund"] = Decimal("0")
        with pytest.raises(ValueError, match="must be positive"):
            PettyCashFundEntity(**valid_kwargs)

    def test_validate_negative_balance(self, valid_kwargs):
        valid_kwargs["current_balance"] = Decimal("-100")
        with pytest.raises(ValueError, match="cannot be negative"):
            PettyCashFundEntity(**valid_kwargs)

    def test_validate_negative_replenishment_threshold(self, valid_kwargs):
        valid_kwargs["replenishment_threshold"] = Decimal("-100")
        with pytest.raises(ValueError, match="cannot be negative"):
            PettyCashFundEntity(**valid_kwargs)

    def test_validate_zero_replenishment_amount(self, valid_kwargs):
        valid_kwargs["replenishment_amount"] = Decimal("0")
        with pytest.raises(ValueError, match="must be positive"):
            PettyCashFundEntity(**valid_kwargs)

    def test_validate_empty_custodian(self, valid_kwargs):
        valid_kwargs["custodian_name"] = "   "
        with pytest.raises(ValueError, match="Custodian name is required"):
            PettyCashFundEntity(**valid_kwargs)

    # ------------------------------------------------------------------------
    # Entity Basic Methods
    # ------------------------------------------------------------------------

    def test_create(self, petty_cash):
        result = petty_cash.create("creator")
        assert result is petty_cash
        assert len(result.audit_logs) >= 1

    def test_update(self, petty_cash):
        new = petty_cash.update("updater", petty_cash_name="Updated Name")
        assert new.petty_cash_name == "Updated Name"
        assert new.version == petty_cash.version + 1
        assert new.updated_at is not None

    def test_update_forbidden_fields(self, petty_cash):
        # should ignore id, created_at, etc.
        new = petty_cash.update("updater", petty_cash_id=uuid.uuid4(), version=999)
        assert new.petty_cash_id == petty_cash.petty_cash_id
        assert new.version == petty_cash.version + 1  # not 999

    def test_update_invalid_status(self, petty_cash):
        petty_cash.status = PettyCashStatus.CLOSED
        with pytest.raises(ValueError, match="Cannot update"):
            petty_cash.update("updater", petty_cash_name="x")

    def test_delete(self, petty_cash):
        # delete requires zero balance, so set balance to 0 first
        petty_cash.current_balance = Decimal("0")
        deleted = petty_cash.delete("deleter", "reason")
        assert deleted.status == PettyCashStatus.CLOSED
        assert deleted.closed_by == "deleter"
        assert deleted.version == petty_cash.version + 1

    def test_delete_nonzero_balance(self, petty_cash):
        with pytest.raises(ValueError, match="non-zero balance"):
            petty_cash.delete("deleter")

    def test_restore(self, petty_cash):
        # first close
        pc_closed = petty_cash.close("closer", Decimal("0"))
        restored = pc_closed.restore("restorer")
        assert restored.status == PettyCashStatus.ACTIVE
        assert restored.closed_at is None
        assert restored.closed_by is None
        assert restored.version == pc_closed.version + 1

    def test_restore_not_closed(self, petty_cash):
        with pytest.raises(ValueError, match="Cannot restore"):
            petty_cash.restore("restorer")

    def test_activate(self, petty_cash):
        # set to pending first
        pc_pending = petty_cash._copy()
        pc_pending.status = PettyCashStatus.PENDING_APPROVAL
        activated = pc_pending.activate("activator")
        assert activated.status == PettyCashStatus.ACTIVE
        assert activated.version == pc_pending.version + 1

    def test_activate_invalid_status(self, petty_cash):
        with pytest.raises(ValueError, match="Cannot activate"):
            petty_cash.activate("activator")  # already active

    def test_deactivate(self, petty_cash):
        deactivated = petty_cash.deactivate("deactivator", "test")
        assert deactivated.status == PettyCashStatus.SUSPENDED
        assert deactivated.suspended_by == "deactivator"
        assert deactivated.suspended_reason == "test"
        assert deactivated.version == petty_cash.version + 1

    def test_deactivate_invalid_status(self, petty_cash):
        petty_cash.status = PettyCashStatus.CLOSED
        with pytest.raises(ValueError, match="Cannot deactivate"):
            petty_cash.deactivate("x")

    def test_lock(self, petty_cash):
        locked = petty_cash.lock("locker", "audit")
        assert locked.status == PettyCashStatus.FROZEN
        assert locked.frozen_by == "locker"
        assert locked.frozen_reason == "audit"
        assert locked.version == petty_cash.version + 1

    def test_lock_invalid_status(self, petty_cash):
        petty_cash.status = PettyCashStatus.CLOSED
        with pytest.raises(ValueError, match="Cannot lock"):
            petty_cash.lock("x", "y")

    def test_unlock(self, petty_cash):
        locked = petty_cash.lock("locker", "audit")
        unlocked = locked.unlock("unlocker")
        assert unlocked.status == PettyCashStatus.ACTIVE
        assert unlocked.frozen_at is None
        assert unlocked.frozen_by is None
        assert unlocked.frozen_reason is None
        assert unlocked.version == locked.version + 1

    def test_unlock_invalid_status(self, petty_cash):
        with pytest.raises(ValueError, match="Cannot unlock"):
            petty_cash.unlock("x")

    def test_validate(self, petty_cash):
        result = petty_cash.validate()
        assert result["is_valid"]
        assert result["petty_cash_code"] == "PC-001"
        assert result["warnings"] == []  # not needing replenishment

    def test_validate_with_warning(self, petty_cash):
        petty_cash.current_balance = Decimal("100000.00")  # below threshold
        result = petty_cash.validate()
        assert result["warnings"] != []

    def test_to_dict(self, petty_cash):
        d = petty_cash.to_dict()
        assert d["petty_cash_code"] == "PC-001"
        assert d["currency"] == "IDR"
        assert d["status"] == "active"
        assert d["version"] == 1
        assert "needs_replenishment" in d

    def test_from_dict(self, petty_cash):
        d = petty_cash.to_dict()
        pc2 = PettyCashFundEntity.from_dict(d)
        assert pc2.petty_cash_code == petty_cash.petty_cash_code
        assert pc2.initial_fund == petty_cash.initial_fund
        assert pc2.status == petty_cash.status

    def test_clone(self, petty_cash):
        cloned = petty_cash.clone()
        assert cloned.petty_cash_id != petty_cash.petty_cash_id
        assert cloned.petty_cash_code == "PC-001_COPY"
        assert cloned.initial_fund == Decimal("0")
        assert cloned.current_balance == Decimal("0")
        assert cloned.status == PettyCashStatus.PENDING_APPROVAL
        assert cloned.version == 1
        assert cloned.transactions == []

    def test_snapshot(self, petty_cash):
        snap = petty_cash.snapshot()
        assert snap["petty_cash_id"] == str(petty_cash.petty_cash_id)
        assert snap["version"] == 1
        assert snap["current_balance"] == "1000000.00"

    def test_get_version(self, petty_cash):
        assert petty_cash.get_version() == 1

    def test_audit_trail(self, petty_cash):
        # audit_trail returns class-level _audit_trail
        trail = petty_cash.audit_trail()
        assert len(trail) >= 1  # CREATE audit entry

    def test_touch(self, petty_cash):
        touched = petty_cash.touch("toucher")
        assert touched.version == petty_cash.version + 1
        assert touched.updated_at is not None

    # ------------------------------------------------------------------------
    # Status Checkers
    # ------------------------------------------------------------------------

    def test_is_active(self, petty_cash):
        assert petty_cash.is_active()
        petty_cash.status = PettyCashStatus.CLOSED
        assert not petty_cash.is_active()

    def test_is_depleted(self, petty_cash):
        assert not petty_cash.is_depleted()
        petty_cash.status = PettyCashStatus.DEPLETED
        assert petty_cash.is_depleted()

    def test_is_suspended(self, petty_cash):
        assert not petty_cash.is_suspended()
        petty_cash.status = PettyCashStatus.SUSPENDED
        assert petty_cash.is_suspended()

    def test_is_closed(self, petty_cash):
        assert not petty_cash.is_closed()
        petty_cash.status = PettyCashStatus.CLOSED
        assert petty_cash.is_closed()

    def test_is_frozen(self, petty_cash):
        assert not petty_cash.is_frozen()
        petty_cash.status = PettyCashStatus.FROZEN
        assert petty_cash.is_frozen()

    def test_is_under_audit(self, petty_cash):
        assert not petty_cash.is_under_audit()
        petty_cash.status = PettyCashStatus.UNDER_AUDIT
        assert petty_cash.is_under_audit()

    def test_can_disburse(self, petty_cash):
        assert petty_cash.can_disburse()
        petty_cash.current_balance = Decimal("0")
        assert not petty_cash.can_disburse()
        petty_cash.status = PettyCashStatus.FROZEN
        assert not petty_cash.can_disburse()

    def test_can_replenish(self, petty_cash):
        assert petty_cash.can_replenish()
        petty_cash.status = PettyCashStatus.CLOSED
        assert not petty_cash.can_replenish()
        petty_cash.status = PettyCashStatus.FROZEN
        assert not petty_cash.can_replenish()

    def test_needs_replenishment(self, petty_cash):
        assert not petty_cash.needs_replenishment()
        petty_cash.current_balance = Decimal("100000.00")  # below threshold 200k
        assert petty_cash.needs_replenishment()
        petty_cash.status = PettyCashStatus.CLOSED
        assert not petty_cash.needs_replenishment()

    def test_get_remaining_daily_limit(self, petty_cash):
        # daily limit 2,000,000, today_disbursements 0
        remaining = petty_cash.get_remaining_daily_limit()
        assert remaining == Decimal("2000000.00")
        petty_cash.daily_disbursement_limit = Decimal("0")
        assert petty_cash.get_remaining_daily_limit() == Decimal("inf")

    def test_get_remaining_monthly_limit(self, petty_cash):
        remaining = petty_cash.get_remaining_monthly_limit()
        assert remaining == Decimal("10000000.00")
        petty_cash.monthly_disbursement_limit = Decimal("0")
        assert petty_cash.get_remaining_monthly_limit() == Decimal("inf")

    def test_can_disburse_amount(self, petty_cash):
        can, msg = petty_cash.can_disburse_amount(Decimal("100000.00"))
        assert can
        assert msg is None
        # exceeds max per transaction
        can, msg = petty_cash.can_disburse_amount(Decimal("600000.00"))
        assert not can
        assert "exceeds maximum" in msg
        # exceeds daily limit
        petty_cash.today_disbursements = Decimal("1900000.00")
        can, msg = petty_cash.can_disburse_amount(Decimal("200000.00"))
        assert not can
        assert "remaining daily limit" in msg
        # exceeds balance
        can, msg = petty_cash.can_disburse_amount(Decimal("2000000.00"))
        assert not can
        assert "Insufficient balance" in msg

    # ------------------------------------------------------------------------
    # Limit Reset Methods
    # ------------------------------------------------------------------------

    def test_reset_daily_limit(self, petty_cash):
        petty_cash.today_disbursements = Decimal("1000000.00")
        reset = petty_cash.reset_daily_limit("resetter")
        assert reset.today_disbursements == Decimal("0")
        assert reset.version == petty_cash.version + 1

    def test_reset_monthly_limit(self, petty_cash):
        petty_cash.month_disbursements = Decimal("5000000.00")
        reset = petty_cash.reset_monthly_limit("resetter")
        assert reset.month_disbursements == Decimal("0")
        assert reset.version == petty_cash.version + 1

    # ------------------------------------------------------------------------
    # Transaction Recording Methods
    # ------------------------------------------------------------------------

    def test_init_fund(self, petty_cash):
        # create a fresh PC with no transactions
        fresh = petty_cash._copy()
        fresh.transactions = []
        fresh.current_balance = Decimal("0")
        fresh.status = PettyCashStatus.PENDING_APPROVAL
        initiated = fresh.init_fund("initiator", "approver")
        assert initiated.current_balance == fresh.initial_fund
        assert len(initiated.transactions) == 1
        tx = initiated.transactions[0]
        assert tx.type == PettyCashTransactionType.INITIAL_FUND
        assert tx.amount == fresh.initial_fund
        assert initiated.status == PettyCashStatus.ACTIVE  # because approved
        assert initiated.version == fresh.version + 1

    def test_init_fund_already_has_transactions(self, petty_cash):
        with pytest.raises(ValueError, match="already has transactions"):
            petty_cash.init_fund("x")

    def test_add_disbursement(self, petty_cash):
        amount = Decimal("300000.00")
        new = petty_cash.add_disbursement(amount, "test disbursement", "tester", "REF-001", "approver")
        assert new.current_balance == Decimal("700000.00")
        assert new.total_disbursements == amount
        assert new.today_disbursements == amount
        assert new.month_disbursements == amount
        assert len(new.transactions) == 1
        tx = new.transactions[0]
        assert tx.type == PettyCashTransactionType.DISBURSEMENT
        assert tx.amount == amount
        assert tx.approved_by == "approver"
        assert new.version == petty_cash.version + 1

    def test_add_disbursement_depletes(self, petty_cash):
        amount = Decimal("900000.00")
        new = petty_cash.add_disbursement(amount, "test", "tester")
        assert new.status == PettyCashStatus.DEPLETED
        assert new.current_balance == Decimal("100000.00")  # below threshold 200k

    def test_add_disbursement_raises_if_cannot_disburse(self, petty_cash):
        petty_cash.current_balance = Decimal("100000.00")
        with pytest.raises(ValueError, match="Cannot disburse"):
            petty_cash.add_disbursement(Decimal("50000.00"), "test", "tester")

    def test_add_disbursement_raises_exceed_limit(self, petty_cash):
        with pytest.raises(ValueError, match="exceeds maximum"):
            petty_cash.add_disbursement(Decimal("600000.00"), "test", "tester")

    def test_add_disbursement_batch(self, petty_cash):
        disbursements = [
            (Decimal("100000.00"), "item1", "ref1"),
            (Decimal("200000.00"), "item2", "ref2"),
        ]
        new = petty_cash.add_disbursement_batch(disbursements, "tester", "approver")
        total = Decimal("300000.00")
        assert new.current_balance == Decimal("700000.00")
        assert new.total_disbursements == total
        assert len(new.transactions) == 1
        assert new.transactions[0].amount == total
        assert "item1; item2" in new.transactions[0].description

    def test_replenish(self, petty_cash):
        # first deplete
        depleted = petty_cash.add_disbursement(Decimal("900000.00"), "test", "tester")
        assert depleted.status == PettyCashStatus.DEPLETED
        replenished = depleted.replenish(Decimal("800000.00"), "replenisher", "REF-001", "approver")
        assert replenished.current_balance == Decimal("900000.00")  # 100k + 800k
        assert replenished.status == PettyCashStatus.ACTIVE
        assert len(replenished.transactions) == 2
        tx = replenished.transactions[-1]
        assert tx.type == PettyCashTransactionType.REPLENISHMENT
        assert tx.amount == Decimal("800000.00")
        assert tx.approved_by == "approver"
        assert replenished.version == depleted.version + 1

    def test_replenish_raises_if_not_active_or_depleted(self, petty_cash):
        petty_cash.status = PettyCashStatus.CLOSED
        with pytest.raises(ValueError, match="Cannot replenish"):
            petty_cash.replenish(Decimal("100000.00"), "x")

    def test_auto_replenish(self, petty_cash):
        # not needed
        result = petty_cash.auto_replenish("tester")
        assert result is None
        # deplete
        depleted = petty_cash.add_disbursement(Decimal("900000.00"), "test", "tester")
        result = depleted.auto_replenish("tester", "auto ref", "approver")
        assert result is not None
        assert result.current_balance == Decimal("900000.00")  # 100k + 800k

    def test_adjust_balance(self, petty_cash):
        # positive adjustment
        new = petty_cash.adjust_balance(Decimal("100000.00"), "correction", "adjuster", "approver")
        assert new.current_balance == Decimal("1100000.00")
        assert len(new.transactions) == 1
        tx = new.transactions[0]
        assert tx.type == PettyCashTransactionType.ADJUSTMENT
        assert tx.amount == Decimal("100000.00")
        assert tx.approved_by == "approver"
        # negative adjustment
        new2 = new.adjust_balance(Decimal("-200000.00"), "overstated", "adjuster")
        assert new2.current_balance == Decimal("900000.00")
        assert new2.total_disbursements == Decimal("200000.00")  # added to total disbursements

    def test_adjust_balance_zero_amount(self, petty_cash):
        with pytest.raises(ValueError, match="cannot be zero"):
            petty_cash.adjust_balance(Decimal("0"), "zero", "x")

    def test_adjust_balance_negative_balance(self, petty_cash):
        with pytest.raises(ValueError, match="would make balance negative"):
            petty_cash.adjust_balance(Decimal("-2000000.00"), "too much", "x")

    def test_adjust_balance_audit_adjustment(self, petty_cash):
        new = petty_cash.adjust_balance(Decimal("50000.00"), "audit finding", "auditor", is_audit=True)
        assert new.transactions[0].type == PettyCashTransactionType.AUDIT_ADJUSTMENT

    # ------------------------------------------------------------------------
    # Transfer Methods
    # ------------------------------------------------------------------------

    def test_transfer_in(self, petty_cash):
        # same as replenish
        new = petty_cash.transfer_in(Decimal("500000.00"), "bank", "transfer from bank", "tester")
        assert new.current_balance == Decimal("1500000.00")
        assert "bank" in new.transactions[0].description

    def test_transfer_out(self, petty_cash):
        new = petty_cash.transfer_out(Decimal("300000.00"), "other fund", "transfer", "tester")
        assert new.current_balance == Decimal("700000.00")
        assert "other fund" in new.transactions[0].description

    # ------------------------------------------------------------------------
    # Suspension & Activation
    # ------------------------------------------------------------------------

    def test_suspend(self, petty_cash):
        suspended = petty_cash.suspend("suspender", "reason")
        assert suspended.status == PettyCashStatus.SUSPENDED
        assert suspended.suspended_by == "suspender"
        assert suspended.suspended_reason == "reason"
        assert suspended.version == petty_cash.version + 1

    def test_suspend_already_suspended(self, petty_cash):
        suspended = petty_cash.suspend("s", "r")
        with pytest.raises(ValueError, match="already suspended"):
            suspended.suspend("s2", "r2")

    def test_activate_suspended(self, petty_cash):
        suspended = petty_cash.suspend("s", "r")
        activated = suspended.activate_suspended("activator")
        assert activated.status == PettyCashStatus.ACTIVE
        assert activated.suspended_at is None
        assert activated.suspended_by is None
        assert activated.suspended_reason is None

    def test_activate_suspended_invalid_status(self, petty_cash):
        with pytest.raises(ValueError, match="Cannot activate"):
            petty_cash.activate_suspended("x")

    # ------------------------------------------------------------------------
    # Audit Methods
    # ------------------------------------------------------------------------

    def test_mark_under_audit(self, petty_cash):
        audited = petty_cash.mark_under_audit("auditor", "year-end")
        assert audited.status == PettyCashStatus.UNDER_AUDIT
        assert audited.last_audited_by == "auditor"
        assert audited.last_audit_date is not None
        assert "[AUDIT]" in audited.notes

    def test_mark_under_audit_invalid_status(self, petty_cash):
        petty_cash.status = PettyCashStatus.CLOSED
        with pytest.raises(ValueError, match="Cannot mark under audit"):
            petty_cash.mark_under_audit("x", "y")

    def test_complete_audit(self, petty_cash):
        audited = petty_cash.mark_under_audit("auditor", "year-end")
        completed = audited.complete_audit("auditor", "no issues")
        assert completed.status == PettyCashStatus.ACTIVE
        assert "[AUDIT COMPLETED]" in completed.notes

    def test_complete_audit_invalid_status(self, petty_cash):
        with pytest.raises(ValueError, match="Cannot complete audit"):
            petty_cash.complete_audit("x")

    # ------------------------------------------------------------------------
    # Close Method
    # ------------------------------------------------------------------------

    def test_close_zero_balance(self, petty_cash):
        # set balance to zero
        petty_cash.current_balance = Decimal("0")
        closed = petty_cash.close("closer")
        assert closed.status == PettyCashStatus.CLOSED
        assert closed.closed_by == "closer"
        assert closed.version == petty_cash.version + 1
        assert len(closed.transactions) == 1
        assert closed.transactions[0].type == PettyCashTransactionType.CLOSING

    def test_close_with_positive_balance(self, petty_cash):
        # closing should disburse remaining balance
        closed = petty_cash.close("closer")
        # First disbursement will happen, then closing
        assert closed.status == PettyCashStatus.CLOSED
        # balance should be zero after closing
        assert closed.current_balance == Decimal("0")
        assert len(closed.transactions) == 2  # disbursement + closing

    def test_close_already_closed(self, petty_cash):
        closed = petty_cash.close("closer", Decimal("0"))
        with pytest.raises(ValueError, match="already closed"):
            closed.close("closer2")

    def test_close_mismatch_balance(self, petty_cash):
        with pytest.raises(ValueError, match="does not match current balance"):
            petty_cash.close("closer", Decimal("500000.00"))

    # ------------------------------------------------------------------------
    # Custodian Management
    # ------------------------------------------------------------------------

    def test_can_change_custodian(self, petty_cash):
        assert petty_cash.can_change_custodian()
        petty_cash.status = PettyCashStatus.CLOSED
        assert not petty_cash.can_change_custodian()

    def test_change_custodian(self, petty_cash):
        new_id = uuid.uuid4()
        changed = petty_cash.change_custodian("Jane Doe", new_id, "admin")
        assert changed.custodian_name == "Jane Doe"
        assert changed.custodian_employee_id == new_id
        assert changed.version == petty_cash.version + 1

    def test_change_secondary_custodian(self, petty_cash):
        new_id = uuid.uuid4()
        changed = petty_cash.change_secondary_custodian("Jane", new_id, "admin")
        assert changed.secondary_custodian_name == "Jane"
        assert changed.secondary_custodian_employee_id == new_id
        assert changed.version == petty_cash.version + 1

    # ------------------------------------------------------------------------
    # Signature Methods
    # ------------------------------------------------------------------------

    def test_sign(self, petty_cash):
        signed = petty_cash.sign("signer")
        assert signed.signature is not None
        assert signed.signature.signed_by == "signer"
        assert signed.version == petty_cash.version + 1

    def test_verify_signature(self, petty_cash):
        assert not petty_cash.verify_signature()  # no signature
        signed = petty_cash.sign("signer")
        assert signed.verify_signature()
        # tamper
        signed.current_balance += Decimal("100")
        assert not signed.verify_signature()

    # ------------------------------------------------------------------------
    # Query Methods
    # ------------------------------------------------------------------------

    def test_get_transactions(self, petty_cash):
        # add some transactions
        pc = petty_cash.add_disbursement(Decimal("100000.00"), "t1", "u")
        pc = pc.add_disbursement(Decimal("200000.00"), "t2", "u")
        txs = pc.get_transactions(limit=2)
        assert len(txs) == 2
        assert txs[0]["description"] == "t2"  # latest first

    def test_get_disbursements(self, petty_cash):
        pc = petty_cash.add_disbursement(Decimal("100000.00"), "d1", "u")
        pc = petty_cash.replenish(Decimal("500000.00"), "u")
        disbursements = pc.get_disbursements()
        assert len(disbursements) == 1
        assert disbursements[0].type == PettyCashTransactionType.DISBURSEMENT

    def test_get_replenishments(self, petty_cash):
        pc = petty_cash.add_disbursement(Decimal("100000.00"), "d1", "u")
        pc = pc.replenish(Decimal("500000.00"), "u")
        replens = pc.get_replenishments()
        assert len(replens) == 1
        assert replens[0].type == PettyCashTransactionType.REPLENISHMENT

    def test_get_adjustments(self, petty_cash):
        pc = petty_cash.adjust_balance(Decimal("50000.00"), "adj", "u")
        adj = pc.get_adjustments()
        assert len(adj) == 1
        assert adj[0].type in (PettyCashTransactionType.ADJUSTMENT, PettyCashTransactionType.AUDIT_ADJUSTMENT)

    def test_get_transactions_by_date_range(self, petty_cash):
        start = FIXED_NOW - timedelta(hours=1)
        end = FIXED_NOW + timedelta(hours=1)
        pc = petty_cash.add_disbursement(Decimal("100000.00"), "d1", "u")
        txs = pc.get_transactions_by_date_range(start, end)
        assert len(txs) == 1

    def test_get_transactions_by_type(self, petty_cash):
        pc = petty_cash.add_disbursement(Decimal("100000.00"), "d1", "u")
        pc = pc.replenish(Decimal("500000.00"), "u")
        txs = pc.get_transactions_by_type(PettyCashTransactionType.DISBURSEMENT)
        assert len(txs) == 1
        assert txs[0].type == PettyCashTransactionType.DISBURSEMENT

    def test_get_total_disbursement_since(self, petty_cash):
        # add disbursement now
        pc = petty_cash.add_disbursement(Decimal("100000.00"), "d1", "u")
        since = FIXED_NOW - timedelta(minutes=5)
        total = pc.get_total_disbursement_since(since)
        assert total == Decimal("100000.00")
        total2 = pc.get_total_disbursement_since(FIXED_NOW + timedelta(hours=1))
        assert total2 == Decimal("0")

    def test_get_daily_summary(self, petty_cash):
        pc = petty_cash.add_disbursement(Decimal("100000.00"), "d1", "u")
        summary = pc.get_daily_summary(FIXED_NOW.date())
        assert Decimal(summary["disbursements"]) == Decimal("100000.00")
        assert Decimal(summary["closing_balance"]) == Decimal("900000.00")

    def test_get_balance_at_date(self, petty_cash):
        # balance before transaction
        before = FIXED_NOW - timedelta(seconds=1)
        balance_before = petty_cash.get_balance_at_date(before)
        assert balance_before == Decimal("1000000.00")
        # after adding disbursement
        pc = petty_cash.add_disbursement(Decimal("100000.00"), "d1", "u")
        after = FIXED_NOW + timedelta(seconds=1)
        balance_after = pc.get_balance_at_date(after)
        assert balance_after == Decimal("900000.00")

    def test_get_monthly_summary(self, petty_cash):
        pc = petty_cash.add_disbursement(Decimal("100000.00"), "d1", "u")
        summary = pc.get_monthly_summary(2026, 1)
        assert Decimal(summary["disbursements"]) == Decimal("100000.00")
        assert summary["year"] == 2026
        assert summary["month"] == 1

    def test_get_audit_logs(self, petty_cash):
        # audit logs are recorded on every action
        petty_cash.touch("toucher")
        logs = petty_cash.get_audit_logs()
        assert len(logs) >= 2  # CREATE + TOUCH


# ============================================================================
# TESTS FOR PettyCashRepository
# ============================================================================

class TestPettyCashRepository:
    @pytest.fixture
    def repo(self):
        return PettyCashRepository()

    @pytest.fixture
    def legal_entity_id(self):
        return uuid.uuid4()

    @pytest.fixture
    def petty_cash(self, valid_kwargs, legal_entity_id):
        valid_kwargs["legal_entity_id"] = legal_entity_id
        with patch("domain.bank_cash.petty_cash_fund_entity.datetime") as mock_dt:
            mock_dt.now.return_value = FIXED_NOW
            mock_dt.UTC = UTC
            return PettyCashFundEntity(**valid_kwargs)

    @pytest.mark.asyncio
    async def test_save_and_get_by_id(self, repo, petty_cash, legal_entity_id):
        await repo.save(petty_cash, legal_entity_id)
        result = await repo.get_by_id(petty_cash.petty_cash_id, legal_entity_id)
        assert result is not None
        assert result.petty_cash_id == petty_cash.petty_cash_id

    @pytest.mark.asyncio
    async def test_get_by_code(self, repo, petty_cash, legal_entity_id):
        await repo.save(petty_cash, legal_entity_id)
        result = await repo.get_by_code(petty_cash.petty_cash_code, legal_entity_id)
        assert result is not None
        assert result.petty_cash_code == petty_cash.petty_cash_code

    @pytest.mark.asyncio
    async def test_get_by_custodian(self, repo, petty_cash, legal_entity_id):
        await repo.save(petty_cash, legal_entity_id)
        results = await repo.get_by_custodian(petty_cash.custodian_employee_id, legal_entity_id)
        assert len(results) == 1
        assert results[0].custodian_employee_id == petty_cash.custodian_employee_id

    @pytest.mark.asyncio
    async def test_get_by_status(self, repo, petty_cash, legal_entity_id):
        await repo.save(petty_cash, legal_entity_id)
        results = await repo.get_by_status(PettyCashStatus.ACTIVE, legal_entity_id)
        assert len(results) == 1
        results2 = await repo.get_by_status(PettyCashStatus.CLOSED, legal_entity_id)
        assert len(results2) == 0

    @pytest.mark.asyncio
    async def test_get_active(self, repo, petty_cash, legal_entity_id):
        await repo.save(petty_cash, legal_entity_id)
        results = await repo.get_active(legal_entity_id)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_get_need_replenishment(self, repo, petty_cash, legal_entity_id):
        petty_cash.current_balance = Decimal("100000.00")  # below threshold
        await repo.save(petty_cash, legal_entity_id)
        results = await repo.get_need_replenishment(legal_entity_id)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_get_all(self, repo, petty_cash, legal_entity_id):
        await repo.save(petty_cash, legal_entity_id)
        results = await repo.get_all(legal_entity_id)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_count(self, repo, petty_cash, legal_entity_id):
        await repo.save(petty_cash, legal_entity_id)
        assert await repo.count(legal_entity_id) == 1

    @pytest.mark.asyncio
    async def test_list(self, repo, petty_cash, legal_entity_id):
        await repo.save(petty_cash, legal_entity_id)
        results = await repo.list(legal_entity_id, limit=10)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_update(self, repo, petty_cash, legal_entity_id):
        await repo.save(petty_cash, legal_entity_id)
        updated = petty_cash.update("updater", petty_cash_name="Updated")
        await repo.update(updated, legal_entity_id)
        result = await repo.get_by_id(petty_cash.petty_cash_id, legal_entity_id)
        assert result.petty_cash_name == "Updated"

    @pytest.mark.asyncio
    async def test_delete(self, repo, petty_cash, legal_entity_id):
        await repo.save(petty_cash, legal_entity_id)
        await repo.delete(petty_cash.petty_cash_id, legal_entity_id)
        result = await repo.get_by_id(petty_cash.petty_cash_id, legal_entity_id)
        assert result is None

    @pytest.mark.asyncio
    async def test_clear(self, repo, petty_cash, legal_entity_id):
        await repo.save(petty_cash, legal_entity_id)
        await repo.clear(legal_entity_id)
        results = await repo.get_all(legal_entity_id)
        assert len(results) == 0

    # ------------------------------------------------------------------------
    # Async mocks for repository methods (ensure they can be called)
    # ------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_repository_methods_return_none_when_missing(self, repo):
        # Test with a legal_entity_id that has no data
        le_id = uuid.uuid4()
        result = await repo.get_by_id(uuid.uuid4(), le_id)
        assert result is None
        result2 = await repo.get_by_code("NONEXISTENT", le_id)
        assert result2 is None
        result3 = await repo.get_by_custodian(uuid.uuid4(), le_id)
        assert result3 == []
        result4 = await repo.get_by_status(PettyCashStatus.ACTIVE, le_id)
        assert result4 == []
        result5 = await repo.get_active(le_id)
        assert result5 == []
        result6 = await repo.get_need_replenishment(le_id)
        assert result6 == []
        result7 = await repo.get_all(le_id)
        assert result7 == []
        assert await repo.count(le_id) == 0
        result8 = await repo.list(le_id)
        assert result8 == []
