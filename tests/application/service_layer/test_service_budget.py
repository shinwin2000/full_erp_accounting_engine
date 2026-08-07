# tests/application/service_layer/test_service_budget.py
"""
Unit tests for BudgetService.
All external dependencies are mocked using AsyncMock.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from pytest import mark

from application.service_layer.service_budget import (
    BudgetAlreadyExistsError,
    BudgetCreateRequest,
    BudgetLineCreateRequest,
    BudgetLineRequest,
    BudgetLineUpdateRequest,
    BudgetNotFoundError,
    BudgetPeriodClosedError,
    BudgetRequest,
    BudgetResponse,
    BudgetService,
    BudgetServiceError,
    BudgetUpdateRequest,
    VarianceAnalysisRequest,
    VarianceAnalysisResponse,
    VarianceItem,
    audit,
    create_budget_service,
)
from domain.budget.aggregate_root import (
    BudgetAggregate,
    BudgetLine,
    BudgetPeriod,
    BudgetStatus,
    BudgetType,
)
from ports.primary.budget_repository_port import BudgetEntity, BudgetLineEntity

# ---------- DTO Tests ----------

class TestBudgetRequest:
    def _build_kwargs(self):
        return {
            "legal_entity_id": uuid4(),
            "budget_name": "test_value",
            "fiscal_year": 1,
            "lines": [{}],
            "period_type": "test_value",
            "description": "test_value",
        }

    def test_construction_success(self):
        kwargs = self._build_kwargs()
        instance = BudgetRequest(**kwargs)
        assert isinstance(instance, BudgetRequest)
        assert instance.legal_entity_id == kwargs["legal_entity_id"]


class TestBudgetResponse:
    def _build_kwargs(self):
        return {
            "id": uuid4(),
            "budget_code": "test_value",
            "budget_name": "test_value",
            "budget_type": "test_value",
            "fiscal_year": 1,
            "period": "test_value",
            "version": "test_value",
            "status": "test_value",
            "effective_date": date.today(),
            "expiry_date": date.today(),
            "currency": "USD",
            "total_amount": Decimal("100.00"),
            "notes": "test_value",
            "tags": ["test_value"],
            "is_locked": False,
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
            "created_by": uuid4(),
            "created_by_name": "test_value",
            "updated_by": uuid4(),
            "approved_at": datetime.now(UTC),
            "approved_by": uuid4(),
            "approved_by_name": "test_value",
            "submitted_at": datetime.now(UTC),
            "submitted_by": uuid4(),
            "rejected_at": datetime.now(UTC),
            "rejected_by": uuid4(),
            "rejection_reason": "test_value",
            "version_number": 1,
            "lines": [],
        }

    def test_construction_success(self):
        kwargs = self._build_kwargs()
        instance = BudgetResponse(**kwargs)
        assert isinstance(instance, BudgetResponse)
        assert instance.id == kwargs["id"]


class TestVarianceAnalysisRequest:
    def _build_kwargs(self):
        return {
            "legal_entity_id": uuid4(),
            "budget_id": uuid4(),
            "period_start": date.today(),
            "period_end": date.today(),
            "include_details": True,
        }

    def test_construction_success(self):
        kwargs = self._build_kwargs()
        instance = VarianceAnalysisRequest(**kwargs)
        assert isinstance(instance, VarianceAnalysisRequest)
        assert instance.legal_entity_id == kwargs["legal_entity_id"]


class TestVarianceItem:
    def _build_kwargs(self):
        return {
            "account_code": "test_value",
            "account_name": "test_value",
            "budget_amount": Decimal("100.00"),
            "actual_amount": Decimal("100.00"),
            "variance": Decimal("100.00"),
            "variance_percentage": 1.5,
            "variance_type": "test_value",
        }

    def test_construction_success(self):
        kwargs = self._build_kwargs()
        instance = VarianceItem(**kwargs)
        assert isinstance(instance, VarianceItem)
        assert instance.account_code == kwargs["account_code"]


class TestVarianceAnalysisResponse:
    def _build_kwargs(self):
        return {
            "budget_id": uuid4(),
            "budget_name": "test_value",
            "period_start": date.today(),
            "period_end": date.today(),
            "total_budget": Decimal("100.00"),
            "total_actual": Decimal("100.00"),
            "total_variance": Decimal("100.00"),
            "variance_percentage": 1.5,
            "items": [],
            "analysis_date": datetime.now(UTC),
        }

    def test_construction_success(self):
        kwargs = self._build_kwargs()
        instance = VarianceAnalysisResponse(**kwargs)
        assert isinstance(instance, VarianceAnalysisResponse)
        assert instance.budget_id == kwargs["budget_id"]


class TestBudgetLineRequest:
    def _build_kwargs(self):
        return {
            "account_code": "test_value",
            "amount": Decimal("100.00"),
            "period": "test_value",
            "description": "test_value",
        }

    def test_construction_success(self):
        kwargs = self._build_kwargs()
        instance = BudgetLineRequest(**kwargs)
        assert isinstance(instance, BudgetLineRequest)
        assert instance.account_code == kwargs["account_code"]


class TestBudgetServiceError:
    def test_construction(self):
        instance = BudgetServiceError()
        assert isinstance(instance, BudgetServiceError)


class TestBudgetNotFoundError:
    def test_construction(self):
        instance = BudgetNotFoundError()
        assert isinstance(instance, BudgetNotFoundError)


class TestBudgetAlreadyExistsError:
    def test_construction(self):
        instance = BudgetAlreadyExistsError()
        assert isinstance(instance, BudgetAlreadyExistsError)


class TestBudgetPeriodClosedError:
    def test_construction(self):
        instance = BudgetPeriodClosedError()
        assert isinstance(instance, BudgetPeriodClosedError)


# ---------- Service Tests ----------

@pytest.fixture
def mock_budget_repo():
    return AsyncMock()

@pytest.fixture
def mock_uow():
    return AsyncMock()

@pytest.fixture
def mock_event_publisher():
    return AsyncMock()

@pytest.fixture
def mock_ledger_repo():
    return AsyncMock()

@pytest.fixture
def budget_service(mock_budget_repo, mock_uow, mock_event_publisher, mock_ledger_repo):
    return BudgetService(
        budget_repo=mock_budget_repo,
        uow=mock_uow,
        event_publisher=mock_event_publisher,
        ledger_repo=mock_ledger_repo,
    )


@pytest.fixture
def sample_budget_entity():
    """A BudgetEntity with a few lines for testing."""
    entity_id = uuid4()
    line_id = uuid4()
    return BudgetEntity(
        id=entity_id,
        legal_entity_id=uuid4(),
        budget_code="TEST-001",
        budget_name="Test Budget",
        budget_type="operational",
        fiscal_year=2025,
        period="monthly",
        version="1.0",
        status="draft",
        effective_date=date(2025, 1, 1),
        expiry_date=date(2025, 12, 31),
        currency="IDR",
        total_amount=Decimal("10000"),
        notes=None,
        tags=[],
        is_locked=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        created_by=uuid4(),
        updated_by=None,
        approved_at=None,
        approved_by=None,
        submitted_at=None,
        submitted_by=None,
        rejected_at=None,
        rejected_by=None,
        rejection_reason=None,
        version_number=1,
        lines=[
            BudgetLineEntity(
                id=line_id,
                account_id=uuid4(),
                account_code="REV-001",
                amount=Decimal("5000"),
                note="Revenue line",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        ],
    )


@pytest.fixture
def mock_aggregate(sample_budget_entity):
    """Create a mock BudgetAggregate that behaves like the real one."""
    agg = MagicMock(spec=BudgetAggregate)
    agg.id = sample_budget_entity.id
    agg.budget_code = sample_budget_entity.budget_code
    agg.budget_name = sample_budget_entity.budget_name
    agg.budget_type = BudgetType.OPERATIONAL
    agg.fiscal_year = sample_budget_entity.fiscal_year
    agg.period = BudgetPeriod.MONTHLY
    agg.version = sample_budget_entity.version
    agg.status = BudgetStatus.DRAFT
    agg.effective_date = sample_budget_entity.effective_date
    agg.expiry_date = sample_budget_entity.expiry_date
    agg.currency = sample_budget_entity.currency
    agg.total_amount = sample_budget_entity.total_amount
    agg.notes = sample_budget_entity.notes
    agg.tags = sample_budget_entity.tags
    agg.is_locked = sample_budget_entity.is_locked
    agg.created_at = sample_budget_entity.created_at
    agg.updated_at = sample_budget_entity.updated_at
    agg.created_by = sample_budget_entity.created_by
    agg.updated_by = sample_budget_entity.updated_by
    agg.approved_at = sample_budget_entity.approved_at
    agg.approved_by = sample_budget_entity.approved_by
    agg.submitted_at = sample_budget_entity.submitted_at
    agg.submitted_by = sample_budget_entity.submitted_by
    agg.rejected_at = sample_budget_entity.rejected_at
    agg.rejected_by = sample_budget_entity.rejected_by
    agg.rejection_reason = sample_budget_entity.rejection_reason
    agg.version_number = sample_budget_entity.version_number
    agg.lines = [
        BudgetLine(
            id=line.id,
            account_id=line.account_id,
            account_code=line.account_code,
            amount=line.amount,
            note=line.note,
            created_at=line.created_at,
            updated_at=line.updated_at,
        )
        for line in sample_budget_entity.lines
    ]
    # Mock methods that are called
    agg.submit = MagicMock()
    agg.approve = MagicMock()
    agg.reject = MagicMock()
    agg.activate = MagicMock()
    agg.lock = MagicMock()
    agg.unlock = MagicMock()
    agg.archive = MagicMock()
    agg.cancel = MagicMock()
    agg.close = MagicMock()
    agg.add_line = MagicMock()
    agg.update_line = MagicMock()
    agg.remove_line = MagicMock()
    agg.pull_events = MagicMock(return_value=[])
    return agg


@mark.asyncio
async def test_create_budget_success(budget_service, mock_budget_repo, mock_uow):
    """Test create_budget with valid data."""
    request = BudgetCreateRequest(
        legal_entity_id=uuid4(),
        budget_code="TEST-001",
        budget_name="Test Budget",
        budget_type="operational",
        fiscal_year=2025,
        period="monthly",
        effective_date=date(2025, 1, 1),
        expiry_date=date(2025, 12, 31),
        currency="IDR",
        lines=[
            BudgetLineCreateRequest(
                account_id=uuid4(),
                account_code="REV-001",
                amount=Decimal("5000"),
                note="Revenue"
            )
        ],
        created_by=uuid4(),
        notes=None,
        tags=None,
    )

    mock_budget_repo.get_by_code_and_year = AsyncMock(return_value=None)
    mock_budget_repo.save = AsyncMock(return_value=None)
    mock_uow.commit = AsyncMock(return_value=None)

    # Create a mock aggregate to return from BudgetAggregate.create
    mock_agg = MagicMock(spec=BudgetAggregate)
    mock_agg.id = uuid4()
    mock_agg.budget_code = request.budget_code
    mock_agg.budget_name = request.budget_name
    mock_agg.budget_type = BudgetType.OPERATIONAL
    mock_agg.fiscal_year = request.fiscal_year
    mock_agg.period = BudgetPeriod.MONTHLY
    mock_agg.version = "1.0"
    mock_agg.status = BudgetStatus.DRAFT
    mock_agg.effective_date = request.effective_date
    mock_agg.expiry_date = request.expiry_date
    mock_agg.currency = request.currency
    mock_agg.total_amount = Decimal("5000")
    mock_agg.notes = request.notes
    mock_agg.tags = request.tags
    mock_agg.is_locked = False
    mock_agg.created_at = datetime.now(UTC)
    mock_agg.updated_at = datetime.now(UTC)
    mock_agg.created_by = request.created_by
    mock_agg.updated_by = None
    mock_agg.approved_at = None
    mock_agg.approved_by = None
    mock_agg.submitted_at = None
    mock_agg.submitted_by = None
    mock_agg.rejected_at = None
    mock_agg.rejected_by = None
    mock_agg.rejection_reason = None
    mock_agg.version_number = 1
    mock_agg.lines = [
        BudgetLine(
            id=uuid4(),
            account_id=request.lines[0].account_id,
            account_code=request.lines[0].account_code,
            amount=request.lines[0].amount,
            note=request.lines[0].note,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    ]
    mock_agg.pull_events = MagicMock(return_value=[])

    # Patch BudgetAggregate.create to return the mock aggregate
    with patch('domain.budget.aggregate_root.BudgetAggregate.create', return_value=mock_agg):
        # Also patch _aggregate_to_entity to return a proper entity (optional)
        with patch.object(budget_service, '_aggregate_to_entity', return_value=MagicMock()):
            response = await budget_service.create_budget(request)

    assert isinstance(response, BudgetResponse)
    assert response.budget_code == request.budget_code
    assert response.fiscal_year == request.fiscal_year
    assert len(response.lines) == 1
    mock_budget_repo.get_by_code_and_year.assert_awaited_once_with(
        request.legal_entity_id, request.budget_code, request.fiscal_year
    )
    mock_budget_repo.save.assert_awaited_once()
    mock_uow.commit.assert_awaited_once()


@mark.asyncio
async def test_create_budget_already_exists(budget_service, mock_budget_repo):
    """Test create_budget raises BudgetAlreadyExistsError if budget already exists."""
    request = BudgetCreateRequest(
        legal_entity_id=uuid4(),
        budget_code="TEST-001",
        budget_name="Test Budget",
        budget_type="operational",
        fiscal_year=2025,
        period="monthly",
        effective_date=date(2025, 1, 1),
        expiry_date=date(2025, 12, 31),
        currency="IDR",
        lines=[],
        created_by=uuid4(),
        notes=None,
        tags=None,
    )
    mock_budget_repo.get_by_code_and_year = AsyncMock(return_value=MagicMock())

    with pytest.raises(BudgetAlreadyExistsError):
        await budget_service.create_budget(request)


@mark.asyncio
async def test_get_budget_success(budget_service, mock_budget_repo, sample_budget_entity):
    """Test get_budget returns a BudgetResponse."""
    mock_budget_repo.get_by_id = AsyncMock(return_value=sample_budget_entity)

    response = await budget_service.get_budget(sample_budget_entity.id)

    assert isinstance(response, BudgetResponse)
    assert response.id == sample_budget_entity.id
    assert response.budget_code == sample_budget_entity.budget_code
    assert len(response.lines) == 1
    mock_budget_repo.get_by_id.assert_awaited_once_with(sample_budget_entity.id)


@mark.asyncio
async def test_get_budget_not_found(budget_service, mock_budget_repo):
    """Test get_budget raises BudgetNotFoundError if not found."""
    mock_budget_repo.get_by_id = AsyncMock(return_value=None)

    with pytest.raises(BudgetNotFoundError):
        await budget_service.get_budget(uuid4())


@mark.asyncio
async def test_list_budgets(budget_service, mock_budget_repo, sample_budget_entity):
    """Test list_budgets returns a list of BudgetResponse."""
    mock_budget_repo.list_by_legal_entity = AsyncMock(return_value=[sample_budget_entity])

    response = await budget_service.list_budgets(legal_entity_id=sample_budget_entity.legal_entity_id)

    assert len(response) == 1
    assert isinstance(response[0], BudgetResponse)
    mock_budget_repo.list_by_legal_entity.assert_awaited_once_with(
        sample_budget_entity.legal_entity_id, None, None
    )


@mark.asyncio
async def test_update_budget_success(budget_service, mock_budget_repo, sample_budget_entity, mock_uow):
    """Test update_budget updates and returns the budget."""
    mock_budget_repo.get_by_id = AsyncMock(return_value=sample_budget_entity)
    mock_budget_repo.update = AsyncMock(return_value=None)
    mock_uow.commit = AsyncMock(return_value=None)

    request = BudgetUpdateRequest(
        id=sample_budget_entity.id,
        legal_entity_id=sample_budget_entity.legal_entity_id,
        budget_name="Updated Name",
        effective_date=date(2025, 2, 1),
        expiry_date=date(2025, 12, 31),
        notes="Updated notes",
        tags=["tag1"],
        updated_by=uuid4(),
    )

    # Mock aggregate with required attributes for _record_audit
    mock_agg = MagicMock()
    mock_agg.id = sample_budget_entity.id
    mock_agg.budget_code = sample_budget_entity.budget_code

    # Patch BudgetAggregate constructor to return mock_agg
    with patch('application.service_layer.service_budget.BudgetAggregate', return_value=mock_agg):
        # Patch _aggregate_to_entity to return sample_budget_entity
        with patch.object(budget_service, '_aggregate_to_entity', return_value=sample_budget_entity):
            # Patch _to_response to return a BudgetResponse
            with patch.object(budget_service, '_to_response', return_value=MagicMock(spec=BudgetResponse)):
                # Patch _record_audit to avoid using aggregate attributes (already mocked)
                with patch.object(budget_service, '_record_audit'):
                    response = await budget_service.update_budget(request)

    assert isinstance(response, BudgetResponse)
    mock_budget_repo.update.assert_awaited_once()
    mock_uow.commit.assert_awaited_once()


@mark.asyncio
async def test_update_budget_not_found(budget_service, mock_budget_repo):
    """Test update_budget raises BudgetNotFoundError."""
    mock_budget_repo.get_by_id = AsyncMock(return_value=None)

    request = BudgetUpdateRequest(
        id=uuid4(),
        legal_entity_id=uuid4(),
        budget_name="Updated Name",
        effective_date=date(2025, 2, 1),
        expiry_date=date(2025, 12, 31),
        notes=None,
        tags=None,
        updated_by=uuid4(),
    )

    with pytest.raises(BudgetNotFoundError):
        await budget_service.update_budget(request)


@mark.asyncio
async def test_delete_budget_success(budget_service, mock_budget_repo, mock_uow):
    """Test delete_budget returns True and commits."""
    budget_id = uuid4()
    user_id = uuid4()
    mock_budget_repo.delete = AsyncMock(return_value=True)
    mock_uow.commit = AsyncMock(return_value=None)

    result = await budget_service.delete_budget(budget_id, user_id)

    assert result is True
    mock_budget_repo.delete.assert_awaited_once_with(budget_id)
    mock_uow.commit.assert_awaited_once()


@mark.asyncio
async def test_delete_budget_false(budget_service, mock_budget_repo, mock_uow):
    """Test delete_budget returns False and does not commit."""
    budget_id = uuid4()
    user_id = uuid4()
    mock_budget_repo.delete = AsyncMock(return_value=False)

    result = await budget_service.delete_budget(budget_id, user_id)

    assert result is False
    mock_budget_repo.delete.assert_awaited_once_with(budget_id)
    mock_uow.commit.assert_not_awaited()


# Workflow actions - use mock aggregate to avoid complex domain logic

@mark.asyncio
async def test_submit_budget(budget_service, mock_aggregate):
    """Test submit_budget calls aggregate.submit and saves."""
    budget_id = uuid4()
    user_id = uuid4()
    with patch.object(budget_service, "_get_aggregate", AsyncMock(return_value=mock_aggregate)):
        with patch.object(budget_service, "_save_aggregate", AsyncMock(return_value=None)):
            with patch.object(budget_service, "_to_response", return_value=MagicMock(spec=BudgetResponse)):
                response = await budget_service.submit_budget(budget_id=budget_id, user_id=user_id)

    mock_aggregate.submit.assert_called_once_with(user_id)
    assert isinstance(response, BudgetResponse)


@mark.asyncio
async def test_approve_budget(budget_service, mock_aggregate):
    budget_id = uuid4()
    user_id = uuid4()
    with patch.object(budget_service, "_get_aggregate", AsyncMock(return_value=mock_aggregate)):
        with patch.object(budget_service, "_save_aggregate", AsyncMock(return_value=None)):
            with patch.object(budget_service, "_to_response", return_value=MagicMock(spec=BudgetResponse)):
                response = await budget_service.approve_budget(budget_id=budget_id, user_id=user_id)

    mock_aggregate.approve.assert_called_once_with(user_id)
    assert isinstance(response, BudgetResponse)


@mark.asyncio
async def test_reject_budget(budget_service, mock_aggregate):
    budget_id = uuid4()
    user_id = uuid4()
    reason = "bad"
    with patch.object(budget_service, "_get_aggregate", AsyncMock(return_value=mock_aggregate)):
        with patch.object(budget_service, "_save_aggregate", AsyncMock(return_value=None)):
            with patch.object(budget_service, "_to_response", return_value=MagicMock(spec=BudgetResponse)):
                response = await budget_service.reject_budget(budget_id=budget_id, user_id=user_id, reason=reason)

    mock_aggregate.reject.assert_called_once_with(user_id, reason)
    assert isinstance(response, BudgetResponse)


@mark.asyncio
async def test_activate_budget(budget_service, mock_aggregate):
    budget_id = uuid4()
    user_id = uuid4()
    with patch.object(budget_service, "_get_aggregate", AsyncMock(return_value=mock_aggregate)):
        with patch.object(budget_service, "_save_aggregate", AsyncMock(return_value=None)):
            with patch.object(budget_service, "_to_response", return_value=MagicMock(spec=BudgetResponse)):
                response = await budget_service.activate_budget(budget_id=budget_id, user_id=user_id)

    mock_aggregate.activate.assert_called_once_with(user_id)
    assert isinstance(response, BudgetResponse)


@mark.asyncio
async def test_lock_budget(budget_service, mock_aggregate):
    budget_id = uuid4()
    user_id = uuid4()
    with patch.object(budget_service, "_get_aggregate", AsyncMock(return_value=mock_aggregate)):
        with patch.object(budget_service, "_save_aggregate", AsyncMock(return_value=None)):
            with patch.object(budget_service, "_to_response", return_value=MagicMock(spec=BudgetResponse)):
                response = await budget_service.lock_budget(budget_id=budget_id, user_id=user_id)

    mock_aggregate.lock.assert_called_once_with(user_id)
    assert isinstance(response, BudgetResponse)


@mark.asyncio
async def test_unlock_budget(budget_service, mock_aggregate):
    budget_id = uuid4()
    user_id = uuid4()
    with patch.object(budget_service, "_get_aggregate", AsyncMock(return_value=mock_aggregate)):
        with patch.object(budget_service, "_save_aggregate", AsyncMock(return_value=None)):
            with patch.object(budget_service, "_to_response", return_value=MagicMock(spec=BudgetResponse)):
                response = await budget_service.unlock_budget(budget_id=budget_id, user_id=user_id)

    mock_aggregate.unlock.assert_called_once_with(user_id)
    assert isinstance(response, BudgetResponse)


@mark.asyncio
async def test_archive_budget(budget_service, mock_aggregate):
    budget_id = uuid4()
    user_id = uuid4()
    with patch.object(budget_service, "_get_aggregate", AsyncMock(return_value=mock_aggregate)):
        with patch.object(budget_service, "_save_aggregate", AsyncMock(return_value=None)):
            with patch.object(budget_service, "_to_response", return_value=MagicMock(spec=BudgetResponse)):
                response = await budget_service.archive_budget(budget_id=budget_id, user_id=user_id)

    mock_aggregate.archive.assert_called_once_with(user_id)
    assert isinstance(response, BudgetResponse)


@mark.asyncio
async def test_cancel_budget(budget_service, mock_aggregate):
    budget_id = uuid4()
    user_id = uuid4()
    reason = "cancel"
    with patch.object(budget_service, "_get_aggregate", AsyncMock(return_value=mock_aggregate)):
        with patch.object(budget_service, "_save_aggregate", AsyncMock(return_value=None)):
            with patch.object(budget_service, "_to_response", return_value=MagicMock(spec=BudgetResponse)):
                response = await budget_service.cancel_budget(budget_id=budget_id, user_id=user_id, reason=reason)

    mock_aggregate.cancel.assert_called_once_with(user_id, reason)
    assert isinstance(response, BudgetResponse)


@mark.asyncio
async def test_close_budget(budget_service, mock_aggregate):
    budget_id = uuid4()
    user_id = uuid4()
    with patch.object(budget_service, "_get_aggregate", AsyncMock(return_value=mock_aggregate)):
        with patch.object(budget_service, "_save_aggregate", AsyncMock(return_value=None)):
            with patch.object(budget_service, "_to_response", return_value=MagicMock(spec=BudgetResponse)):
                response = await budget_service.close_budget(budget_id=budget_id, user_id=user_id)

    mock_aggregate.close.assert_called_once_with(user_id)
    assert isinstance(response, BudgetResponse)


# Line operations

@mark.asyncio
async def test_add_line(budget_service, mock_aggregate):
    request = BudgetLineCreateRequest(
        account_id=uuid4(),
        account_code="EXP-001",
        amount=Decimal("1000"),
        note="Expense"
    )
    budget_id = uuid4()
    user_id = uuid4()
    with patch.object(budget_service, "_get_aggregate", AsyncMock(return_value=mock_aggregate)):
        with patch.object(budget_service, "_save_aggregate", AsyncMock(return_value=None)):
            with patch.object(budget_service, "_to_response", return_value=MagicMock(spec=BudgetResponse)):
                response = await budget_service.add_line(budget_id=budget_id, request=request, user_id=user_id)

    mock_aggregate.add_line.assert_called_once_with(
        user_id=user_id,
        account_id=request.account_id,
        account_code=request.account_code,
        amount=request.amount,
        note=request.note,
    )
    assert isinstance(response, BudgetResponse)


@mark.asyncio
async def test_update_line(budget_service, mock_aggregate):
    request = BudgetLineUpdateRequest(
        line_id=uuid4(),
        amount=Decimal("2000"),
        note="Updated note"
    )
    budget_id = uuid4()
    user_id = uuid4()
    with patch.object(budget_service, "_get_aggregate", AsyncMock(return_value=mock_aggregate)):
        with patch.object(budget_service, "_save_aggregate", AsyncMock(return_value=None)):
            with patch.object(budget_service, "_to_response", return_value=MagicMock(spec=BudgetResponse)):
                response = await budget_service.update_line(budget_id=budget_id, request=request, user_id=user_id)

    mock_aggregate.update_line.assert_called_once_with(
        user_id=user_id,
        line_id=request.line_id,
        amount=request.amount,
        note=request.note,
    )
    assert isinstance(response, BudgetResponse)


@mark.asyncio
async def test_remove_line(budget_service, mock_aggregate):
    line_id = uuid4()
    budget_id = uuid4()
    user_id = uuid4()
    with patch.object(budget_service, "_get_aggregate", AsyncMock(return_value=mock_aggregate)):
        with patch.object(budget_service, "_save_aggregate", AsyncMock(return_value=None)):
            with patch.object(budget_service, "_to_response", return_value=MagicMock(spec=BudgetResponse)):
                response = await budget_service.remove_line(budget_id=budget_id, line_id=line_id, user_id=user_id)

    mock_aggregate.remove_line.assert_called_once_with(user_id=user_id, line_id=line_id)
    assert isinstance(response, BudgetResponse)


# Dashboard and other methods - simple smoke tests

@mark.asyncio
async def test_get_budget_dashboard(budget_service, mock_budget_repo, sample_budget_entity):
    mock_budget_repo.list_by_legal_entity = AsyncMock(return_value=[sample_budget_entity])
    result = await budget_service.get_budget_dashboard(legal_entity_id=uuid4(), as_of_date=date.today())
    assert isinstance(result, dict)
    assert "total_budgets" in result
    assert result["total_budgets"] == 1


@mark.asyncio
async def test_get_budget_alerts(budget_service, mock_budget_repo, sample_budget_entity):
    mock_budget_repo.list_by_legal_entity = AsyncMock(return_value=[sample_budget_entity])
    alerts = await budget_service.get_budget_alerts(legal_entity_id=uuid4())
    assert isinstance(alerts, list)
    # Since we don't have actual data, alerts will be empty because actual_amount = 0
    assert len(alerts) == 0


@mark.asyncio
async def test_get_budget_vs_actual(budget_service, mock_budget_repo, sample_budget_entity):
    mock_budget_repo.get_by_id = AsyncMock(return_value=sample_budget_entity)
    result = await budget_service.get_budget_vs_actual(
        budget_id=sample_budget_entity.id,
        legal_entity_id=uuid4(),
        period=1
    )
    assert result is not None
    assert result.budget_id == sample_budget_entity.id


@mark.asyncio
async def test_get_budget_vs_actual_not_found(budget_service, mock_budget_repo):
    mock_budget_repo.get_by_id = AsyncMock(return_value=None)
    result = await budget_service.get_budget_vs_actual(
        budget_id=uuid4(),
        legal_entity_id=uuid4(),
        period=1
    )
    assert result is None


@mark.asyncio
async def test_get_budget_vs_actual_ytd(budget_service, mock_budget_repo, sample_budget_entity):
    mock_budget_repo.get_by_id = AsyncMock(return_value=sample_budget_entity)
    result = await budget_service.get_budget_vs_actual_ytd(
        budget_id=sample_budget_entity.id,
        legal_entity_id=uuid4(),
        as_of_month=6
    )
    assert result is not None


@mark.asyncio
async def test_export_budgets(budget_service, mock_budget_repo, sample_budget_entity):
    mock_budget_repo.list_by_legal_entity = AsyncMock(return_value=[sample_budget_entity])
    csv_data = await budget_service.export_budgets(
        legal_entity_id=uuid4(),
        fiscal_year=2025,
        format="csv"
    )
    assert isinstance(csv_data, str)
    assert "Budget Code" in csv_data


def test_audit_trail(budget_service):
    # Initially empty
    assert budget_service.get_audit_trail() == []
    # Add an audit entry manually
    budget_service._record_audit("test", {"key": "value"})
    assert len(budget_service.get_audit_trail()) == 1


def test_audit_decorator():
    @audit
    def dummy():
        pass
    # Just ensure it doesn't raise
    dummy()


@mark.asyncio
async def test_create_budget_service(mock_budget_repo, mock_uow, mock_event_publisher, mock_ledger_repo):
    service = await create_budget_service(
        budget_repo=mock_budget_repo,
        uow=mock_uow,
        event_publisher=mock_event_publisher,
        ledger_repo=mock_ledger_repo,
    )
    assert isinstance(service, BudgetService)
