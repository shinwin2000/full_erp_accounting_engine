# tests/domain/equity_retained/test_aggregate_root.py
"""
Comprehensive tests for domain/equity_retained/aggregate_root.py
Covers all classes, exceptions, properties, business methods, event methods,
repository methods, and edge cases.
Uses mocks for dependent entities to isolate the aggregate.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from domain.equity_retained.aggregate_root import (
    DuplicateTransactionError,
    EquityAggregate,
    EquityAggregateError,
    EquityRepository,
    InsufficientPaidInCapitalError,
    InsufficientRetainedEarningsError,
    TransactionNotFoundError,
    _AsyncUnitOfWorkContext,
    _UnitOfWorkContext,
)
from domain.equity_retained.capital_contribution_entity import (
    CapitalContributionEntity,
    ContributionStatus,
)
from domain.equity_retained.capital_withdrawal_entity import (
    CapitalWithdrawalEntity,
    WithdrawalStatus,
)
from domain.equity_retained.dividend_declaration_entity import (
    DividendDeclarationEntity,
    DividendShareholderAllocation,
    DividendStatus,
)
from domain.equity_retained.retained_earnings_entity import RetainedEarningsEntity

# ============================================================================
# FIXED DATETIME
# ============================================================================

FIXED_NOW = datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC)
FIXED_PAST = FIXED_NOW - timedelta(days=30)
FIXED_FUTURE = FIXED_NOW + timedelta(days=30)


# ============================================================================
# MOCK HELPERS
# ============================================================================

def create_mock_contribution(
    contribution_id: uuid.UUID = None,
    status: ContributionStatus = ContributionStatus.DRAFT,
    amount: Decimal = Decimal("100000"),
    shareholder_id: uuid.UUID = None,
    can_approve: bool = True,
    can_post: bool = True,
    can_cancel: bool = True,
) -> CapitalContributionEntity:
    mock = MagicMock(spec=CapitalContributionEntity)
    mock.contribution_id = contribution_id or uuid.uuid4()
    mock.status = status
    mock.amount = amount
    mock.shareholder_id = shareholder_id or uuid.uuid4()
    mock.can_approve = can_approve
    mock.can_post = can_post
    mock.can_cancel = can_cancel
    mock.approve = MagicMock(return_value=mock)
    mock.post = MagicMock(return_value=mock)
    mock.cancel = MagicMock(return_value=mock)
    mock.clone = MagicMock(return_value=mock)
    return mock


def create_mock_withdrawal(
    withdrawal_id: uuid.UUID = None,
    status: WithdrawalStatus = WithdrawalStatus.DRAFT,
    amount: Decimal = Decimal("50000"),
    shareholder_id: uuid.UUID = None,
    can_approve: bool = True,
    can_post: bool = True,
    can_cancel: bool = True,
) -> CapitalWithdrawalEntity:
    mock = MagicMock(spec=CapitalWithdrawalEntity)
    mock.withdrawal_id = withdrawal_id or uuid.uuid4()
    mock.status = status
    mock.amount = amount
    mock.shareholder_id = shareholder_id or uuid.uuid4()
    mock.can_approve = can_approve
    mock.can_post = can_post
    mock.can_cancel = can_cancel
    mock.approve = MagicMock(return_value=mock)
    mock.post = MagicMock(return_value=mock)
    mock.cancel = MagicMock(return_value=mock)
    mock.clone = MagicMock(return_value=mock)
    return mock


def create_mock_retained_earnings(
    current_balance: Decimal = Decimal("500000"),
    entries: list = None,
) -> RetainedEarningsEntity:
    mock = MagicMock(spec=RetainedEarningsEntity)
    mock.current_balance = current_balance
    mock.entries = entries or []
    mock.add_net_income = MagicMock(return_value=mock)
    mock.add_prior_period_adjustment = MagicMock(return_value=mock)
    mock.record_dividend = MagicMock(return_value=mock)
    mock.clone = MagicMock(return_value=mock)
    mock.to_dict = MagicMock(return_value={})
    return mock


def create_mock_dividend(
    dividend_id: uuid.UUID = None,
    status: DividendStatus = DividendStatus.PROPOSED,
    total_amount: Decimal = Decimal("100000"),
    unpaid_amount: Decimal = Decimal("100000"),
    can_approve: bool = True,
    can_pay: bool = True,
    can_cancel: bool = True,
) -> DividendDeclarationEntity:
    mock = MagicMock(spec=DividendDeclarationEntity)
    mock.dividend_id = dividend_id or uuid.uuid4()
    mock.status = status
    mock.total_amount = total_amount
    mock.unpaid_amount = unpaid_amount
    mock.total_paid = total_amount - unpaid_amount
    mock.can_approve = can_approve
    mock.can_pay = can_pay
    mock.can_cancel = can_cancel
    mock.approve = MagicMock(return_value=mock)
    mock.cancel = MagicMock(return_value=mock)
    mock.record_payment = MagicMock(return_value=mock)
    mock.clone = MagicMock(return_value=mock)
    mock.to_dict = MagicMock(return_value={})
    return mock


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def fixed_now():
    return FIXED_NOW


@pytest.fixture
def legal_entity_id():
    return uuid.uuid4()


@pytest.fixture
def equity_id():
    return uuid.uuid4()


@pytest.fixture
def retained_earnings():
    return create_mock_retained_earnings()


@pytest.fixture
def contribution_draft():
    return create_mock_contribution(status=ContributionStatus.DRAFT)


@pytest.fixture
def contribution_approved():
    return create_mock_contribution(status=ContributionStatus.APPROVED)


@pytest.fixture
def withdrawal_draft():
    return create_mock_withdrawal(status=WithdrawalStatus.DRAFT)


@pytest.fixture
def withdrawal_approved():
    return create_mock_withdrawal(status=WithdrawalStatus.APPROVED)


@pytest.fixture
def dividend_proposed():
    return create_mock_dividend(status=DividendStatus.PROPOSED)


@pytest.fixture
def dividend_approved():
    return create_mock_dividend(status=DividendStatus.APPROVED)


@pytest.fixture
def sample_aggregate(
    equity_id,
    legal_entity_id,
    retained_earnings,
) -> EquityAggregate:
    with patch("domain.equity_retained.aggregate_root.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.UTC = UTC
        return EquityAggregate(
            equity_id=equity_id,
            legal_entity_id=legal_entity_id,
            legal_entity_name="Test Entity",
            retained_earnings=retained_earnings,
        )


# ============================================================================
# EXCEPTION TESTS
# ============================================================================

class TestExceptions:
    def test_equity_aggregate_error(self):
        with pytest.raises(EquityAggregateError):
            raise EquityAggregateError("test")

    def test_insufficient_paid_in_capital_error(self):
        with pytest.raises(InsufficientPaidInCapitalError):
            raise InsufficientPaidInCapitalError("test")

    def test_insufficient_retained_earnings_error(self):
        with pytest.raises(InsufficientRetainedEarningsError):
            raise InsufficientRetainedEarningsError("test")

    def test_duplicate_transaction_error(self):
        with pytest.raises(DuplicateTransactionError):
            raise DuplicateTransactionError("test")

    def test_transaction_not_found_error(self):
        with pytest.raises(TransactionNotFoundError):
            raise TransactionNotFoundError("test")


# ============================================================================
# UNIT OF WORK CONTEXT TESTS
# ============================================================================

class TestUnitOfWorkContexts:
    def test_uow_context(self):
        ctx = _UnitOfWorkContext()
        with ctx as c:
            assert c is ctx

    async def test_async_uow_context(self):
        ctx = _AsyncUnitOfWorkContext()
        async with ctx as c:
            assert c is ctx


# ============================================================================
# EQUITY AGGREGATE TESTS
# ============================================================================

class TestEquityAggregate:
    # ---- Construction & Validation ----
    def test_construction_valid(self, sample_aggregate):
        assert sample_aggregate.equity_id is not None
        assert sample_aggregate.legal_entity_id is not None
        assert sample_aggregate.legal_entity_name == "Test Entity"
        assert sample_aggregate.version == 1
        assert sample_aggregate.created_at == FIXED_NOW
        assert sample_aggregate.updated_at == FIXED_NOW
        assert sample_aggregate._snapshots is not None
        assert len(sample_aggregate._snapshots) > 0

    def test_construction_invalid_entity_name(self):
        with pytest.raises(EquityAggregateError, match="at least 2 characters"):
            EquityAggregate(
                equity_id=uuid.uuid4(),
                legal_entity_id=uuid.uuid4(),
                legal_entity_name="A",
            )

    def test_construction_invalid_version(self):
        with pytest.raises(EquityAggregateError, match="Version must be >= 1"):
            EquityAggregate(
                equity_id=uuid.uuid4(),
                legal_entity_id=uuid.uuid4(),
                legal_entity_name="Test",
                version=0,
            )

    # ---- Entity Basic Methods ----
    def test_create(self, sample_aggregate):
        result = sample_aggregate.create("creator")
        assert result is sample_aggregate
        assert len(sample_aggregate._audit_trail) >= 1
        assert sample_aggregate._audit_trail[-1]["action"] == "CREATE"

    def test_update(self, sample_aggregate):
        updated = sample_aggregate.update("updater", legal_entity_name="Updated Name")
        assert updated.legal_entity_name == "Updated Name"
        assert updated.version == sample_aggregate.version + 1
        assert updated.updated_at == FIXED_NOW
        assert len(updated._audit_trail) >= 1
        assert updated._audit_trail[-1]["action"] == "UPDATE"

    def test_update_protected_fields(self, sample_aggregate):
        original_id = sample_aggregate.equity_id
        original_created = sample_aggregate.created_at
        updated = sample_aggregate.update(
            "updater",
            equity_id=uuid.uuid4(),
            created_at=datetime.now(UTC),
            version=999,
        )
        assert updated.equity_id == original_id
        assert updated.created_at == original_created
        assert updated.version == sample_aggregate.version + 1  # not 999

    def test_delete_valid(self, sample_aggregate):
        # Need to make total_equity = 0 and no transactions for delete to work
        with patch.object(sample_aggregate, "total_equity", 0):
            with patch.object(sample_aggregate, "capital_contributions", {}):
                with patch.object(sample_aggregate, "capital_withdrawals", {}):
                    deleted = sample_aggregate.delete("deleter", "reason")
                    assert deleted.version == sample_aggregate.version + 1
                    assert deleted.updated_at == FIXED_NOW
                    assert len(deleted._audit_trail) >= 1
                    assert deleted._audit_trail[-1]["action"] == "DELETE"

    def test_delete_invalid_nonzero_equity(self, sample_aggregate):
        with patch.object(sample_aggregate, "total_equity", Decimal("1000")):
            with pytest.raises(EquityAggregateError, match="non-zero equity"):
                sample_aggregate.delete("deleter")

    def test_delete_invalid_transactions(self, sample_aggregate):
        with patch.object(sample_aggregate, "total_equity", 0):
            with patch.object(sample_aggregate, "capital_contributions", {"c1": MagicMock()}):
                with pytest.raises(EquityAggregateError, match="existing transactions"):
                    sample_aggregate.delete("deleter")

    def test_restore(self, sample_aggregate):
        restored = sample_aggregate.restore("restorer")
        assert restored.version == sample_aggregate.version + 1
        assert restored._audit_trail[-1]["action"] == "RESTORE"

    def test_activate(self, sample_aggregate):
        activated = sample_aggregate.activate("activator")
        assert activated.version == sample_aggregate.version + 1
        assert activated._audit_trail[-1]["action"] == "ACTIVATE"

    def test_deactivate(self, sample_aggregate):
        deactivated = sample_aggregate.deactivate("deactivator", "reason")
        assert deactivated.version == sample_aggregate.version + 1
        assert deactivated._audit_trail[-1]["action"] == "DEACTIVATE"

    def test_lock(self, sample_aggregate):
        locked = sample_aggregate.lock("locker", "reason")
        assert locked.version == sample_aggregate.version + 1
        assert locked._audit_trail[-1]["action"] == "LOCK"

    def test_unlock(self, sample_aggregate):
        unlocked = sample_aggregate.unlock("unlocker")
        assert unlocked.version == sample_aggregate.version + 1
        assert unlocked._audit_trail[-1]["action"] == "UNLOCK"

    def test_validate_valid(self, sample_aggregate):
        with patch.object(sample_aggregate, "total_posted_contributions", Decimal("1000")):
            with patch.object(sample_aggregate, "total_posted_withdrawals", Decimal("500")):
                with patch.object(sample_aggregate, "total_retained_earnings", Decimal("2000")):
                    with patch.object(sample_aggregate, "total_paid_in_capital", Decimal("500")):
                        with patch.object(sample_aggregate, "dividend_declarations", []):
                            result = sample_aggregate.validate()
                            assert result["is_valid"] is True
                            assert result["errors"] == []

    def test_validate_invalid_negative_contribution(self, sample_aggregate):
        mock_contrib = MagicMock()
        mock_contrib.amount = Decimal("-100")
        with patch.object(sample_aggregate, "capital_contributions", {"c1": mock_contrib}):
            result = sample_aggregate.validate()
            assert result["is_valid"] is False
            assert any("negative amount" in e for e in result["errors"])

    def test_validate_invalid_withdrawals_exceed_contributions(self, sample_aggregate):
        with patch.object(sample_aggregate, "total_posted_contributions", Decimal("1000")):
            with patch.object(sample_aggregate, "total_posted_withdrawals", Decimal("1500")):
                result = sample_aggregate.validate()
                assert result["is_valid"] is False
                assert any("exceed total contributions" in e for e in result["errors"])

    def test_to_dict(self, sample_aggregate):
        result = sample_aggregate.to_dict()
        assert result["legal_entity_name"] == "Test Entity"
        assert result["equity_id"] == str(sample_aggregate.equity_id)
        assert "version" in result

    def test_from_dict(self, sample_aggregate):
        data = sample_aggregate.to_dict()
        reconstructed = EquityAggregate.from_dict(data)
        assert reconstructed.equity_id == sample_aggregate.equity_id
        assert reconstructed.legal_entity_id == sample_aggregate.legal_entity_id
        assert reconstructed.legal_entity_name == sample_aggregate.legal_entity_name
        assert reconstructed.version == sample_aggregate.version

    def test_clone(self, sample_aggregate):
        cloned = sample_aggregate.clone()
        assert cloned.equity_id != sample_aggregate.equity_id
        assert cloned.legal_entity_id == sample_aggregate.legal_entity_id
        assert cloned.legal_entity_name == sample_aggregate.legal_entity_name
        assert cloned.version == 1
        assert cloned.created_at != sample_aggregate.created_at
        assert len(cloned._audit_trail) >= 1
        assert cloned._audit_trail[-1]["action"] == "CLONE"

    def test_snapshot(self, sample_aggregate):
        snap = sample_aggregate.snapshot()
        assert snap["version"] == sample_aggregate.version
        assert snap["equity_id"] == str(sample_aggregate.equity_id)
        assert "timestamp" in snap

    def test_get_version(self, sample_aggregate):
        assert sample_aggregate.get_version() == 1

    def test_audit_trail(self, sample_aggregate):
        trail = sample_aggregate.audit_trail()
        assert len(trail) >= 1
        sample_aggregate.touch("toucher")
        trail2 = sample_aggregate.audit_trail()
        assert len(trail2) >= 2
        assert trail2[-1]["action"] == "TOUCH"

    def test_touch(self, sample_aggregate):
        touched = sample_aggregate.touch("toucher")
        assert touched.version == sample_aggregate.version + 1
        assert touched.updated_at == FIXED_NOW
        assert touched._audit_trail[-1]["action"] == "TOUCH"

    # ---- Properties ----
    def test_total_paid_in_capital(self, sample_aggregate):
        contrib1 = create_mock_contribution(status=ContributionStatus.POSTED, amount=Decimal("1000"))
        contrib2 = create_mock_contribution(status=ContributionStatus.DRAFT, amount=Decimal("500"))
        withdrawal1 = create_mock_withdrawal(status=WithdrawalStatus.POSTED, amount=Decimal("300"))
        sample_aggregate.capital_contributions = {"c1": contrib1, "c2": contrib2}
        sample_aggregate.capital_withdrawals = {"w1": withdrawal1}
        assert sample_aggregate.total_paid_in_capital == Decimal("700")  # 1000 - 300

    def test_total_retained_earnings(self, sample_aggregate):
        mock_re = create_mock_retained_earnings(current_balance=Decimal("5000"))
        sample_aggregate.retained_earnings = mock_re
        assert sample_aggregate.total_retained_earnings == Decimal("5000")

    def test_total_equity(self, sample_aggregate):
        with patch.object(sample_aggregate, "total_paid_in_capital", Decimal("1000")):
            with patch.object(sample_aggregate, "total_retained_earnings", Decimal("500")):
                assert sample_aggregate.total_equity == Decimal("1500")

    def test_total_posted_contributions(self, sample_aggregate):
        c1 = create_mock_contribution(status=ContributionStatus.POSTED, amount=Decimal("1000"))
        c2 = create_mock_contribution(status=ContributionStatus.DRAFT, amount=Decimal("500"))
        sample_aggregate.capital_contributions = {"c1": c1, "c2": c2}
        assert sample_aggregate.total_posted_contributions == Decimal("1000")

    def test_total_posted_withdrawals(self, sample_aggregate):
        w1 = create_mock_withdrawal(status=WithdrawalStatus.POSTED, amount=Decimal("300"))
        w2 = create_mock_withdrawal(status=WithdrawalStatus.DRAFT, amount=Decimal("200"))
        sample_aggregate.capital_withdrawals = {"w1": w1, "w2": w2}
        assert sample_aggregate.total_posted_withdrawals == Decimal("300")

    def test_total_dividends_declared(self, sample_aggregate):
        d1 = create_mock_dividend(total_amount=Decimal("1000"))
        d2 = create_mock_dividend(total_amount=Decimal("2000"))
        sample_aggregate.dividend_declarations = [d1, d2]
        assert sample_aggregate.total_dividends_declared == Decimal("3000")

    def test_total_dividends_paid(self, sample_aggregate):
        d1 = create_mock_dividend(total_amount=Decimal("1000"), unpaid_amount=Decimal("0"), total_paid=Decimal("1000"))
        d2 = create_mock_dividend(total_amount=Decimal("2000"), unpaid_amount=Decimal("1000"), total_paid=Decimal("1000"))
        sample_aggregate.dividend_declarations = [d1, d2]
        assert sample_aggregate.total_dividends_paid == Decimal("2000")

    # ---- Query Methods ----
    def test_get_capital_contribution(self, sample_aggregate):
        cid = uuid.uuid4()
        contrib = create_mock_contribution(contribution_id=cid)
        sample_aggregate.capital_contributions = {cid: contrib}
        assert sample_aggregate.get_capital_contribution(cid) is contrib
        assert sample_aggregate.get_capital_contribution(uuid.uuid4()) is None

    def test_get_capital_withdrawal(self, sample_aggregate):
        wid = uuid.uuid4()
        withdrawal = create_mock_withdrawal(withdrawal_id=wid)
        sample_aggregate.capital_withdrawals = {wid: withdrawal}
        assert sample_aggregate.get_capital_withdrawal(wid) is withdrawal
        assert sample_aggregate.get_capital_withdrawal(uuid.uuid4()) is None

    def test_get_dividend_declaration(self, sample_aggregate):
        did = uuid.uuid4()
        dividend = create_mock_dividend(dividend_id=did)
        sample_aggregate.dividend_declarations = [dividend]
        assert sample_aggregate.get_dividend_declaration(did) is dividend
        assert sample_aggregate.get_dividend_declaration(uuid.uuid4()) is None

    def test_get_contributions_by_shareholder(self, sample_aggregate):
        sid = uuid.uuid4()
        c1 = create_mock_contribution(shareholder_id=sid)
        c2 = create_mock_contribution(shareholder_id=sid)
        c3 = create_mock_contribution(shareholder_id=uuid.uuid4())
        sample_aggregate.capital_contributions = {"c1": c1, "c2": c2, "c3": c3}
        result = sample_aggregate.get_contributions_by_shareholder(sid)
        assert len(result) == 2
        assert c1 in result
        assert c2 in result

    def test_get_withdrawals_by_shareholder(self, sample_aggregate):
        sid = uuid.uuid4()
        w1 = create_mock_withdrawal(shareholder_id=sid)
        w2 = create_mock_withdrawal(shareholder_id=sid)
        w3 = create_mock_withdrawal(shareholder_id=uuid.uuid4())
        sample_aggregate.capital_withdrawals = {"w1": w1, "w2": w2, "w3": w3}
        result = sample_aggregate.get_withdrawals_by_shareholder(sid)
        assert len(result) == 2

    def test_get_dividends_by_shareholder(self, sample_aggregate):
        sid = uuid.uuid4()
        alloc = MagicMock(spec=DividendShareholderAllocation)
        alloc.shareholder_id = sid
        d1 = create_mock_dividend()
        d1.allocations = [alloc]
        d2 = create_mock_dividend()
        d2.allocations = []
        sample_aggregate.dividend_declarations = [d1, d2]
        result = sample_aggregate.get_dividends_by_shareholder(sid)
        assert len(result) == 1
        assert result[0] is d1

    def test_get_shareholder_net_capital(self, sample_aggregate):
        sid = uuid.uuid4()
        c1 = create_mock_contribution(shareholder_id=sid, status=ContributionStatus.POSTED, amount=Decimal("1000"))
        c2 = create_mock_contribution(shareholder_id=sid, status=ContributionStatus.DRAFT, amount=Decimal("500"))
        w1 = create_mock_withdrawal(shareholder_id=sid, status=WithdrawalStatus.POSTED, amount=Decimal("300"))
        sample_aggregate.capital_contributions = {"c1": c1, "c2": c2}
        sample_aggregate.capital_withdrawals = {"w1": w1}
        assert sample_aggregate.get_shareholder_net_capital(sid) == Decimal("700")  # 1000 - 300

    # ---- Command Methods ----
    def test_add_capital_contribution(self, sample_aggregate, contribution_draft):
        cid = contribution_draft.contribution_id
        new_agg = sample_aggregate.add_capital_contribution(contribution_draft, "adder")
        assert new_agg is not sample_aggregate
        assert cid in new_agg.capital_contributions
        assert new_agg.capital_contributions[cid] is contribution_draft
        assert new_agg.version == sample_aggregate.version + 1
        # Check event registered
        events = new_agg.get_events()
        assert len(events) == 1
        assert events[0].__class__.__name__ == "CapitalContributionRecordedEvent"

    def test_add_capital_contribution_duplicate(self, sample_aggregate, contribution_draft):
        cid = contribution_draft.contribution_id
        sample_aggregate.capital_contributions = {cid: contribution_draft}
        with pytest.raises(DuplicateTransactionError, match="already exists"):
            sample_aggregate.add_capital_contribution(contribution_draft, "adder")

    def test_remove_capital_contribution_draft(self, sample_aggregate, contribution_draft):
        cid = contribution_draft.contribution_id
        sample_aggregate.capital_contributions = {cid: contribution_draft}
        new_agg = sample_aggregate.remove_capital_contribution(cid, "remover")
        assert cid not in new_agg.capital_contributions
        assert new_agg.version == sample_aggregate.version + 1
        assert new_agg._audit_trail[-1]["action"] == "REMOVE_CONTRIBUTION"

    def test_remove_capital_contribution_not_found(self, sample_aggregate):
        with pytest.raises(TransactionNotFoundError, match="not found"):
            sample_aggregate.remove_capital_contribution(uuid.uuid4(), "remover")

    def test_remove_capital_contribution_non_draft(self, sample_aggregate):
        contrib = create_mock_contribution(status=ContributionStatus.APPROVED)
        cid = contrib.contribution_id
        sample_aggregate.capital_contributions = {cid: contrib}
        with pytest.raises(EquityAggregateError, match="Cannot remove non-draft"):
            sample_aggregate.remove_capital_contribution(cid, "remover")

    def test_add_capital_withdrawal_valid(self, sample_aggregate, withdrawal_draft, contribution_draft):
        # Need enough paid-in capital
        contrib = create_mock_contribution(status=ContributionStatus.POSTED, amount=Decimal("100000"))
        sample_aggregate.capital_contributions = {"c1": contrib}
        wid = withdrawal_draft.withdrawal_id
        new_agg = sample_aggregate.add_capital_withdrawal(withdrawal_draft, "adder")
        assert wid in new_agg.capital_withdrawals
        assert new_agg.version == sample_aggregate.version + 1
        events = new_agg.get_events()
        assert len(events) == 1
        assert events[0].__class__.__name__ == "CapitalWithdrawalRecordedEvent"

    def test_add_capital_withdrawal_insufficient(self, sample_aggregate, withdrawal_draft):
        # No contributions -> paid-in capital = 0
        with pytest.raises(InsufficientPaidInCapitalError, match="exceeds paid-in capital"):
            sample_aggregate.add_capital_withdrawal(withdrawal_draft, "adder")

    def test_add_capital_withdrawal_duplicate(self, sample_aggregate, withdrawal_draft):
        wid = withdrawal_draft.withdrawal_id
        sample_aggregate.capital_withdrawals = {wid: withdrawal_draft}
        with pytest.raises(DuplicateTransactionError, match="already exists"):
            sample_aggregate.add_capital_withdrawal(withdrawal_draft, "adder")

    def test_remove_capital_withdrawal_draft(self, sample_aggregate, withdrawal_draft):
        wid = withdrawal_draft.withdrawal_id
        sample_aggregate.capital_withdrawals = {wid: withdrawal_draft}
        new_agg = sample_aggregate.remove_capital_withdrawal(wid, "remover")
        assert wid not in new_agg.capital_withdrawals
        assert new_agg.version == sample_aggregate.version + 1

    def test_remove_capital_withdrawal_not_found(self, sample_aggregate):
        with pytest.raises(TransactionNotFoundError, match="not found"):
            sample_aggregate.remove_capital_withdrawal(uuid.uuid4(), "remover")

    def test_remove_capital_withdrawal_non_draft(self, sample_aggregate):
        withdrawal = create_mock_withdrawal(status=WithdrawalStatus.APPROVED)
        wid = withdrawal.withdrawal_id
        sample_aggregate.capital_withdrawals = {wid: withdrawal}
        with pytest.raises(EquityAggregateError, match="Cannot remove non-draft"):
            sample_aggregate.remove_capital_withdrawal(wid, "remover")

    def test_add_dividend_declaration_valid(self, sample_aggregate, dividend_proposed):
        # Need sufficient retained earnings
        with patch.object(sample_aggregate, "total_retained_earnings", Decimal("200000")):
            new_agg = sample_aggregate.add_dividend_declaration(dividend_proposed, "declarer")
            assert dividend_proposed in new_agg.dividend_declarations
            assert new_agg.version == sample_aggregate.version + 1
            events = new_agg.get_events()
            assert len(events) == 1
            assert events[0].__class__.__name__ == "DividendDeclaredEvent"

    def test_add_dividend_declaration_insufficient(self, sample_aggregate, dividend_proposed):
        with patch.object(sample_aggregate, "total_retained_earnings", Decimal("100")):
            with pytest.raises(InsufficientRetainedEarningsError, match="exceeds retained earnings"):
                sample_aggregate.add_dividend_declaration(dividend_proposed, "declarer")

    def test_remove_dividend_declaration_proposed(self, sample_aggregate, dividend_proposed):
        sample_aggregate.dividend_declarations = [dividend_proposed]
        new_agg = sample_aggregate.remove_dividend_declaration(dividend_proposed.dividend_id, "remover")
        assert len(new_agg.dividend_declarations) == 0
        assert new_agg.version == sample_aggregate.version + 1

    def test_remove_dividend_declaration_not_found(self, sample_aggregate):
        with pytest.raises(TransactionNotFoundError, match="not found"):
            sample_aggregate.remove_dividend_declaration(uuid.uuid4(), "remover")

    def test_remove_dividend_declaration_non_proposed(self, sample_aggregate):
        dividend = create_mock_dividend(status=DividendStatus.APPROVED)
        sample_aggregate.dividend_declarations = [dividend]
        with pytest.raises(EquityAggregateError, match="Cannot remove dividend in status approved"):
            sample_aggregate.remove_dividend_declaration(dividend.dividend_id, "remover")

    # ---- Approve Methods ----
    def test_approve_capital_contribution(self, sample_aggregate, contribution_draft):
        cid = contribution_draft.contribution_id
        sample_aggregate.capital_contributions = {cid: contribution_draft}
        new_agg = sample_aggregate.approve_capital_contribution(cid, "approver")
        contribution_draft.approve.assert_called_once_with("approver")
        assert new_agg.version == sample_aggregate.version + 1
        events = new_agg.get_events()
        assert len(events) == 1
        assert events[0].__class__.__name__ == "CapitalContributionApprovedEvent"

    def test_approve_capital_contribution_not_found(self, sample_aggregate):
        with pytest.raises(TransactionNotFoundError, match="not found"):
            sample_aggregate.approve_capital_contribution(uuid.uuid4(), "approver")

    def test_approve_capital_contribution_not_approvable(self, sample_aggregate, contribution_draft):
        contribution_draft.can_approve = False
        cid = contribution_draft.contribution_id
        sample_aggregate.capital_contributions = {cid: contribution_draft}
        with pytest.raises(EquityAggregateError, match="Cannot approve contribution in status"):
            sample_aggregate.approve_capital_contribution(cid, "approver")

    def test_approve_capital_withdrawal(self, sample_aggregate, withdrawal_draft):
        wid = withdrawal_draft.withdrawal_id
        sample_aggregate.capital_withdrawals = {wid: withdrawal_draft}
        new_agg = sample_aggregate.approve_capital_withdrawal(wid, "approver")
        withdrawal_draft.approve.assert_called_once_with("approver")
        assert new_agg.version == sample_aggregate.version + 1
        events = new_agg.get_events()
        assert len(events) == 1
        assert events[0].__class__.__name__ == "CapitalWithdrawalApprovedEvent"

    def test_approve_capital_withdrawal_not_found(self, sample_aggregate):
        with pytest.raises(TransactionNotFoundError, match="not found"):
            sample_aggregate.approve_capital_withdrawal(uuid.uuid4(), "approver")

    def test_approve_dividend(self, sample_aggregate, dividend_proposed):
        did = dividend_proposed.dividend_id
        sample_aggregate.dividend_declarations = [dividend_proposed]
        new_agg = sample_aggregate.approve_dividend(did, "approver")
        dividend_proposed.approve.assert_called_once_with("approver")
        assert new_agg.version == sample_aggregate.version + 1
        events = new_agg.get_events()
        assert len(events) == 1
        assert events[0].__class__.__name__ == "DividendApprovedEvent"

    def test_approve_dividend_not_found(self, sample_aggregate):
        with pytest.raises(TransactionNotFoundError, match="not found"):
            sample_aggregate.approve_dividend(uuid.uuid4(), "approver")

    # ---- Reject Methods ----
    def test_reject_capital_contribution(self, sample_aggregate, contribution_draft):
        cid = contribution_draft.contribution_id
        sample_aggregate.capital_contributions = {cid: contribution_draft}
        new_agg = sample_aggregate.reject(cid, "contribution", "rejecter", "bad")
        contribution_draft.cancel.assert_called_once_with("rejecter", "bad")
        assert new_agg.version == sample_aggregate.version + 1
        events = new_agg.get_events()
        assert len(events) == 1
        assert events[0].__class__.__name__ == "CapitalContributionCancelledEvent"

    def test_reject_not_allowed(self, sample_aggregate):
        with patch.object(sample_aggregate, "can_reject", return_value=False):
            with pytest.raises(EquityAggregateError, match="Cannot reject"):
                sample_aggregate.reject(uuid.uuid4(), "contribution", "rejecter", "bad")

    def test_reject_unsupported_type(self, sample_aggregate):
        with pytest.raises(EquityAggregateError, match="Reject not implemented for"):
            sample_aggregate.reject(uuid.uuid4(), "dividend", "rejecter", "bad")

    # ---- Cancel Methods ----
    def test_cancel_capital_contribution(self, sample_aggregate, contribution_draft):
        cid = contribution_draft.contribution_id
        sample_aggregate.capital_contributions = {cid: contribution_draft}
        new_agg = sample_aggregate.cancel_capital_contribution(cid, "canceller", "reason")
        contribution_draft.cancel.assert_called_once_with("canceller", "reason")
        assert new_agg.version == sample_aggregate.version + 1
        events = new_agg.get_events()
        assert len(events) == 1
        assert events[0].__class__.__name__ == "CapitalContributionCancelledEvent"

    def test_cancel_capital_withdrawal(self, sample_aggregate, withdrawal_draft):
        wid = withdrawal_draft.withdrawal_id
        sample_aggregate.capital_withdrawals = {wid: withdrawal_draft}
        new_agg = sample_aggregate.cancel_capital_withdrawal(wid, "canceller", "reason")
        withdrawal_draft.cancel.assert_called_once_with("canceller", "reason")
        assert new_agg.version == sample_aggregate.version + 1

    def test_cancel_dividend(self, sample_aggregate, dividend_proposed):
        did = dividend_proposed.dividend_id
        sample_aggregate.dividend_declarations = [dividend_proposed]
        new_agg = sample_aggregate.cancel_dividend(did, "canceller", "reason")
        dividend_proposed.cancel.assert_called_once_with("canceller", "reason")
        assert new_agg.version == sample_aggregate.version + 1
        events = new_agg.get_events()
        assert len(events) == 1
        assert events[0].__class__.__name__ == "DividendCancelledEvent"

    def test_cancel_not_found(self, sample_aggregate):
        with pytest.raises(TransactionNotFoundError, match="not found"):
            sample_aggregate.cancel_capital_contribution(uuid.uuid4(), "canceller", "reason")

    # ---- Post Methods ----
    async def test_post_capital_contribution(self, sample_aggregate, contribution_draft):
        cid = contribution_draft.contribution_id
        sample_aggregate.capital_contributions = {cid: contribution_draft}
        new_agg = await sample_aggregate.post_capital_contribution(cid, "poster")
        contribution_draft.post.assert_called_once_with("poster")
        assert new_agg.version == sample_aggregate.version + 1
        events = new_agg.get_events()
        assert len(events) == 1
        assert events[0].__class__.__name__ == "CapitalContributionPostedEvent"

    async def test_post_capital_contribution_not_found(self, sample_aggregate):
        with pytest.raises(TransactionNotFoundError, match="not found"):
            await sample_aggregate.post_capital_contribution(uuid.uuid4(), "poster")

    async def test_post_capital_withdrawal(self, sample_aggregate, withdrawal_draft):
        wid = withdrawal_draft.withdrawal_id
        sample_aggregate.capital_withdrawals = {wid: withdrawal_draft}
        new_agg = await sample_aggregate.post_capital_withdrawal(wid, "poster")
        withdrawal_draft.post.assert_called_once_with("poster")
        assert new_agg.version == sample_aggregate.version + 1
        events = new_agg.get_events()
        assert len(events) == 1
        assert events[0].__class__.__name__ == "CapitalWithdrawalPostedEvent"

    # ---- Pay Dividend ----
    def test_pay_dividend(self, sample_aggregate, dividend_approved):
        did = dividend_approved.dividend_id
        sample_aggregate.dividend_declarations = [dividend_approved]
        sample_aggregate.retained_earnings = create_mock_retained_earnings(current_balance=Decimal("500000"))
        new_agg = sample_aggregate.pay_dividend(did, Decimal("100000"), "payer", FIXED_NOW)
        dividend_approved.record_payment.assert_called_once_with(
            Decimal("100000"), "payer", FIXED_NOW, None
        )
        assert new_agg.version == sample_aggregate.version + 1
        events = new_agg.get_events()
        assert len(events) == 1
        assert events[0].__class__.__name__ == "DividendPaidEvent"

    def test_pay_dividend_partial(self, sample_aggregate, dividend_approved):
        did = dividend_approved.dividend_id
        dividend_approved.status = DividendStatus.APPROVED
        dividend_approved.unpaid_amount = Decimal("100000")
        new_dividend = create_mock_dividend(status=DividendStatus.PARTIALLY_PAID, unpaid_amount=Decimal("50000"))
        dividend_approved.record_payment.return_value = new_dividend
        sample_aggregate.dividend_declarations = [dividend_approved]
        sample_aggregate.retained_earnings = create_mock_retained_earnings()
        new_agg = sample_aggregate.pay_dividend(did, Decimal("50000"), "payer", FIXED_NOW)
        events = new_agg.get_events()
        assert len(events) == 1
        assert events[0].__class__.__name__ == "DividendPartiallyPaidEvent"

    def test_pay_dividend_not_found(self, sample_aggregate):
        with pytest.raises(TransactionNotFoundError, match="not found"):
            sample_aggregate.pay_dividend(uuid.uuid4(), Decimal("100"), "payer")

    def test_pay_dividend_not_payable(self, sample_aggregate, dividend_proposed):
        did = dividend_proposed.dividend_id
        sample_aggregate.dividend_declarations = [dividend_proposed]
        with pytest.raises(EquityAggregateError, match="Cannot pay dividend in status proposed"):
            sample_aggregate.pay_dividend(did, Decimal("100"), "payer")

    def test_pay_dividend_zero_amount(self, sample_aggregate, dividend_approved):
        did = dividend_approved.dividend_id
        sample_aggregate.dividend_declarations = [dividend_approved]
        with pytest.raises(EquityAggregateError, match="Payment amount must be positive"):
            sample_aggregate.pay_dividend(did, Decimal("0"), "payer")

    def test_pay_dividend_exceeds_unpaid(self, sample_aggregate, dividend_approved):
        did = dividend_approved.dividend_id
        dividend_approved.unpaid_amount = Decimal("100")
        sample_aggregate.dividend_declarations = [dividend_approved]
        with pytest.raises(EquityAggregateError, match="exceeds unpaid amount"):
            sample_aggregate.pay_dividend(did, Decimal("200"), "payer")

    # ---- Net Income & Prior Period Adjustments ----
    def test_add_net_income(self, sample_aggregate):
        new_agg = sample_aggregate.add_net_income(Decimal("1000"), "2026-01", "updater", "desc")
        sample_aggregate.retained_earnings.add_net_income.assert_called_once_with(
            Decimal("1000"), "2026-01", "updater", "desc"
        )
        assert new_agg.version == sample_aggregate.version + 1
        events = new_agg.get_events()
        assert len(events) == 1
        assert events[0].__class__.__name__ == "RetainedEarningsUpdatedEvent"

    def test_add_prior_period_adjustment(self, sample_aggregate):
        new_agg = sample_aggregate.add_prior_period_adjustment(Decimal("-500"), "2025-12", "updater", "correction")
        sample_aggregate.retained_earnings.add_prior_period_adjustment.assert_called_once_with(
            Decimal("-500"), "2025-12", "updater", "correction"
        )
        assert new_agg.version == sample_aggregate.version + 1
        events = new_agg.get_events()
        assert len(events) == 1
        assert events[0].__class__.__name__ == "RetainedEarningsAdjustedEvent"

    # ---- Event Methods ----
    def test_register_event(self, sample_aggregate):
        event = MagicMock()
        sample_aggregate.register_event(event)
        assert len(sample_aggregate.get_events()) == 1
        assert sample_aggregate.get_events()[0] is event

    def test_pull_events(self, sample_aggregate):
        e1 = MagicMock()
        e2 = MagicMock()
        sample_aggregate.register_event(e1)
        sample_aggregate.register_event(e2)
        events = sample_aggregate.pull_events()
        assert len(events) == 2
        assert events[0] is e1
        assert events[1] is e2
        assert len(sample_aggregate.get_events()) == 0

    def test_clear_events(self, sample_aggregate):
        sample_aggregate.register_event(MagicMock())
        sample_aggregate.clear_events()
        assert len(sample_aggregate.get_events()) == 0

    def test_apply(self, sample_aggregate):
        event = MagicMock()
        sample_aggregate.apply(event)
        assert len(sample_aggregate.get_events()) == 1
        assert sample_aggregate.get_events()[0] is event

    # ---- from_events ----
    def test_from_events(self, sample_aggregate):
        event1 = MagicMock()
        event1.aggregate_id = sample_aggregate.equity_id
        event1.legal_entity_id = sample_aggregate.legal_entity_id
        event2 = MagicMock()
        agg = EquityAggregate.from_events([event1, event2])
        assert agg.equity_id == sample_aggregate.equity_id
        assert agg.legal_entity_id == sample_aggregate.legal_entity_id
        assert agg.version == 2

    def test_from_events_empty(self):
        with pytest.raises(ValueError, match="No events provided"):
            EquityAggregate.from_events([])

    # ---- Aggregate Root Lifecycle Methods ----
    def test_add_child_contribution(self, sample_aggregate, contribution_draft):
        with patch.object(sample_aggregate, "add_capital_contribution") as mock_add:
            sample_aggregate.add_child(contribution_draft, "adder")
            mock_add.assert_called_once_with(contribution_draft, "adder")

    def test_add_child_withdrawal(self, sample_aggregate, withdrawal_draft):
        with patch.object(sample_aggregate, "add_capital_withdrawal") as mock_add:
            sample_aggregate.add_child(withdrawal_draft, "adder")
            mock_add.assert_called_once_with(withdrawal_draft, "adder")

    def test_add_child_dividend(self, sample_aggregate, dividend_proposed):
        with patch.object(sample_aggregate, "add_dividend_declaration") as mock_add:
            sample_aggregate.add_child(dividend_proposed, "declarer")
            mock_add.assert_called_once_with(dividend_proposed, "declarer")

    def test_add_child_unknown(self, sample_aggregate):
        with pytest.raises(EquityAggregateError, match="Unknown entity type"):
            sample_aggregate.add_child("not an entity", "adder")

    def test_remove_child_contribution(self, sample_aggregate, contribution_draft):
        cid = contribution_draft.contribution_id
        sample_aggregate.capital_contributions = {cid: contribution_draft}
        new_agg = sample_aggregate.remove_child(cid, "contribution", "remover")
        assert cid not in new_agg.capital_contributions

    def test_remove_child_withdrawal(self, sample_aggregate, withdrawal_draft):
        wid = withdrawal_draft.withdrawal_id
        sample_aggregate.capital_withdrawals = {wid: withdrawal_draft}
        new_agg = sample_aggregate.remove_child(wid, "withdrawal", "remover")
        assert wid not in new_agg.capital_withdrawals

    def test_remove_child_dividend(self, sample_aggregate, dividend_proposed):
        did = dividend_proposed.dividend_id
        sample_aggregate.dividend_declarations = [dividend_proposed]
        new_agg = sample_aggregate.remove_child(did, "dividend", "remover")
        assert len(new_agg.dividend_declarations) == 0

    def test_remove_child_unknown_type(self, sample_aggregate):
        with pytest.raises(EquityAggregateError, match="Unknown entity type"):
            sample_aggregate.remove_child(uuid.uuid4(), "unknown", "remover")

    def test_can_post(self, sample_aggregate, contribution_draft, withdrawal_draft):
        cid = contribution_draft.contribution_id
        wid = withdrawal_draft.withdrawal_id
        sample_aggregate.capital_contributions = {cid: contribution_draft}
        sample_aggregate.capital_withdrawals = {wid: withdrawal_draft}
        assert sample_aggregate.can_post(cid, "contribution") is True
        assert sample_aggregate.can_post(wid, "withdrawal") is True
        assert sample_aggregate.can_post(uuid.uuid4(), "contribution") is False
        assert sample_aggregate.can_post(uuid.uuid4(), "withdrawal") is False
        assert sample_aggregate.can_post(uuid.uuid4(), "dividend") is False

    def test_post(self, sample_aggregate, contribution_draft):
        cid = contribution_draft.contribution_id
        sample_aggregate.capital_contributions = {cid: contribution_draft}
        with patch.object(sample_aggregate, "post_capital_contribution") as mock_post:
            sample_aggregate.post(cid, "contribution", "poster")
            mock_post.assert_called_once_with(cid, "poster")

    def test_post_unknown_type(self, sample_aggregate):
        with pytest.raises(EquityAggregateError, match="Cannot post transaction type"):
            sample_aggregate.post(uuid.uuid4(), "unknown", "poster")

    def test_can_approve(self, sample_aggregate, contribution_draft, withdrawal_draft, dividend_proposed):
        cid = contribution_draft.contribution_id
        wid = withdrawal_draft.withdrawal_id
        did = dividend_proposed.dividend_id
        sample_aggregate.capital_contributions = {cid: contribution_draft}
        sample_aggregate.capital_withdrawals = {wid: withdrawal_draft}
        sample_aggregate.dividend_declarations = [dividend_proposed]
        # User role finance_manager or admin should approve
        assert sample_aggregate.can_approve(cid, "contribution", "finance_manager") is True
        assert sample_aggregate.can_approve(cid, "contribution", "admin") is True
        assert sample_aggregate.can_approve(cid, "contribution", "user") is False
        assert sample_aggregate.can_approve(wid, "withdrawal", "finance_manager") is True
        assert sample_aggregate.can_approve(did, "dividend", "board") is True
        assert sample_aggregate.can_approve(did, "dividend", "admin") is True
        assert sample_aggregate.can_approve(did, "dividend", "user") is False

    def test_approve(self, sample_aggregate):
        with patch.object(sample_aggregate, "approve_capital_contribution") as mock_contrib:
            sample_aggregate.approve(uuid.uuid4(), "contribution", "approver")
            mock_contrib.assert_called_once()
        with patch.object(sample_aggregate, "approve_capital_withdrawal") as mock_withdraw:
            sample_aggregate.approve(uuid.uuid4(), "withdrawal", "approver")
            mock_withdraw.assert_called_once()
        with patch.object(sample_aggregate, "approve_dividend") as mock_dividend:
            sample_aggregate.approve(uuid.uuid4(), "dividend", "approver")
            mock_dividend.assert_called_once()

    def test_approve_unknown_type(self, sample_aggregate):
        with pytest.raises(EquityAggregateError, match="Cannot approve transaction type"):
            sample_aggregate.approve(uuid.uuid4(), "unknown", "approver")

    def test_can_reject(self, sample_aggregate, contribution_draft, withdrawal_draft):
        cid = contribution_draft.contribution_id
        wid = withdrawal_draft.withdrawal_id
        sample_aggregate.capital_contributions = {cid: contribution_draft}
        sample_aggregate.capital_withdrawals = {wid: withdrawal_draft}
        assert sample_aggregate.can_reject(cid, "contribution") is True
        assert sample_aggregate.can_reject(wid, "withdrawal") is True
        # Non-draft statuses
        contrib_approved = create_mock_contribution(status=ContributionStatus.APPROVED)
        cid2 = contrib_approved.contribution_id
        sample_aggregate.capital_contributions[cid2] = contrib_approved
        assert sample_aggregate.can_reject(cid2, "contribution") is False
        # unsupported type
        assert sample_aggregate.can_reject(uuid.uuid4(), "dividend") is False

    # ---- can_cancel ----
    def test_can_cancel(self, sample_aggregate, contribution_draft, withdrawal_draft, dividend_proposed):
        cid = contribution_draft.contribution_id
        wid = withdrawal_draft.withdrawal_id
        did = dividend_proposed.dividend_id
        sample_aggregate.capital_contributions = {cid: contribution_draft}
        sample_aggregate.capital_withdrawals = {wid: withdrawal_draft}
        sample_aggregate.dividend_declarations = [dividend_proposed]
        assert sample_aggregate.can_cancel(cid, "contribution") is True
        assert sample_aggregate.can_cancel(wid, "withdrawal") is True
        assert sample_aggregate.can_cancel(did, "dividend") is True
        assert sample_aggregate.can_cancel(uuid.uuid4(), "unknown") is False

    # ---- cancel (generic) ----
    def test_cancel_generic(self, sample_aggregate):
        with patch.object(sample_aggregate, "cancel_capital_contribution") as mock_contrib:
            sample_aggregate.cancel(uuid.uuid4(), "contribution", "canceller", "reason")
            mock_contrib.assert_called_once()
        with patch.object(sample_aggregate, "cancel_capital_withdrawal") as mock_withdraw:
            sample_aggregate.cancel(uuid.uuid4(), "withdrawal", "canceller", "reason")
            mock_withdraw.assert_called_once()
        with patch.object(sample_aggregate, "cancel_dividend") as mock_dividend:
            sample_aggregate.cancel(uuid.uuid4(), "dividend", "canceller", "reason")
            mock_dividend.assert_called_once()

    def test_cancel_unknown_type(self, sample_aggregate):
        with pytest.raises(EquityAggregateError, match="Cannot cancel transaction type"):
            sample_aggregate.cancel(uuid.uuid4(), "unknown", "canceller", "reason")

    # ---- can_reverse, reverse ----
    def test_can_reverse(self, sample_aggregate):
        assert sample_aggregate.can_reverse(uuid.uuid4(), "contribution") is False

    def test_reverse(self, sample_aggregate):
        with pytest.raises(NotImplementedError, match="Reverse not applicable"):
            sample_aggregate.reverse(uuid.uuid4(), "contribution", "reverser", "reason")

    # ---- can_close, close ----
    def test_can_close(self, sample_aggregate):
        with patch.object(sample_aggregate, "total_equity", Decimal("0")):
            with patch.object(sample_aggregate, "capital_contributions", {}):
                with patch.object(sample_aggregate, "capital_withdrawals", {}):
                    assert sample_aggregate.can_close() is True

    def test_close(self, sample_aggregate):
        with patch.object(sample_aggregate, "can_close", return_value=True):
            new_agg = sample_aggregate.close("closer", "reason")
            assert new_agg.version == sample_aggregate.version + 1
            assert new_agg._audit_trail[-1]["action"] == "CLOSE"

    def test_close_not_allowed(self, sample_aggregate):
        with patch.object(sample_aggregate, "can_close", return_value=False):
            with pytest.raises(EquityAggregateError, match="Cannot close"):
                sample_aggregate.close("closer", "reason")

    # ---- can_reopen, reopen ----
    def test_can_reopen(self, sample_aggregate):
        assert sample_aggregate.can_reopen() is True

    def test_reopen(self, sample_aggregate):
        new_agg = sample_aggregate.reopen("reopener", "reason")
        assert new_agg.version == sample_aggregate.version + 1
        assert new_agg._audit_trail[-1]["action"] == "REOPEN"

    # ---- can_archive, archive ----
    def test_can_archive(self, sample_aggregate):
        with patch.object(sample_aggregate, "capital_contributions", {}):
            with patch.object(sample_aggregate, "capital_withdrawals", {}):
                with patch.object(sample_aggregate, "dividend_declarations", []):
                    assert sample_aggregate.can_archive() is True

    def test_archive(self, sample_aggregate):
        with patch.object(sample_aggregate, "can_archive", return_value=True):
            new_agg = sample_aggregate.archive("archiver", "reason")
            assert new_agg.version == sample_aggregate.version + 1
            assert new_agg._audit_trail[-1]["action"] == "ARCHIVE"

    def test_archive_not_allowed(self, sample_aggregate):
        with patch.object(sample_aggregate, "can_archive", return_value=False):
            with patch.object(sample_aggregate, "capital_contributions", {"c1": MagicMock()}):
                with pytest.raises(EquityAggregateError, match="Cannot archive"):
                    sample_aggregate.archive("archiver", "reason")

    # ---- can_unarchive, unarchive ----
    def test_can_unarchive(self, sample_aggregate):
        assert sample_aggregate.can_unarchive() is True

    def test_unarchive(self, sample_aggregate):
        new_agg = sample_aggregate.unarchive("unarchiver")
        assert new_agg.version == sample_aggregate.version + 1
        assert new_agg._audit_trail[-1]["action"] == "UNARCHIVE"

    # ---- get_equity_summary ----
    def test_get_equity_summary(self, sample_aggregate):
        with patch.object(sample_aggregate, "total_paid_in_capital", Decimal("1000")):
            with patch.object(sample_aggregate, "total_retained_earnings", Decimal("500")):
                with patch.object(sample_aggregate, "total_equity", Decimal("1500")):
                    with patch.object(sample_aggregate, "total_posted_contributions", Decimal("1000")):
                        with patch.object(sample_aggregate, "total_posted_withdrawals", Decimal("200")):
                            with patch.object(sample_aggregate, "total_dividends_declared", Decimal("300")):
                                with patch.object(sample_aggregate, "total_dividends_paid", Decimal("200")):
                                    with patch.object(sample_aggregate, "capital_contributions", {"c1": MagicMock()}):
                                        with patch.object(sample_aggregate, "capital_withdrawals", {"w1": MagicMock()}):
                                            with patch.object(sample_aggregate, "dividend_declarations", [MagicMock()]):
                                                with patch.object(sample_aggregate.retained_earnings, "entries", []):
                                                    summary = sample_aggregate.get_equity_summary()
                                                    assert summary["paid_in_capital"] == "1000"
                                                    assert summary["retained_earnings"] == "500"
                                                    assert summary["total_equity"] == "1500"
                                                    assert summary["contributions_count"] == 1
                                                    assert summary["withdrawals_count"] == 1
                                                    assert summary["dividends_count"] == 1
                                                    assert summary["retained_earnings_entries_count"] == 0


# ============================================================================
# EQUITY REPOSITORY TESTS
# ============================================================================

class TestEquityRepository:
    @pytest.fixture
    def sample_aggregate(self):
        # Buat retained_earnings secara manual untuk menghindari bug di RetainedEarningsEntity.create
        retained = RetainedEarningsEntity(entity_id=uuid.uuid4(), opening_balance=Decimal("0"))
        return EquityAggregate(
            equity_id=uuid.uuid4(),
            legal_entity_id=uuid.uuid4(),
            legal_entity_name="Test",
            version=1,
            retained_earnings=retained,
        )

    @pytest.mark.asyncio
    async def test_save_and_get_by_id(self, sample_aggregate):
        repo = EquityRepository()
        await repo.clear()
        await repo.save(sample_aggregate)
        retrieved = await repo.get_by_id(sample_aggregate.equity_id)
        assert retrieved is not None
        assert retrieved.equity_id == sample_aggregate.equity_id

    @pytest.mark.asyncio
    async def test_get_by_legal_entity(self, sample_aggregate):
        repo = EquityRepository()
        await repo.clear()
        await repo.save(sample_aggregate)
        retrieved = await repo.get_by_legal_entity(sample_aggregate.legal_entity_id)
        assert retrieved is not None
        assert retrieved.legal_entity_id == sample_aggregate.legal_entity_id
        # Non-existent
        assert await repo.get_by_legal_entity(uuid.uuid4()) is None

    @pytest.mark.asyncio
    async def test_get_all(self, sample_aggregate):
        repo = EquityRepository()
        await repo.clear()
        await repo.save(sample_aggregate)
        all_ = await repo.get_all()
        assert len(all_) == 1
        assert all_[0].equity_id == sample_aggregate.equity_id

    @pytest.mark.asyncio
    async def test_update(self, sample_aggregate):
        repo = EquityRepository()
        await repo.clear()
        await repo.save(sample_aggregate)
        updated = sample_aggregate.update("updater", legal_entity_name="Updated")
        await repo.update(updated)
        retrieved = await repo.get_by_id(sample_aggregate.equity_id)
        assert retrieved.legal_entity_name == "Updated"
        assert retrieved.version == 2

    @pytest.mark.asyncio
    async def test_delete(self, sample_aggregate):
        repo = EquityRepository()
        await repo.clear()
        await repo.save(sample_aggregate)
        await repo.delete(sample_aggregate.equity_id)
        assert await repo.get_by_id(sample_aggregate.equity_id) is None

    @pytest.mark.asyncio
    async def test_exists(self, sample_aggregate):
        repo = EquityRepository()
        await repo.clear()
        await repo.save(sample_aggregate)
        assert await repo.exists(sample_aggregate.equity_id) is True
        assert await repo.exists(uuid.uuid4()) is False

    @pytest.mark.asyncio
    async def test_count(self, sample_aggregate):
        repo = EquityRepository()
        await repo.clear()
        assert await repo.count() == 0
        await repo.save(sample_aggregate)
        assert await repo.count() == 1

    @pytest.mark.asyncio
    async def test_list(self, sample_aggregate):
        repo = EquityRepository()
        await repo.clear()
        for i in range(5):
            agg = EquityAggregate(
                equity_id=uuid.uuid4(),
                legal_entity_id=uuid.uuid4(),
                legal_entity_name=f"Test {i}",
                version=1,
            )
            await repo.save(agg)
        results = await repo.list(limit=2, offset=1)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_paginate(self, sample_aggregate):
        repo = EquityRepository()
        await repo.clear()
        for i in range(5):
            agg = EquityAggregate(
                equity_id=uuid.uuid4(),
                legal_entity_id=uuid.uuid4(),
                legal_entity_name=f"Test {i}",
                version=1,
            )
            await repo.save(agg)
        page, total = await repo.paginate(page=2, per_page=2)
        assert len(page) == 2
        assert total == 5

    @pytest.mark.asyncio
    async def test_search(self, sample_aggregate):
        repo = EquityRepository()
        await repo.clear()
        agg1 = EquityAggregate(equity_id=uuid.uuid4(), legal_entity_id=uuid.uuid4(), legal_entity_name="Alpha Corp", version=1)
        agg2 = EquityAggregate(equity_id=uuid.uuid4(), legal_entity_id=uuid.uuid4(), legal_entity_name="Beta Inc", version=1)
        await repo.save(agg1)
        await repo.save(agg2)
        results = await repo.search("Alpha")
        assert len(results) == 1
        assert results[0].legal_entity_name == "Alpha Corp"
        # Search by equity_id
        results2 = await repo.search(str(agg1.equity_id))
        assert len(results2) == 1
        # No results
        results3 = await repo.search("Gamma")
        assert len(results3) == 0

    @pytest.mark.asyncio
    async def test_lock_unlock(self, sample_aggregate):
        repo = EquityRepository()
        await repo.clear()
        await repo.save(sample_aggregate)
        locked = await repo.lock(sample_aggregate.equity_id, "locker", "reason")
        assert locked.version == sample_aggregate.version + 1
        assert locked._audit_trail[-1]["action"] == "LOCK"
        unlocked = await repo.unlock(sample_aggregate.equity_id, "unlocker")
        assert unlocked.version == locked.version + 1
        assert unlocked._audit_trail[-1]["action"] == "UNLOCK"

    @pytest.mark.asyncio
    async def test_lock_not_found(self, sample_aggregate):
        repo = EquityRepository()
        await repo.clear()
        with pytest.raises(ValueError, match="not found"):
            await repo.lock(uuid.uuid4(), "locker", "reason")

    @pytest.mark.asyncio
    async def test_clear(self, sample_aggregate):
        repo = EquityRepository()
        await repo.clear()
        await repo.save(sample_aggregate)
        await repo.clear()
        assert await repo.count() == 0
