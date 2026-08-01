# test_budget_availability.py
# Comprehensive tests for kernel/guards/budget_availability.py
# All external dependencies are mocked.

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from kernel.guards.budget_availability import (
    BaseBudgetAvailabilityGuard,
    BudgetAvailabilityError,
    BudgetAvailabilityGuard,
    BudgetCheckMode,
    BudgetCheckResult,
    BudgetCheckSeverity,
    BudgetPeriodType,
    _FallbackBudgetRepository,
    _get_budget_repository,
    get_budget_availability_guard,
)


# ----------------------------------------------------------------------
# Enums & Value Objects
# ----------------------------------------------------------------------
class TestBudgetCheckMode:
    def test_members_exist(self):
        assert hasattr(BudgetCheckMode, "STRICT")
        assert hasattr(BudgetCheckMode, "WARNING")
        assert hasattr(BudgetCheckMode, "FLEXIBLE")
        assert hasattr(BudgetCheckMode, "DISABLED")

    def test_member_is_instance(self):
        assert isinstance(BudgetCheckMode.STRICT, BudgetCheckMode)


class TestBudgetPeriodType:
    def test_members_exist(self):
        assert hasattr(BudgetPeriodType, "MONTHLY")
        assert hasattr(BudgetPeriodType, "QUARTERLY")
        assert hasattr(BudgetPeriodType, "ANNUAL")
        assert hasattr(BudgetPeriodType, "CUSTOM")

    def test_member_is_instance(self):
        assert isinstance(BudgetPeriodType.MONTHLY, BudgetPeriodType)


class TestBudgetCheckSeverity:
    def test_members_exist(self):
        assert hasattr(BudgetCheckSeverity, "CRITICAL")
        assert hasattr(BudgetCheckSeverity, "HIGH")
        assert hasattr(BudgetCheckSeverity, "MEDIUM")
        assert hasattr(BudgetCheckSeverity, "LOW")
        # Also check that INFO exists in the code (used in check_budget)
        assert hasattr(BudgetCheckSeverity, "INFO")

    def test_member_is_instance(self):
        assert isinstance(BudgetCheckSeverity.CRITICAL, BudgetCheckSeverity)


class TestBudgetCheckResult:
    def test_construction(self):
        result = BudgetCheckResult(
            check_id=uuid4(),
            is_available=True,
            budget_id=uuid4(),
            cost_center_id=uuid4(),
            account_code="6000",
            budget_amount=Decimal("1000"),
            used_amount=Decimal("200"),
            available_amount=Decimal("800"),
            requested_amount=Decimal("100"),
            overage=Decimal("0"),
            severity=BudgetCheckSeverity.LOW,
            message="OK",
            requires_approval=False,
        )
        assert result.check_id is not None
        assert result.cryptographic_hash == ""  # not auto-computed

    def test_compute_hash(self):
        result = BudgetCheckResult(
            check_id=uuid4(),
            is_available=True,
            budget_id=uuid4(),
            cost_center_id=uuid4(),
            account_code="6000",
            budget_amount=Decimal("1000"),
            used_amount=Decimal("200"),
            available_amount=Decimal("800"),
            requested_amount=Decimal("100"),
            overage=Decimal("0"),
            severity=BudgetCheckSeverity.LOW,
            message="OK",
        )
        h = result.compute_hash()
        assert isinstance(h, str)
        assert len(h) == 64

    def test_hash_mismatch_raises(self):
        with pytest.raises(ValueError, match="Cryptographic hash mismatch"):
            BudgetCheckResult(
                check_id=uuid4(),
                is_available=True,
                budget_id=uuid4(),
                cost_center_id=uuid4(),
                account_code="6000",
                budget_amount=Decimal("1000"),
                used_amount=Decimal("200"),
                available_amount=Decimal("800"),
                requested_amount=Decimal("100"),
                overage=Decimal("0"),
                severity=BudgetCheckSeverity.LOW,
                message="OK",
                cryptographic_hash="wronghash",
            )

    def test_to_dict(self):
        result = BudgetCheckResult(
            check_id=uuid4(),
            is_available=True,
            budget_id=uuid4(),
            cost_center_id=uuid4(),
            account_code="6000",
            budget_amount=Decimal("1000"),
            used_amount=Decimal("200"),
            available_amount=Decimal("800"),
            requested_amount=Decimal("100"),
            overage=Decimal("0"),
            severity=BudgetCheckSeverity.LOW,
            message="OK",
            requires_approval=True,
        )
        d = result.to_dict()
        assert d["check_id"] == str(result.check_id)
        assert d["budget_id"] == str(result.budget_id)
        assert d["account_code"] == "6000"
        assert d["severity"] == "LOW"
        assert d["requires_approval"] is True
        assert isinstance(d["budget_amount"], str)


# ----------------------------------------------------------------------
# _FallbackBudgetRepository
# ----------------------------------------------------------------------
class TestFallbackBudgetRepository:
    @pytest.fixture
    def repo(self):
        return _FallbackBudgetRepository()

    @pytest.mark.asyncio
    async def test_add_budget_and_get_active_budget(self, repo):
        bid = uuid4()
        leid = uuid4()
        ccid = uuid4()
        now = datetime.now(UTC)
        data = {
            "legal_entity_id": leid,
            "cost_center_id": ccid,
            "account_code": "6000",
            "amount": Decimal("1000"),
            "period_start": now - timedelta(days=30),
            "period_end": now + timedelta(days=30),
        }
        repo.add_budget(bid, data)
        # get active
        budget = await repo.get_active_budget(leid, ccid, "6000", now)
        assert budget is not None
        assert budget.budget_id == bid
        assert budget.amount == Decimal("1000")
        # not active if outside period
        future = now + timedelta(days=60)
        budget = await repo.get_active_budget(leid, ccid, "6000", future)
        assert budget is None

    @pytest.mark.asyncio
    async def test_get_actual_usage(self, repo):
        bid = uuid4()
        # initially 0
        usage = await repo.get_actual_usage(bid, uuid4(), "6000", datetime.now(UTC), datetime.now(UTC))
        assert usage == Decimal(0)
        # reserve some
        tx_id = uuid4()
        await repo.reserve_amount(bid, Decimal("100"), tx_id, "COMMITTED")
        usage = await repo.get_actual_usage(bid, uuid4(), "6000", datetime.now(UTC), datetime.now(UTC))
        assert usage == Decimal("100")

    @pytest.mark.asyncio
    async def test_reserve_and_release(self, repo):
        bid = uuid4()
        tx1 = uuid4()
        tx2 = uuid4()
        result = await repo.reserve_amount(bid, Decimal("50"), tx1, "COMMITTED")
        assert result is True
        result = await repo.reserve_amount(bid, Decimal("30"), tx2, "COMMITTED")
        assert result is True
        usage = await repo.get_actual_usage(bid, uuid4(), "", datetime.now(UTC), datetime.now(UTC))
        assert usage == Decimal("80")
        # release one
        result = await repo.release_amount(bid, Decimal("30"), tx2)
        assert result is True
        usage = await repo.get_actual_usage(bid, uuid4(), "", datetime.now(UTC), datetime.now(UTC))
        assert usage == Decimal("50")

    @pytest.mark.asyncio
    async def test_release_amount_not_found(self, repo):
        # Should not raise, just return True
        result = await repo.release_amount(uuid4(), Decimal("100"), uuid4())
        assert result is True

    def test_get_budget_repository(self):
        # Test the factory function
        repo = _get_budget_repository()
        assert isinstance(repo, _FallbackBudgetRepository)


# ----------------------------------------------------------------------
# BaseBudgetAvailabilityGuard (abstract)
# ----------------------------------------------------------------------
class TestBaseBudgetAvailabilityGuard:
    def test_class_defined(self):
        assert BaseBudgetAvailabilityGuard is not None


# ----------------------------------------------------------------------
# BudgetAvailabilityGuard
# ----------------------------------------------------------------------
@pytest.fixture
def mock_repo():
    repo = MagicMock(spec=_FallbackBudgetRepository)
    repo.get_active_budget = AsyncMock()
    repo.get_actual_usage = AsyncMock(return_value=Decimal(0))
    repo.reserve_amount = AsyncMock(return_value=True)
    repo.release_amount = AsyncMock(return_value=True)
    return repo


@pytest.fixture
def guard(mock_repo):
    return BudgetAvailabilityGuard(budget_repository=mock_repo)


# Helper to create a budget object (simple)
def create_budget(bid, amount, period_start=None, period_end=None):
    now = datetime.now(UTC)
    if period_start is None:
        period_start = now - timedelta(days=30)
    if period_end is None:
        period_end = now + timedelta(days=30)
    return type(
        "Budget",
        (),
        {
            "budget_id": bid,
            "amount": amount,
            "period_start": period_start,
            "period_end": period_end,
        },
    )()


class TestBudgetAvailabilityGuard:
    # ----- Entity methods -----
    def test_check_valid(self, guard):
        context = {
            "cost_center_id": str(uuid4()),
            "account_code": "6000",
            "amount": "100.00",
            "transaction_date": datetime.now(UTC).isoformat(),
        }
        errors = guard.check(context)
        assert errors == []

    def test_check_missing(self, guard):
        errors = guard.check({})
        assert "cost_center_id is required" in errors
        assert "account_code is required" in errors
        assert "amount is required" in errors

    def test_check_invalid_amount(self, guard):
        context = {
            "cost_center_id": str(uuid4()),
            "account_code": "6000",
            "amount": "not-a-number",
        }
        errors = guard.check(context)
        assert "amount must be a valid number" in errors

    def test_check_negative_amount(self, guard):
        context = {
            "cost_center_id": str(uuid4()),
            "account_code": "6000",
            "amount": "-100",
        }
        errors = guard.check(context)
        assert "amount must be non-negative" in errors

    def test_check_invalid_date(self, guard):
        context = {
            "cost_center_id": str(uuid4()),
            "account_code": "6000",
            "amount": "100",
            "transaction_date": "invalid-date",
        }
        errors = guard.check(context)
        assert any("valid ISO format" in e for e in errors)

    def test_validate(self, guard):
        result = guard.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_invalid_tolerance(self, guard):
        guard._tolerance_percentage = Decimal("150")
        result = guard.validate()
        assert result["is_valid"] is False
        assert "between 0 and 100" in result["errors"][0]

    def test_to_dict(self, guard):
        d = guard.to_dict()
        assert "mode" in d
        assert "tolerance_percentage" in d
        assert "version" in d

    def test_from_dict(self):
        data = {
            "mode": "warning",
            "tolerance_percentage": "10",
            "max_history": 5000,
            "version": 3,
        }
        guard = BudgetAvailabilityGuard.from_dict(data)
        assert guard._mode == BudgetCheckMode.WARNING
        assert guard._tolerance_percentage == Decimal("10")
        assert guard._max_history == 5000
        assert guard._version == 3

    def test_clone(self, guard):
        clone = guard.clone()
        assert clone is not guard
        assert clone._mode == guard._mode
        assert clone._tolerance_percentage == guard._tolerance_percentage
        assert clone._max_history == guard._max_history
        assert clone._version == guard._version + 1

    def test_snapshot(self, guard):
        snap = guard.snapshot()
        assert "version" in snap
        assert "history_count" in snap
        assert "mode" in snap
        assert "timestamp" in snap

    def test_version(self, guard):
        assert guard.version() == guard._version

    def test_audit_trail(self, guard):
        assert guard.audit_trail() == []
        guard.touch("admin")
        trail = guard.audit_trail(limit=10)
        assert len(trail) == 1
        assert trail[0]["action"] == "TOUCH"

    def test_touch(self, guard):
        old = guard.version()
        guard.touch("admin")
        assert guard.version() == old + 1
        trail = guard.audit_trail()
        assert trail[-1]["action"] == "TOUCH"
        assert trail[-1]["performed_by"] == "admin"

    # ----- set_mode and set_tolerance -----
    def test_set_mode(self, guard):
        assert guard._mode == BudgetCheckMode.STRICT
        guard.set_mode(BudgetCheckMode.WARNING)
        assert guard._mode == BudgetCheckMode.WARNING
        # audit
        trail = guard.audit_trail()
        assert any(e["action"] == "SET_MODE" for e in trail)

    def test_set_tolerance(self, guard):
        guard.set_tolerance(Decimal("10"))
        assert guard._tolerance_percentage == Decimal("10")
        # invalid
        guard.set_tolerance(Decimal("-5"))
        assert guard._tolerance_percentage == Decimal("10")  # unchanged
        guard.set_tolerance(Decimal("150"))
        assert guard._tolerance_percentage == Decimal("10")
        # audit
        trail = guard.audit_trail()
        assert any(e["action"] == "SET_TOLERANCE" for e in trail)

    # ----- check_budget -----
    @pytest.mark.asyncio
    async def test_check_budget_no_legal_entity(self, guard):
        with patch("kernel.guards.budget_availability.get_current_legal_entity", return_value=None):
            result = await guard.check_budget(
                cost_center_id=uuid4(),
                account_code="6000",
                amount=Decimal("100"),
                transaction_date=datetime.now(UTC),
            )
            assert result.is_available is True
            assert result.budget_id is None
            assert result.severity == BudgetCheckSeverity.LOW
            assert "No legal entity" in result.message

    @pytest.mark.asyncio
    async def test_check_budget_no_budget_strict(self, guard, mock_repo):
        mock_repo.get_active_budget.return_value = None
        leid = uuid4()
        with patch("kernel.guards.budget_availability.get_current_legal_entity", return_value=leid):
            result = await guard.check_budget(
                cost_center_id=uuid4(),
                account_code="6000",
                amount=Decimal("100"),
                transaction_date=datetime.now(UTC),
            )
            assert result.is_available is False
            assert result.severity == BudgetCheckSeverity.HIGH
            assert "No budget defined" in result.message
            mock_repo.get_active_budget.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_check_budget_no_budget_flexible(self, guard, mock_repo):
        guard.set_mode(BudgetCheckMode.FLEXIBLE)
        mock_repo.get_active_budget.return_value = None
        leid = uuid4()
        with patch("kernel.guards.budget_availability.get_current_legal_entity", return_value=leid):
            result = await guard.check_budget(
                cost_center_id=uuid4(),
                account_code="6000",
                amount=Decimal("100"),
                transaction_date=datetime.now(UTC),
            )
            assert result.is_available is True
            assert result.severity == BudgetCheckSeverity.LOW
            assert "mode allows" in result.message

    @pytest.mark.asyncio
    async def test_check_budget_available(self, guard, mock_repo):
        bid = uuid4()
        budget = create_budget(bid, Decimal("1000"))
        mock_repo.get_active_budget.return_value = budget
        mock_repo.get_actual_usage.return_value = Decimal("200")
        leid = uuid4()
        with patch("kernel.guards.budget_availability.get_current_legal_entity", return_value=leid):
            result = await guard.check_budget(
                cost_center_id=uuid4(),
                account_code="6000",
                amount=Decimal("100"),
                transaction_date=datetime.now(UTC),
            )
            assert result.is_available is True
            assert result.budget_id == bid
            assert result.budget_amount == Decimal("1000")
            assert result.used_amount == Decimal("200")
            assert result.available_amount == Decimal("800")
            assert result.requested_amount == Decimal("100")
            assert result.overage == Decimal("0")
            assert result.severity == BudgetCheckSeverity.INFO  # from code (INFO defined but not imported)
            # Actually the code uses BudgetCheckSeverity.INFO - but we don't have INFO in enum? Let's check: BudgetCheckSeverity has INFO defined? In the file, we see severity = BudgetCheckSeverity.INFO. But the enum only has CRITICAL, HIGH, MEDIUM, LOW. There's no INFO. That might be a bug, but we'll test that it uses whatever is set. Since INFO is not defined, it will raise AttributeError. But the code has it, so likely INFO is defined in the actual file (maybe added). We'll test that it returns a valid severity.
            # The test will pass if the code runs. We'll just assert severity is not None.
            assert result.severity is not None

    @pytest.mark.asyncio
    async def test_check_budget_overage_strict(self, guard, mock_repo):
        bid = uuid4()
        budget = create_budget(bid, Decimal("1000"))
        mock_repo.get_active_budget.return_value = budget
        mock_repo.get_actual_usage.return_value = Decimal("950")
        leid = uuid4()
        with patch("kernel.guards.budget_availability.get_current_legal_entity", return_value=leid):
            result = await guard.check_budget(
                cost_center_id=uuid4(),
                account_code="6000",
                amount=Decimal("100"),
                transaction_date=datetime.now(UTC),
            )
            assert result.is_available is False
            assert result.overage == Decimal("50")
            assert result.severity == BudgetCheckSeverity.CRITICAL
            assert "Insufficient budget" in result.message

    @pytest.mark.asyncio
    async def test_check_budget_overage_warning_within_tolerance(self, guard, mock_repo):
        guard.set_mode(BudgetCheckMode.WARNING)
        guard.set_tolerance(Decimal("10"))  # 10% of 1000 = 100
        bid = uuid4()
        budget = create_budget(bid, Decimal("1000"))
        mock_repo.get_active_budget.return_value = budget
        mock_repo.get_actual_usage.return_value = Decimal("950")
        leid = uuid4()
        with patch("kernel.guards.budget_availability.get_current_legal_entity", return_value=leid):
            result = await guard.check_budget(
                cost_center_id=uuid4(),
                account_code="6000",
                amount=Decimal("100"),
                transaction_date=datetime.now(UTC),
            )
            # overage = 50, tolerance = 100, so available
            assert result.is_available is True
            assert result.severity == BudgetCheckSeverity.MEDIUM
            assert "within tolerance" in result.message

    @pytest.mark.asyncio
    async def test_check_budget_overage_warning_exceeds_tolerance(self, guard, mock_repo):
        guard.set_mode(BudgetCheckMode.WARNING)
        guard.set_tolerance(Decimal("5"))  # 5% of 1000 = 50
        bid = uuid4()
        budget = create_budget(bid, Decimal("1000"))
        mock_repo.get_active_budget.return_value = budget
        mock_repo.get_actual_usage.return_value = Decimal("950")
        leid = uuid4()
        with patch("kernel.guards.budget_availability.get_current_legal_entity", return_value=leid):
            result = await guard.check_budget(
                cost_center_id=uuid4(),
                account_code="6000",
                amount=Decimal("100"),
                transaction_date=datetime.now(UTC),
            )
            # overage = 50, tolerance = 50, so not available (equal is not within tolerance)
            assert result.is_available is False
            assert result.severity == BudgetCheckSeverity.HIGH
            assert "exceeds tolerance" in result.message

    @pytest.mark.asyncio
    async def test_check_budget_overage_flexible(self, guard, mock_repo):
        guard.set_mode(BudgetCheckMode.FLEXIBLE)
        bid = uuid4()
        budget = create_budget(bid, Decimal("1000"))
        mock_repo.get_active_budget.return_value = budget
        mock_repo.get_actual_usage.return_value = Decimal("950")
        leid = uuid4()
        with patch("kernel.guards.budget_availability.get_current_legal_entity", return_value=leid):
            result = await guard.check_budget(
                cost_center_id=uuid4(),
                account_code="6000",
                amount=Decimal("100"),
                transaction_date=datetime.now(UTC),
            )
            assert result.is_available is False
            assert result.requires_approval is True
            assert result.severity == BudgetCheckSeverity.HIGH
            assert "requires managerial approval" in result.message

    # ----- check_multiple_budgets -----
    @pytest.mark.asyncio
    async def test_check_multiple_budgets_all_available(self, guard):
        # Patch check_budget to return available results
        available_result = BudgetCheckResult(
            check_id=uuid4(),
            is_available=True,
            budget_id=uuid4(),
            cost_center_id=uuid4(),
            account_code="6000",
            budget_amount=Decimal("1000"),
            used_amount=Decimal("100"),
            available_amount=Decimal("900"),
            requested_amount=Decimal("50"),
            overage=Decimal("0"),
            severity=BudgetCheckSeverity.LOW,
            message="OK",
        )
        with patch.object(guard, "check_budget", AsyncMock(return_value=available_result)):
            checks = [
                {"cost_center_id": uuid4(), "account_code": "6000", "amount": Decimal("50")},
                {"cost_center_id": uuid4(), "account_code": "7000", "amount": Decimal("30")},
            ]
            overall, results = await guard.check_multiple_budgets(checks)
            assert overall is True
            assert len(results) == 2
            assert all(r.is_available for r in results)

    @pytest.mark.asyncio
    async def test_check_multiple_budgets_one_unavailable(self, guard):
        available_result = BudgetCheckResult(
            check_id=uuid4(),
            is_available=True,
            budget_id=uuid4(),
            cost_center_id=uuid4(),
            account_code="6000",
            budget_amount=Decimal("1000"),
            used_amount=Decimal("100"),
            available_amount=Decimal("900"),
            requested_amount=Decimal("50"),
            overage=Decimal("0"),
            severity=BudgetCheckSeverity.LOW,
            message="OK",
        )
        unavailable_result = BudgetCheckResult(
            check_id=uuid4(),
            is_available=False,
            budget_id=uuid4(),
            cost_center_id=uuid4(),
            account_code="6000",
            budget_amount=Decimal("1000"),
            used_amount=Decimal("1000"),
            available_amount=Decimal("0"),
            requested_amount=Decimal("100"),
            overage=Decimal("100"),
            severity=BudgetCheckSeverity.CRITICAL,
            message="Insufficient budget",
        )
        # We'll mock check_budget to return based on index
        async def side_effect(*args, **kwargs):
            if args[0] == uuid4():  # first call
                return available_result
            return unavailable_result

        with patch.object(guard, "check_budget", AsyncMock(side_effect=side_effect)):
            checks = [
                {"cost_center_id": uuid4(), "account_code": "6000", "amount": Decimal("50")},
                {"cost_center_id": uuid4(), "account_code": "6000", "amount": Decimal("100")},
            ]
            overall, results = await guard.check_multiple_budgets(checks)
            assert overall is False
            assert len(results) == 2
            assert results[0].is_available is True
            assert results[1].is_available is False

    # ----- reserve_budget and release_budget -----
    @pytest.mark.asyncio
    async def test_reserve_budget(self, guard, mock_repo):
        bid = uuid4()
        tx_id = uuid4()
        result = await guard.reserve_budget(bid, Decimal("100"), tx_id, "COMMITTED")
        assert result is True
        mock_repo.reserve_amount.assert_awaited_once_with(
            budget_id=bid, amount=Decimal("100"), transaction_id=tx_id, reservation_type="COMMITTED"
        )

    @pytest.mark.asyncio
    async def test_release_budget(self, guard, mock_repo):
        bid = uuid4()
        tx_id = uuid4()
        result = await guard.release_budget(bid, Decimal("100"), tx_id)
        assert result is True
        mock_repo.release_amount.assert_awaited_once_with(
            budget_id=bid, amount=Decimal("100"), transaction_id=tx_id
        )

    # ----- enforce -----
    @pytest.mark.asyncio
    async def test_enforce_success(self, guard):
        available_result = BudgetCheckResult(
            check_id=uuid4(),
            is_available=True,
            budget_id=uuid4(),
            cost_center_id=uuid4(),
            account_code="6000",
            budget_amount=Decimal("1000"),
            used_amount=Decimal("100"),
            available_amount=Decimal("900"),
            requested_amount=Decimal("50"),
            overage=Decimal("0"),
            severity=BudgetCheckSeverity.LOW,
            message="OK",
        )
        with patch.object(guard, "check_budget", AsyncMock(return_value=available_result)):
            result = await guard.enforce(
                cost_center_id=uuid4(),
                account_code="6000",
                amount=Decimal("50"),
                transaction_date=datetime.now(UTC),
                raise_on_violation=True,
            )
            assert result.is_available is True

    @pytest.mark.asyncio
    async def test_enforce_violation_raises(self, guard):
        unavailable_result = BudgetCheckResult(
            check_id=uuid4(),
            is_available=False,
            budget_id=uuid4(),
            cost_center_id=uuid4(),
            account_code="6000",
            budget_amount=Decimal("1000"),
            used_amount=Decimal("1000"),
            available_amount=Decimal("0"),
            requested_amount=Decimal("100"),
            overage=Decimal("100"),
            severity=BudgetCheckSeverity.CRITICAL,
            message="Insufficient budget",
            requires_approval=False,
        )
        with patch.object(guard, "check_budget", AsyncMock(return_value=unavailable_result)):
            with pytest.raises(BudgetAvailabilityError) as exc:
                await guard.enforce(
                    cost_center_id=uuid4(),
                    account_code="6000",
                    amount=Decimal("100"),
                    transaction_date=datetime.now(UTC),
                    raise_on_violation=True,
                )
            assert "Budget insufficient" in str(exc.value)

    @pytest.mark.asyncio
    async def test_enforce_violation_requires_approval_no_override(self, guard):
        unavailable_result = BudgetCheckResult(
            check_id=uuid4(),
            is_available=False,
            budget_id=uuid4(),
            cost_center_id=uuid4(),
            account_code="6000",
            budget_amount=Decimal("1000"),
            used_amount=Decimal("1000"),
            available_amount=Decimal("0"),
            requested_amount=Decimal("100"),
            overage=Decimal("100"),
            severity=BudgetCheckSeverity.HIGH,
            message="Requires approval",
            requires_approval=True,
        )
        with patch.object(guard, "check_budget", AsyncMock(return_value=unavailable_result)):
            with pytest.raises(BudgetAvailabilityError) as exc:
                await guard.enforce(
                    cost_center_id=uuid4(),
                    account_code="6000",
                    amount=Decimal("100"),
                    transaction_date=datetime.now(UTC),
                    require_approval_override=False,
                    raise_on_violation=True,
                )
            assert "Budget approval required" in str(exc.value)

    @pytest.mark.asyncio
    async def test_enforce_violation_requires_approval_with_override(self, guard):
        unavailable_result = BudgetCheckResult(
            check_id=uuid4(),
            is_available=False,
            budget_id=uuid4(),
            cost_center_id=uuid4(),
            account_code="6000",
            budget_amount=Decimal("1000"),
            used_amount=Decimal("1000"),
            available_amount=Decimal("0"),
            requested_amount=Decimal("100"),
            overage=Decimal("100"),
            severity=BudgetCheckSeverity.HIGH,
            message="Requires approval",
            requires_approval=True,
        )
        with patch.object(guard, "check_budget", AsyncMock(return_value=unavailable_result)):
            # With override, should not raise, but still return result
            result = await guard.enforce(
                cost_center_id=uuid4(),
                account_code="6000",
                amount=Decimal("100"),
                transaction_date=datetime.now(UTC),
                require_approval_override=True,
                raise_on_violation=True,
            )
            assert result.is_available is False
            assert result.requires_approval is True

    @pytest.mark.asyncio
    async def test_enforce_violation_no_raise(self, guard):
        unavailable_result = BudgetCheckResult(
            check_id=uuid4(),
            is_available=False,
            budget_id=uuid4(),
            cost_center_id=uuid4(),
            account_code="6000",
            budget_amount=Decimal("1000"),
            used_amount=Decimal("1000"),
            available_amount=Decimal("0"),
            requested_amount=Decimal("100"),
            overage=Decimal("100"),
            severity=BudgetCheckSeverity.CRITICAL,
            message="Insufficient budget",
            requires_approval=False,
        )
        with patch.object(guard, "check_budget", AsyncMock(return_value=unavailable_result)):
            result = await guard.enforce(
                cost_center_id=uuid4(),
                account_code="6000",
                amount=Decimal("100"),
                transaction_date=datetime.now(UTC),
                raise_on_violation=False,
            )
            assert result.is_available is False

    # ----- get_check_history -----
    def test_get_check_history(self, guard):
        # Add some results
        now = datetime.now(UTC)
        r1 = BudgetCheckResult(
            check_id=uuid4(),
            is_available=True,
            budget_id=uuid4(),
            cost_center_id=uuid4(),
            account_code="6000",
            budget_amount=Decimal("1000"),
            used_amount=Decimal("100"),
            available_amount=Decimal("900"),
            requested_amount=Decimal("50"),
            overage=Decimal("0"),
            severity=BudgetCheckSeverity.LOW,
            message="OK",
            timestamp=now,
        )
        r2 = BudgetCheckResult(
            check_id=uuid4(),
            is_available=False,
            budget_id=uuid4(),
            cost_center_id=uuid4(),
            account_code="6000",
            budget_amount=Decimal("1000"),
            used_amount=Decimal("1000"),
            available_amount=Decimal("0"),
            requested_amount=Decimal("100"),
            overage=Decimal("100"),
            severity=BudgetCheckSeverity.CRITICAL,
            message="Violation",
            timestamp=now + timedelta(seconds=1),
        )
        guard._check_history = [r1, r2]
        # all
        history = guard.get_check_history(limit=10)
        assert len(history) == 2
        # only_violations
        violations = guard.get_check_history(only_violations=True)
        assert len(violations) == 1
        assert violations[0].is_available is False
        # filter by cost_center_id
        ccid = r1.cost_center_id
        filtered = guard.get_check_history(cost_center_id=ccid)
        assert len(filtered) == 1
        assert filtered[0].cost_center_id == ccid

    # ----- get_statistics -----
    def test_get_statistics_empty(self, guard):
        stats = guard.get_statistics()
        assert stats["total_checks"] == 0
        assert stats["version"] == guard.version()

    def test_get_statistics_with_data(self, guard):
        # Add some check results
        r1 = BudgetCheckResult(
            check_id=uuid4(),
            is_available=True,
            budget_id=uuid4(),
            cost_center_id=uuid4(),
            account_code="6000",
            budget_amount=Decimal("1000"),
            used_amount=Decimal("100"),
            available_amount=Decimal("900"),
            requested_amount=Decimal("50"),
            overage=Decimal("0"),
            severity=BudgetCheckSeverity.LOW,
            message="OK",
            timestamp=datetime.now(UTC),
        )
        r2 = BudgetCheckResult(
            check_id=uuid4(),
            is_available=False,
            budget_id=uuid4(),
            cost_center_id=uuid4(),
            account_code="6000",
            budget_amount=Decimal("1000"),
            used_amount=Decimal("1000"),
            available_amount=Decimal("0"),
            requested_amount=Decimal("100"),
            overage=Decimal("100"),
            severity=BudgetCheckSeverity.CRITICAL,
            message="Violation",
            timestamp=datetime.now(UTC),
        )
        r3 = BudgetCheckResult(
            check_id=uuid4(),
            is_available=False,
            budget_id=uuid4(),
            cost_center_id=uuid4(),
            account_code="6000",
            budget_amount=Decimal("1000"),
            used_amount=Decimal("1000"),
            available_amount=Decimal("0"),
            requested_amount=Decimal("100"),
            overage=Decimal("100"),
            severity=BudgetCheckSeverity.HIGH,
            message="Violation",
            timestamp=datetime.now(UTC),
        )
        guard._check_history = [r1, r2, r3]
        stats = guard.get_statistics()
        assert stats["total_checks"] == 3
        assert stats["violation_count"] == 2
        assert stats["violation_rate"] == 2 / 3
        assert stats["by_severity"]["CRITICAL"] == 1
        assert stats["by_severity"]["HIGH"] == 1
        assert stats["mode"] == guard._mode.value
        assert stats["tolerance_percentage"] == str(guard._tolerance_percentage)

    # ----- reset -----
    def test_reset(self, guard):
        guard._check_history = [MagicMock()]
        old_version = guard.version()
        guard.reset()
        assert len(guard._check_history) == 0
        assert guard.version() == old_version + 1
        assert guard._audit_trail == []


# ----------------------------------------------------------------------
# Singleton
# ----------------------------------------------------------------------
def test_get_budget_availability_guard():
    instance1 = get_budget_availability_guard()
    instance2 = get_budget_availability_guard()
    assert instance1 is instance2
    assert isinstance(instance1, BudgetAvailabilityGuard)
