# tests/application/service_layer/test_service_approval.py
"""
Unit tests for ApprovalService (DB-backed version).

Covers all public methods of ApprovalService using a mocked
ApprovalRepositoryPort. No real database is used.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from pytest_mock import MockerFixture

from application.service_layer.service_approval import (
    ApprovalService,
    PaginatedResult,
    audit,
)


# =============================================================================
# Enum definitions
# =============================================================================

class ApprovalStatus:
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    ESCALATED = "escalated"
    RECALLED = "recalled"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ApprovalAction:
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    ESCALATED = "escalated"
    RECALLED = "recalled"
    CANCELLED = "cancelled"


# =============================================================================
# Mock Request Row with methods (all IDs stored as strings)
# =============================================================================

class MockRequestRow:
    """Mock object that mimics ApprovalRequestTable ORM row with methods.
    All UUID fields are stored as strings to match database behavior.
    """

    def __init__(
        self,
        request_id: UUID | str | None = None,
        request_number: str = "APR-20260101-ABC123",
        entity_type: str = "Journal",
        entity_id: UUID | str | None = None,
        amount: Decimal | None = Decimal("1000"),
        currency: str = "IDR",
        status: str = "pending",
        current_level: int = 1,
        approver_id: UUID | str | None = None,
        approver_name: str = "Approver",
        approver_role: str | None = "Manager",
        approval_matrix_id: UUID | str | None = None,
        requested_by: UUID | str | None = None,
        requester_name: str = "Requester",
        requester_comments: str | None = None,
        legal_entity_id: UUID | str | None = None,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
        approved_at: datetime | None = None,
        approved_by: UUID | str | None = None,
        cancelled_at: datetime | None = None,
        cancelled_by: UUID | str | None = None,
        escalated_at: datetime | None = None,
        escalated_to: UUID | str | None = None,
        deadline: date | None = None,
        approval_comments: str | None = None,
        cancellation_reason: str | None = None,
        is_overdue: bool = False,
        created_by: UUID | str | None = None,
        version: int = 1,
    ):
        # Convert all UUIDs to strings
        self.id = str(request_id) if request_id else str(uuid4())
        self.request_number = request_number
        self.entity_type = entity_type
        self.entity_id = str(entity_id) if entity_id else str(uuid4())
        self.entity_reference = f"{entity_type}-{uuid4().hex[:8]}"
        self.amount = amount
        self.currency = currency
        self.status = status
        self.current_level = current_level
        self.approver_id = str(approver_id) if approver_id else str(uuid4())
        self.approver_name = approver_name
        self.approver_role = approver_role
        self.approval_matrix_id = str(approval_matrix_id) if approval_matrix_id else str(uuid4())
        self.requested_by = str(requested_by) if requested_by else str(uuid4())
        self.requester_name = requester_name
        self.requester_comments = requester_comments
        self.legal_entity_id = str(legal_entity_id) if legal_entity_id else str(uuid4())
        self.created_at = created_at or datetime.now(UTC)
        self.updated_at = updated_at or datetime.now(UTC)
        self.approved_at = approved_at
        self.approved_by = str(approved_by) if approved_by else None
        self.cancelled_at = cancelled_at
        self.cancelled_by = str(cancelled_by) if cancelled_by else None
        self.escalated_at = escalated_at
        self.escalated_to = str(escalated_to) if escalated_to else None
        self.deadline = deadline
        self.approval_comments = approval_comments
        self.cancellation_reason = cancellation_reason
        self.is_overdue = is_overdue
        self.created_by = str(created_by) if created_by else str(uuid4())
        self.version = version

    def approve(self, approved_by: UUID | str, comments: str | None = None):
        self.status = ApprovalStatus.APPROVED
        self.approved_by = str(approved_by)
        self.approved_at = datetime.now(UTC)
        if comments:
            self.approval_comments = comments

    def reject(self, approved_by: UUID | str, comments: str | None = None):
        self.status = ApprovalStatus.REJECTED
        self.approved_by = str(approved_by)
        self.approved_at = datetime.now(UTC)
        if comments:
            self.approval_comments = comments

    def cancel(self, cancelled_by: UUID | str, reason: str | None = None):
        self.status = ApprovalStatus.CANCELLED
        self.cancelled_by = str(cancelled_by)
        self.cancelled_at = datetime.now(UTC)
        if reason:
            self.cancellation_reason = reason

    def recall(self, recalled_by: UUID | str, reason: str | None = None):
        self.status = ApprovalStatus.RECALLED
        self.cancelled_by = str(recalled_by)
        self.cancelled_at = datetime.now(UTC)
        if reason:
            self.cancellation_reason = reason

    def escalate(self, escalated_to: UUID | str, reason: str | None = None, level: int | None = None, **kwargs):
        self.status = ApprovalStatus.ESCALATED
        self.escalated_to = str(escalated_to)
        self.escalated_at = datetime.now(UTC)
        if level is not None:
            self.current_level = level
        elif "current_level" in kwargs:
            self.current_level = kwargs["current_level"]
        else:
            self.current_level += 1
        if reason:
            self.approval_comments = reason

    def increment_version(self):
        self.version += 1


# =============================================================================
# Mock Matrix Row with methods (all IDs as strings)
# =============================================================================

class MockMatrixRow:
    """Mock object that mimics ApprovalMatrixTable ORM row with methods."""

    def __init__(
        self,
        matrix_id: UUID | str | None = None,
        matrix_code: str = "MAT-001",
        matrix_name: str = "Test Matrix",
        entity_type: str = "Journal",
        min_amount: Decimal | None = Decimal("0"),
        max_amount: Decimal | None = Decimal("1000000"),
        currency: str = "IDR",
        rules: list[dict] | None = None,
        is_active: bool = True,
        notes: str | None = None,
        legal_entity_id: UUID | str | None = None,
        created_by: UUID | str | None = None,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
        version: int = 1,
    ):
        self.id = str(matrix_id) if matrix_id else str(uuid4())
        self.matrix_code = matrix_code
        self.matrix_name = matrix_name
        self.entity_type = entity_type
        self.min_amount = min_amount
        self.max_amount = max_amount
        self.currency = currency
        self.rules = rules or [{"level": 1, "approver_id": str(uuid4()), "approver_name": "Manager"}]
        self.is_active = is_active
        self.notes = notes
        self.legal_entity_id = str(legal_entity_id) if legal_entity_id else str(uuid4())
        self.created_by = str(created_by) if created_by else str(uuid4())
        self.created_by_name = None
        self.created_at = created_at or datetime.now(UTC)
        self.updated_at = updated_at or datetime.now(UTC)
        self.version = version

    def increment_version(self):
        self.version += 1


# =============================================================================
# Mock Delegation Row with methods (all IDs as strings)
# =============================================================================

class MockDelegationRow:
    """Mock object that mimics ApprovalDelegationTable ORM row with methods."""

    def __init__(
        self,
        delegation_id: UUID | str | None = None,
        delegator_id: UUID | str | None = None,
        delegate_to_id: UUID | str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        reason: str | None = None,
        is_active: bool = True,
        legal_entity_id: UUID | str | None = None,
        created_by: UUID | str | None = None,
        created_at: datetime | None = None,
        revoked_by: UUID | str | None = None,
        revoked_at: datetime | None = None,
        version: int = 1,
    ):
        self.id = str(delegation_id) if delegation_id else str(uuid4())
        self.delegator_id = str(delegator_id) if delegator_id else str(uuid4())
        self.delegator_name = None
        self.delegate_to_id = str(delegate_to_id) if delegate_to_id else str(uuid4())
        self.delegate_to_name = None
        self.start_date = start_date or date.today()
        self.end_date = end_date or date.today().replace(year=date.today().year + 1)
        self.reason = reason
        self.is_active = is_active
        self.legal_entity_id = str(legal_entity_id) if legal_entity_id else str(uuid4())
        self.created_by = str(created_by) if created_by else str(uuid4())
        self.created_at = created_at or datetime.now(UTC)
        self.revoked_by = str(revoked_by) if revoked_by else None
        self.revoked_at = revoked_at
        self.version = version

    def increment_version(self):
        self.version += 1


# =============================================================================
# Helper: create mock rows
# =============================================================================

def mock_request_row(**kwargs) -> MockRequestRow:
    return MockRequestRow(**kwargs)


def mock_matrix_row(**kwargs) -> MockMatrixRow:
    return MockMatrixRow(**kwargs)


def mock_delegation_row(**kwargs) -> MockDelegationRow:
    return MockDelegationRow(**kwargs)


# =============================================================================
# Fixture: Mock ApprovalRepositoryPort
# =============================================================================

@pytest.fixture
def mock_repo(mocker: MockerFixture):
    repo = mocker.MagicMock()

    # Default behaviors for common methods
    # We use return_value so tests can override
    repo.save_request = mocker.AsyncMock(return_value=mock_request_row())
    repo.get_request_by_id = mocker.AsyncMock(return_value=None)
    repo.get_request_by_number = mocker.AsyncMock(return_value=None)
    repo.list_requests = mocker.AsyncMock(return_value=([], 0))
    repo.get_pending_requests_for_user = mocker.AsyncMock(return_value=[])
    repo.get_requests_by_entity = mocker.AsyncMock(return_value=[])

    repo.save_matrix = mocker.AsyncMock(return_value=mock_matrix_row())
    repo.get_matrix_by_id = mocker.AsyncMock(return_value=None)
    repo.list_matrices = mocker.AsyncMock(return_value=[])
    repo.delete_matrix = mocker.AsyncMock(return_value=True)

    repo.save_delegation = mocker.AsyncMock(return_value=mock_delegation_row())
    repo.get_delegation_by_id = mocker.AsyncMock(return_value=None)
    repo.list_delegations_by_delegator = mocker.AsyncMock(return_value=[])

    repo.get_statistics = mocker.AsyncMock(return_value={
        "total": 10,
        "pending": 5,
        "approved": 3,
        "rejected": 1,
        "escalated": 1,
        "avg_approval_time_hours": 12.5,
    })

    return repo


@pytest.fixture
def service(mock_repo) -> ApprovalService:
    return ApprovalService(approval_repo=mock_repo)


# =============================================================================
# Tests for PaginatedResult
# =============================================================================

class TestPaginatedResult:
    def test_construction(self):
        items = [1, 2, 3]
        result = PaginatedResult(items=items, total=25, page=3, page_size=10)
        assert result.items == items
        assert result.total == 25
        assert result.page == 3
        assert result.page_size == 10

    def test_total_pages(self):
        result = PaginatedResult(items=[], total=25, page=1, page_size=10)
        assert result.total_pages == 3
        result2 = PaginatedResult(items=[], total=0, page=1, page_size=10)
        assert result2.total_pages == 0
        result3 = PaginatedResult(items=[], total=10, page=1, page_size=0)
        assert result3.total_pages == 0

    def test_has_next(self):
        result = PaginatedResult(items=[], total=25, page=1, page_size=10)
        assert result.has_next() is True
        result2 = PaginatedResult(items=[], total=25, page=3, page_size=10)
        assert result2.has_next() is False

    def test_has_prev(self):
        result = PaginatedResult(items=[], total=25, page=2, page_size=10)
        assert result.has_prev() is True
        result2 = PaginatedResult(items=[], total=25, page=1, page_size=10)
        assert result2.has_prev() is False


# =============================================================================
# Tests for ApprovalService
# =============================================================================

@pytest.mark.asyncio
class TestApprovalService:
    async def test_submit_approval_success(self, service, mock_repo):
        matrix_id = str(uuid4())
        approver_id = str(uuid4())
        legal_entity_id = str(uuid4())
        matrix_row = mock_matrix_row(
            matrix_id=matrix_id,
            legal_entity_id=legal_entity_id,
            matrix_name="Test Matrix",
            rules=[{"level": 1, "approver_id": approver_id, "approver_name": "Manager"}],
        )
        mock_repo.get_matrix_by_id.return_value = matrix_row

        # Explicitly set save_request return value to our custom row
        submitted_row = mock_request_row(
            approval_matrix_id=matrix_id,
            approver_id=approver_id,
            approver_name="Manager",
            current_level=1,
            status=ApprovalStatus.PENDING,
            legal_entity_id=legal_entity_id,
        )
        mock_repo.save_request.return_value = submitted_row

        result = await service.submit_approval(
            entity_type="Journal",
            entity_id=uuid4(),
            approval_matrix_id=matrix_id,
            requester_id=uuid4(),
            legal_entity_id=legal_entity_id,
            amount=Decimal("1000"),
            notes="Test",
        )

        assert result is not None
        assert result.status == ApprovalStatus.PENDING
        assert result.current_level == 1
        assert result.current_approver_id == approver_id
        assert result.current_approver_name == "Manager"
        assert result.approval_matrix_id == matrix_id
        mock_repo.get_matrix_by_id.assert_called_once_with(matrix_id, result.legal_entity_id)
        mock_repo.save_request.assert_called_once()

    async def test_submit_approval_matrix_not_found(self, service, mock_repo):
        mock_repo.get_matrix_by_id.return_value = None

        with pytest.raises(ValueError, match="Approval matrix .* not found"):
            await service.submit_approval(
                entity_type="Journal",
                entity_id=uuid4(),
                approval_matrix_id=str(uuid4()),
                requester_id=uuid4(),
                legal_entity_id=str(uuid4()),
            )

    async def test_submit_approval_no_level1_rule(self, service, mock_repo):
        matrix_row = mock_matrix_row(rules=[{"level": 2, "approver_id": str(uuid4())}])
        mock_repo.get_matrix_by_id.return_value = matrix_row

        with pytest.raises(ValueError, match="Matrix .* has no level-1 rule defined"):
            await service.submit_approval(
                entity_type="Journal",
                entity_id=uuid4(),
                approval_matrix_id=str(uuid4()),
                requester_id=uuid4(),
                legal_entity_id=str(uuid4()),
            )

    async def test_list_approval_requests(self, service, mock_repo):
        test_legal_entity_id = str(uuid4())
        mock_repo.list_requests.return_value = ([mock_request_row(legal_entity_id=test_legal_entity_id, status="pending")], 1)

        result = await service.list_approval_requests(
            legal_entity_id=test_legal_entity_id,
            entity_type="Journal",
            status="pending",
            page=2,
            page_size=10,
        )

        assert result.total == 1
        assert len(result.items) == 1
        assert result.page == 2
        assert result.page_size == 10
        mock_repo.list_requests.assert_called_once_with(
            legal_entity_id=test_legal_entity_id,
            entity_type="Journal",
            status="pending",
            requester_id=None,
            start_date=None,
            end_date=None,
            page=2,
            page_size=10,
        )

    async def test_get_approval_request_by_id(self, service, mock_repo):
        row = mock_request_row()
        mock_repo.get_request_by_id.return_value = row

        result = await service.get_approval_request(row.id, row.legal_entity_id)
        assert result is not None
        assert result.id == row.id
        assert result.status == row.status

        result2 = await service.get_approval_request(row.id, str(uuid4()))
        assert result2 is None

    async def test_get_approval_request_by_number(self, service, mock_repo):
        row = mock_request_row(request_number="APR-123")
        mock_repo.get_request_by_number.return_value = row

        result = await service.get_approval_request_by_number("APR-123", row.legal_entity_id)
        assert result is not None
        assert result.request_number == "APR-123"

    async def test_recall_approval_success(self, service, mock_repo):
        requester_id = str(uuid4())
        row = mock_request_row(requested_by=requester_id, status=ApprovalStatus.PENDING)
        mock_repo.get_request_by_id.return_value = row

        result = await service.recall_approval(row.id, requester_id, row.legal_entity_id)

        assert result is not None
        assert result.status in (ApprovalStatus.CANCELLED, ApprovalStatus.RECALLED)
        mock_repo.save_request.assert_not_called()

    async def test_recall_approval_wrong_user(self, service, mock_repo):
        requester_id = str(uuid4())
        row = mock_request_row(requested_by=str(uuid4()), status=ApprovalStatus.PENDING)
        mock_repo.get_request_by_id.return_value = row

        with pytest.raises(ValueError, match="Only requester can recall approval"):
            await service.recall_approval(row.id, requester_id, row.legal_entity_id)

    async def test_recall_approval_not_pending(self, service, mock_repo):
        requester_id = str(uuid4())
        row = mock_request_row(requested_by=requester_id, status=ApprovalStatus.APPROVED)
        mock_repo.get_request_by_id.return_value = row

        with pytest.raises(ValueError, match="Cannot recall request with status approved"):
            await service.recall_approval(row.id, requester_id, row.legal_entity_id)

    async def test_cancel_approval(self, service, mock_repo):
        row = mock_request_row(status=ApprovalStatus.PENDING)
        mock_repo.get_request_by_id.return_value = row

        result = await service.cancel_approval(row.id, str(uuid4()), row.legal_entity_id, reason="Test cancel")
        assert result is not None
        assert result.status == ApprovalStatus.CANCELLED
        mock_repo.save_request.assert_not_called()

    async def test_process_approval_approve(self, service, mock_repo):
        row = mock_request_row(status=ApprovalStatus.PENDING)
        mock_repo.get_request_by_id.return_value = row

        actor_id = str(uuid4())
        result = await service.process_approval_action(
            request_id=row.id,
            action="approve",
            actor_id=actor_id,
            legal_entity_id=row.legal_entity_id,
            notes="OK",
        )
        assert result is not None
        assert result.status == ApprovalStatus.APPROVED
        mock_repo.save_request.assert_not_called()

    async def test_process_approval_reject(self, service, mock_repo):
        row = mock_request_row(status=ApprovalStatus.PENDING)
        mock_repo.get_request_by_id.return_value = row

        result = await service.process_approval_action(
            request_id=row.id,
            action="reject",
            actor_id=str(uuid4()),
            legal_entity_id=row.legal_entity_id,
            notes="Rejected",
        )
        assert result is not None
        assert result.status == ApprovalStatus.REJECTED
        mock_repo.save_request.assert_not_called()

    async def test_process_approval_escalate(self, service, mock_repo):
        matrix_id = str(uuid4())
        approver_id = str(uuid4())
        matrix_row = mock_matrix_row(
            matrix_id=matrix_id,
            matrix_name="Test Matrix",
            rules=[
                {"level": 1, "approver_id": str(uuid4())},
                {"level": 2, "approver_id": approver_id, "approver_name": "Director"},
            ],
        )
        # Service may call get_matrix_by_id multiple times (once for resolving approver, once for matrix name)
        mock_repo.get_matrix_by_id.return_value = matrix_row

        row = mock_request_row(
            status=ApprovalStatus.PENDING,
            current_level=1,
            approval_matrix_id=matrix_id,
        )
        mock_repo.get_request_by_id.return_value = row

        result = await service.process_approval_action(
            request_id=row.id,
            action="escalate",
            actor_id=str(uuid4()),
            legal_entity_id=row.legal_entity_id,
            escalation_level=2,
        )
        assert result is not None
        assert result.current_level == 2
        assert result.current_approver_id == approver_id
        mock_repo.get_matrix_by_id.assert_called_with(matrix_id, row.legal_entity_id)
        mock_repo.save_request.assert_not_called()

    async def test_process_approval_delegate(self, service, mock_repo):
        delegate_to = str(uuid4())
        row = mock_request_row(status=ApprovalStatus.PENDING)
        mock_repo.get_request_by_id.return_value = row

        result = await service.process_approval_action(
            request_id=row.id,
            action="delegate",
            actor_id=str(uuid4()),
            legal_entity_id=row.legal_entity_id,
            delegate_to_user_id=delegate_to,
        )
        assert result is not None
        assert result.current_approver_id == delegate_to
        mock_repo.save_request.assert_not_called()

    async def test_process_approval_unknown_action(self, service, mock_repo):
        row = mock_request_row(status=ApprovalStatus.PENDING)
        mock_repo.get_request_by_id.return_value = row

        with pytest.raises(ValueError, match="Unknown action: unknown"):
            await service.process_approval_action(
                request_id=row.id,
                action="unknown",
                actor_id=str(uuid4()),
                legal_entity_id=row.legal_entity_id,
            )

    async def test_get_pending_tasks_for_user(self, service, mock_repo):
        test_legal_entity_id = str(uuid4())
        rows = [
            mock_request_row(
                status=ApprovalStatus.PENDING,
                entity_type="Journal",
                legal_entity_id=test_legal_entity_id,
                is_overdue=True
            )
            for _ in range(3)
        ]
        mock_repo.get_pending_requests_for_user.return_value = rows

        user_id = str(uuid4())

        result = await service.get_pending_tasks_for_user(user_id, legal_entity_id=test_legal_entity_id)
        assert len(result) == 3

        result2 = await service.get_pending_tasks_for_user(user_id, entity_type="Journal")
        assert len(result2) == 3

        result3 = await service.get_pending_tasks_for_user(user_id, overdue_only=True)
        assert len(result3) == 3

    async def test_get_pending_tasks_count(self, service, mock_repo):
        test_legal_entity_id = str(uuid4())
        rows = [
            mock_request_row(status=ApprovalStatus.PENDING, entity_type="Journal", legal_entity_id=test_legal_entity_id),
            mock_request_row(status=ApprovalStatus.PENDING, entity_type="Journal", legal_entity_id=test_legal_entity_id),
            mock_request_row(status=ApprovalStatus.PENDING, entity_type="PurchaseOrder", legal_entity_id=test_legal_entity_id),
        ]
        mock_repo.get_pending_requests_for_user.return_value = rows

        user_id = str(uuid4())
        result = await service.get_pending_tasks_count(user_id, legal_entity_id=test_legal_entity_id)
        assert result.total == 3
        assert result.by_entity_type == {"Journal": 2, "PurchaseOrder": 1}
        assert result.overdue == 0

    async def test_get_approval_history_synthetic(self, service, mock_repo):
        row = mock_request_row(
            status=ApprovalStatus.APPROVED,
            created_at=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
            approved_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
            approved_by=str(uuid4()),
            requester_comments="Initial",
            approval_comments="Approved",
        )
        mock_repo.get_request_by_id.return_value = row

        history = await service.get_approval_history(row.id, row.legal_entity_id)
        assert len(history) == 2
        assert history[0].action == ApprovalAction.SUBMITTED
        assert history[1].action == ApprovalAction.APPROVED

        row2 = mock_request_row(status=ApprovalStatus.CANCELLED, cancelled_at=datetime.now(UTC))
        mock_repo.get_request_by_id.return_value = row2
        history2 = await service.get_approval_history(row2.id)
        assert len(history2) == 2

        row3 = mock_request_row(
            status=ApprovalStatus.PENDING,
            current_level=2,
            escalated_at=datetime.now(UTC),
        )
        mock_repo.get_request_by_id.return_value = row3
        history3 = await service.get_approval_history(row3.id)
        assert len(history3) == 2

    async def test_get_entity_approval_status(self, service, mock_repo):
        row = mock_request_row(status=ApprovalStatus.APPROVED)
        mock_repo.get_requests_by_entity.return_value = [row]

        result = await service.get_entity_approval_status("Journal", row.entity_id, row.legal_entity_id)
        assert result is not None
        assert result.status == ApprovalStatus.APPROVED

        mock_repo.get_requests_by_entity.return_value = []
        result2 = await service.get_entity_approval_status("Journal", str(uuid4()), str(uuid4()))
        assert result2 is None

    # --------------------- Matrix Tests ---------------------
    async def test_create_approval_matrix(self, service, mock_repo):
        created = mock_matrix_row(matrix_code="MAT-001")
        mock_repo.save_matrix.return_value = created

        result = await service.create_approval_matrix(
            matrix_code="MAT-001",
            matrix_name="Test",
            entity_type="Journal",
            min_amount=Decimal("0"),
            max_amount=Decimal("1000"),
            currency="IDR",
            rules=[{"level": 1, "approver_id": str(uuid4())}],
            is_active=True,
            notes="Test",
            created_by=str(uuid4()),
            legal_entity_id=str(uuid4()),
        )
        assert result is not None
        assert result.matrix_code == "MAT-001"
        mock_repo.save_matrix.assert_called_once()

    async def test_list_approval_matrices(self, service, mock_repo):
        mock_repo.list_matrices.return_value = [mock_matrix_row(), mock_matrix_row()]

        result = await service.list_approval_matrices(str(uuid4()), entity_type="Journal", is_active=True)
        assert len(result) == 2
        mock_repo.list_matrices.assert_called_once()

    async def test_get_approval_matrix(self, service, mock_repo):
        matrix = mock_matrix_row()
        mock_repo.get_matrix_by_id.return_value = matrix

        result = await service.get_approval_matrix(matrix.id, matrix.legal_entity_id)
        assert result is not None
        assert result.id == matrix.id

    async def test_update_approval_matrix(self, service, mock_repo):
        matrix = mock_matrix_row(matrix_name="Old")
        mock_repo.get_matrix_by_id.return_value = matrix

        result = await service.update_approval_matrix(
            matrix_id=matrix.id,
            matrix_name="New Name",
            legal_entity_id=matrix.legal_entity_id,
        )
        assert result is not None
        assert result.matrix_name == "New Name"

    async def test_delete_approval_matrix(self, service, mock_repo):
        mock_repo.delete_matrix.return_value = True
        result = await service.delete_approval_matrix(str(uuid4()), str(uuid4()), str(uuid4()))
        assert result is True
        mock_repo.delete_matrix.assert_called_once()

    async def test_deactivate_approval_matrix(self, service, mock_repo):
        matrix = mock_matrix_row(is_active=True)
        mock_repo.get_matrix_by_id.return_value = matrix

        result = await service.deactivate_approval_matrix(matrix.id, matrix.legal_entity_id, str(uuid4()))
        assert result is True
        assert matrix.is_active is False
        assert matrix.version == 2

    # --------------------- Delegation Tests ---------------------
    async def test_create_delegation(self, service, mock_repo):
        delegation = mock_delegation_row()
        mock_repo.save_delegation.return_value = delegation

        result = await service.create_delegation(
            delegator_id=str(uuid4()),
            delegate_to_id=str(uuid4()),
            start_date=date.today(),
            end_date=date.today().replace(year=date.today().year + 1),
            reason="Test",
            legal_entity_id=str(uuid4()),
        )
        assert result is not None
        assert result.id == delegation.id
        mock_repo.save_delegation.assert_called_once()

    async def test_create_delegation_invalid_dates(self, service):
        with pytest.raises(ValueError, match="end_date must be on or after start_date"):
            await service.create_delegation(
                delegator_id=str(uuid4()),
                delegate_to_id=str(uuid4()),
                start_date=date(2026, 1, 1),
                end_date=date(2025, 12, 31),
                reason="Invalid",
                legal_entity_id=str(uuid4()),
            )

    async def test_list_delegations(self, service, mock_repo):
        mock_repo.list_delegations_by_delegator.return_value = [mock_delegation_row(), mock_delegation_row()]

        result = await service.list_delegations(str(uuid4()), str(uuid4()), is_active=True)
        assert len(result) == 2

    async def test_revoke_delegation(self, service, mock_repo):
        delegation = mock_delegation_row()
        mock_repo.get_delegation_by_id.return_value = delegation

        result = await service.revoke_delegation(delegation.id, str(uuid4()), delegation.legal_entity_id)
        assert result is True
        assert delegation.is_active is False
        assert delegation.version == 2

    # --------------------- Statistics ---------------------
    async def test_get_approval_statistics(self, service, mock_repo):
        stats = await service.get_approval_statistics(
            legal_entity_id=str(uuid4()),
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            entity_type="Journal",
        )
        assert stats.total == 10
        assert stats.pending == 5
        assert stats.approved == 3

    # --------------------- Export ---------------------
    async def test_export_approval_requests_csv(self, service, mock_repo):
        mock_repo.list_requests.return_value = (
            [mock_request_row(request_number="APR-1"), mock_request_row(request_number="APR-2")],
            2,
        )

        data = await service.export_approval_requests(
            legal_entity_id=str(uuid4()),
            start_date=date(2026, 1, 1),
            format="csv",
        )
        assert isinstance(data, bytes)
        assert b"request_number" in data
        assert b"APR-1" in data

    async def test_export_approval_requests_unsupported_format(self, service):
        with pytest.raises(ValueError, match="Unsupported export format: pdf"):
            await service.export_approval_requests(
                legal_entity_id=str(uuid4()),
                format="pdf",
            )


# =============================================================================
# Test for audit decorator
# =============================================================================

def test_audit_decorator():
    @audit
    def test_func():
        return "ok"
    assert test_func() == "ok"


# =============================================================================
# Test for __all__ exports
# =============================================================================

def test_exports():
    from application.service_layer.service_approval import __all__
    expected = ["ApprovalService", "PaginatedResult", "audit"]
    assert set(__all__) == set(expected)