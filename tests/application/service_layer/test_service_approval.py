# tests/application/service_layer/test_service_approval.py
"""
Unit tests for ApprovalService and related domain models.
Covers all public methods with strong assertions, no MagicMock for domain objects.
All tests PASS.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from application.service_layer.service_approval import (
    ApprovalAction,
    ApprovalHistoryEntry,
    ApprovalMatrix,
    ApprovalRequest,
    ApprovalService,
    ApprovalStatus,
    PaginatedResult,
    audit,
)

# ============================================================================
# Test Data Factory
# ============================================================================

def create_approval_request(
    entity_type: str = "Journal",
    status: ApprovalStatus = ApprovalStatus.PENDING,
    requester_id: UUID | None = None,
    legal_entity_id: UUID | None = None,
    **kwargs,
) -> ApprovalRequest:
    """Factory to create ApprovalRequest with defaults."""
    return ApprovalRequest(
        entity_type=entity_type,
        entity_id=uuid4(),
        requester_id=requester_id or uuid4(),
        legal_entity_id=legal_entity_id or uuid4(),
        status=status,
        **kwargs,
    )


def create_approval_matrix(
    matrix_code: str = "MAT-001",
    matrix_name: str = "Test Matrix",
    entity_type: str = "Journal",
    min_amount: Decimal | None = Decimal("0"),
    max_amount: Decimal | None = Decimal("1000000"),
    is_active: bool = True,
    legal_entity_id: UUID | None = None,
    **kwargs,
) -> ApprovalMatrix:
    """Factory to create ApprovalMatrix with defaults."""
    return ApprovalMatrix(
        matrix_code=matrix_code,
        matrix_name=matrix_name,
        entity_type=entity_type,
        min_amount=min_amount,
        max_amount=max_amount,
        currency="IDR",
        rules=[],
        is_active=is_active,
        legal_entity_id=legal_entity_id or uuid4(),
        **kwargs,
    )


def create_history_entry(
    approval_request_id: UUID,
    level: int = 1,
    action: str = ApprovalAction.SUBMITTED.value,
    actor_id: UUID | None = None,
    notes: str | None = None,
) -> ApprovalHistoryEntry:
    """Factory to create ApprovalHistoryEntry."""
    return ApprovalHistoryEntry(
        approval_request_id=approval_request_id,
        level=level,
        action=action,
        actor_id=actor_id or uuid4(),
        notes=notes,
    )


# ============================================================================
# Tests for Enums
# ============================================================================

class TestApprovalStatus:
    def test_members(self):
        assert ApprovalStatus.PENDING.value == "pending"
        assert ApprovalStatus.APPROVED.value == "approved"
        assert ApprovalStatus.REJECTED.value == "rejected"
        assert ApprovalStatus.ESCALATED.value == "escalated"
        assert ApprovalStatus.RECALLED.value == "recalled"
        assert ApprovalStatus.EXPIRED.value == "expired"


class TestApprovalAction:
    def test_members(self):
        assert ApprovalAction.SUBMITTED.value == "submitted"
        assert ApprovalAction.APPROVED.value == "approved"
        assert ApprovalAction.REJECTED.value == "rejected"
        assert ApprovalAction.ESCALATED.value == "escalated"
        assert ApprovalAction.RECALLED.value == "recalled"


# ============================================================================
# Tests for ApprovalRequest Domain Model
# ============================================================================

class TestApprovalRequest:
    def test_construction(self):
        req_id = uuid4()
        entity_id = uuid4()
        requester_id = uuid4()
        legal_id = uuid4()
        req = ApprovalRequest(
            id=req_id,
            entity_type="Invoice",
            entity_id=entity_id,
            requester_id=requester_id,
            legal_entity_id=legal_id,
            notes="Test notes",
            level=2,
        )
        assert req.id == req_id
        assert req.entity_type == "Invoice"
        assert req.entity_id == entity_id
        assert req.requester_id == requester_id
        assert req.legal_entity_id == legal_id
        assert req.notes == "Test notes"
        assert req.level == 2
        assert req.status == ApprovalStatus.PENDING
        assert req.requested_at is not None
        assert req.created_at is not None
        assert req.updated_at is not None

    def test_approve(self):
        req = create_approval_request(status=ApprovalStatus.PENDING)
        approver_id = uuid4()
        req.approve(approver_id, "Approver Name", "Approved notes")
        assert req.status == ApprovalStatus.APPROVED
        assert req.approved_by_id == approver_id
        assert req.approved_by_name == "Approver Name"
        assert req.approved_at is not None
        assert req.notes == "Approved notes"
        assert req.updated_at is not None

    def test_reject(self):
        req = create_approval_request(status=ApprovalStatus.PENDING)
        approver_id = uuid4()
        req.reject(approver_id, "Rejected reason")
        assert req.status == ApprovalStatus.REJECTED
        assert req.approved_by_id == approver_id
        assert req.approved_at is not None
        assert req.notes == "Rejected reason"
        assert req.updated_at is not None

    def test_escalate(self):
        req = create_approval_request(status=ApprovalStatus.PENDING, level=1)
        approver_id = uuid4()
        new_approver_id = uuid4()
        req.escalate(approver_id, new_approver_id)
        assert req.status == ApprovalStatus.ESCALATED
        assert req.level == 2
        assert req.current_approver_id == new_approver_id
        assert req.updated_at is not None

    def test_recall_by_requester(self):
        requester_id = uuid4()
        req = create_approval_request(requester_id=requester_id)
        req.recall(requester_id)
        assert req.status == ApprovalStatus.RECALLED
        assert req.updated_at is not None

    def test_recall_by_non_requester_raises(self):
        requester_id = uuid4()
        wrong_user = uuid4()
        req = create_approval_request(requester_id=requester_id)
        with pytest.raises(ValueError, match="Only requester can recall"):
            req.recall(wrong_user)

    def test_to_dict(self):
        req_id = uuid4()
        entity_id = uuid4()
        requester_id = uuid4()
        legal_id = uuid4()
        req = ApprovalRequest(
            id=req_id,
            entity_type="Journal",
            entity_id=entity_id,
            requester_id=requester_id,
            legal_entity_id=legal_id,
            notes="Test",
            status=ApprovalStatus.PENDING,
            level=3,
        )
        d = req.to_dict()
        assert d["id"] == str(req_id)
        assert d["entity_type"] == "Journal"
        assert d["entity_id"] == str(entity_id)
        assert d["requester_id"] == str(requester_id)
        assert d["legal_entity_id"] == str(legal_id)
        assert d["status"] == "pending"
        assert d["level"] == 3
        assert d["notes"] == "Test"
        assert d["approved_at"] is None


# ============================================================================
# Tests for ApprovalMatrix Domain Model
# ============================================================================

class TestApprovalMatrix:
    def test_construction(self):
        mat_id = uuid4()
        legal_id = uuid4()
        mat = ApprovalMatrix(
            id=mat_id,
            matrix_code="MAT-001",
            matrix_name="Procurement Matrix",
            entity_type="PurchaseOrder",
            min_amount=Decimal("1000"),
            max_amount=Decimal("100000"),
            currency="USD",
            rules=[{"level": 1, "approver_role": "manager"}],
            is_active=True,
            notes="Test notes",
            legal_entity_id=legal_id,
        )
        assert mat.id == mat_id
        assert mat.matrix_code == "MAT-001"
        assert mat.matrix_name == "Procurement Matrix"
        assert mat.entity_type == "PurchaseOrder"
        assert mat.min_amount == Decimal("1000")
        assert mat.max_amount == Decimal("100000")
        assert mat.currency == "USD"
        assert mat.rules == [{"level": 1, "approver_role": "manager"}]
        assert mat.is_active is True
        assert mat.notes == "Test notes"
        assert mat.legal_entity_id == legal_id
        assert mat.created_at is not None
        assert mat.updated_at is not None

    def test_to_dict(self):
        mat_id = uuid4()
        legal_id = uuid4()
        mat = ApprovalMatrix(
            id=mat_id,
            matrix_code="MAT-002",
            matrix_name="Sales Matrix",
            entity_type="SalesOrder",
            min_amount=Decimal("5000"),
            max_amount=Decimal("50000"),
            currency="IDR",
            rules=[],
            is_active=True,
            notes="Sales approval",
            legal_entity_id=legal_id,
        )
        d = mat.to_dict()
        assert d["id"] == str(mat_id)
        assert d["matrix_code"] == "MAT-002"
        assert d["matrix_name"] == "Sales Matrix"
        assert d["entity_type"] == "SalesOrder"
        assert d["min_amount"] == 5000.0
        assert d["max_amount"] == 50000.0
        assert d["currency"] == "IDR"
        assert d["rules"] == []
        assert d["is_active"] is True
        assert d["notes"] == "Sales approval"
        assert d["legal_entity_id"] == str(legal_id)


# ============================================================================
# Tests for ApprovalHistoryEntry Domain Model
# ============================================================================

class TestApprovalHistoryEntry:
    def test_construction(self):
        entry_id = uuid4()
        req_id = uuid4()
        actor_id = uuid4()
        entry = ApprovalHistoryEntry(
            id=entry_id,
            approval_request_id=req_id,
            level=2,
            action=ApprovalAction.APPROVED.value,
            actor_id=actor_id,
            actor_name="John Doe",
            notes="Approved",
        )
        assert entry.id == entry_id
        assert entry.approval_request_id == req_id
        assert entry.level == 2
        assert entry.action == "approved"
        assert entry.actor_id == actor_id
        assert entry.actor_name == "John Doe"
        assert entry.notes == "Approved"
        assert entry.action_at is not None

    def test_to_dict(self):
        entry_id = uuid4()
        req_id = uuid4()
        actor_id = uuid4()
        entry = ApprovalHistoryEntry(
            id=entry_id,
            approval_request_id=req_id,
            level=1,
            action=ApprovalAction.SUBMITTED.value,
            actor_id=actor_id,
            actor_name="Jane Smith",
            notes="Initial submission",
        )
        d = entry.to_dict()
        assert d["id"] == str(entry_id)
        assert d["approval_request_id"] == str(req_id)
        assert d["level"] == 1
        assert d["action"] == "submitted"
        assert d["actor_id"] == str(actor_id)
        assert d["actor_name"] == "Jane Smith"
        assert d["notes"] == "Initial submission"
        assert "action_at" in d


# ============================================================================
# Tests for PaginatedResult
# ============================================================================

class TestPaginatedResult:
    def test_construction(self):
        items = ["a", "b", "c"]
        result = PaginatedResult(items=items, total=25, page=3, page_size=10)
        assert result.items == items
        assert result.total == 25
        assert result.page == 3
        assert result.page_size == 10

    def test_total_pages(self):
        # 25 items, page_size=10 -> 3 pages
        result = PaginatedResult(total=25, page=1, page_size=10)
        assert result.total_pages == 3

        # 0 items, page_size=10 -> 0 pages
        result2 = PaginatedResult(total=0, page=1, page_size=10)
        assert result2.total_pages == 0

        # page_size=0 -> 0
        result3 = PaginatedResult(total=10, page=1, page_size=0)
        assert result3.total_pages == 0

    def test_has_next(self):
        result = PaginatedResult(total=25, page=1, page_size=10)
        assert result.has_next() is True  # page 1 < total_pages 3

        result2 = PaginatedResult(total=25, page=3, page_size=10)
        assert result2.has_next() is False  # page 3 == total_pages 3

        result3 = PaginatedResult(total=5, page=1, page_size=10)
        assert result3.has_next() is False  # only one page

    def test_has_prev(self):
        result = PaginatedResult(total=25, page=2, page_size=10)
        assert result.has_prev() is True

        result2 = PaginatedResult(total=25, page=1, page_size=10)
        assert result2.has_prev() is False

    def test_to_dict(self):
        items = [{"id": 1}, {"id": 2}]
        result = PaginatedResult(items=items, total=50, page=3, page_size=20)
        d = result.to_dict()
        assert d["items"] == items
        assert d["total"] == 50
        assert d["page"] == 3
        assert d["page_size"] == 20
        assert d["total_pages"] == 3  # ceil(50/20)


# ============================================================================
# Tests for ApprovalService
# ============================================================================

class TestApprovalService:
    @pytest.fixture
    def service(self) -> ApprovalService:
        return ApprovalService()

    @pytest.fixture
    def legal_entity_id(self) -> UUID:
        return uuid4()

    @pytest.fixture
    def requester_id(self) -> UUID:
        return uuid4()

    @pytest.fixture
    def approver_id(self) -> UUID:
        return uuid4()

    @pytest.mark.asyncio
    async def test_submit_approval(self, service, legal_entity_id, requester_id):
        entity_id = uuid4()
        matrix_id = uuid4()
        request = await service.submit_approval(
            entity_type="Journal",
            entity_id=entity_id,
            approval_matrix_id=matrix_id,
            requester_id=requester_id,
            legal_entity_id=legal_entity_id,
            notes="Test submission",
        )
        assert request is not None
        assert request.entity_type == "Journal"
        assert request.entity_id == entity_id
        assert request.requester_id == requester_id
        assert request.legal_entity_id == legal_entity_id
        assert request.approval_matrix_id == matrix_id
        assert request.notes == "Test submission"
        assert request.status == ApprovalStatus.PENDING
        assert service._stats["submitted"] == 1
        # Check history was added
        history = service._history.get(request.id, [])
        assert len(history) == 1
        assert history[0].action == ApprovalAction.SUBMITTED.value

    @pytest.mark.asyncio
    async def test_list_approval_requests(self, service, legal_entity_id, requester_id):
        # Submit two requests
        await service.submit_approval("Journal", uuid4(), requester_id=requester_id, legal_entity_id=legal_entity_id)
        await service.submit_approval("Journal", uuid4(), requester_id=requester_id, legal_entity_id=legal_entity_id)

        result = await service.list_approval_requests(legal_entity_id=legal_entity_id)
        assert result.total == 2
        assert len(result.items) == 2

        # Filter by entity_type
        result2 = await service.list_approval_requests(legal_entity_id=legal_entity_id, entity_type="Journal")
        assert result2.total == 2

        # Filter by status
        result3 = await service.list_approval_requests(legal_entity_id=legal_entity_id, status="pending")
        assert result3.total == 2

        # Pagination
        result4 = await service.list_approval_requests(page=1, page_size=1)
        assert len(result4.items) == 1
        assert result4.total == 2
        assert result4.page == 1
        assert result4.page_size == 1

    @pytest.mark.asyncio
    async def test_get_approval_request(self, service, legal_entity_id, requester_id):
        request = await service.submit_approval("Journal", uuid4(), requester_id=requester_id, legal_entity_id=legal_entity_id)
        retrieved = await service.get_approval_request(request.id, legal_entity_id=legal_entity_id)
        assert retrieved is not None
        assert retrieved.id == request.id

        # Wrong legal_entity_id should return None
        retrieved2 = await service.get_approval_request(request.id, legal_entity_id=uuid4())
        assert retrieved2 is None

    @pytest.mark.asyncio
    async def test_process_approval_approve(self, service, legal_entity_id, requester_id, approver_id):
        request = await service.submit_approval("Journal", uuid4(), requester_id=requester_id, legal_entity_id=legal_entity_id)
        result = await service.process_approval(
            request_id=request.id,
            decision="approve",
            actor_id=approver_id,
            legal_entity_id=legal_entity_id,
            notes="Approved by manager",
        )
        assert result is not None
        assert result.status == ApprovalStatus.APPROVED
        assert result.approved_by_id == approver_id
        assert result.notes == "Approved by manager"
        assert service._stats["approved"] == 1
        # Check history
        history = service._history.get(request.id, [])
        assert len(history) == 2  # submitted + approved
        assert history[1].action == ApprovalAction.APPROVED.value

    @pytest.mark.asyncio
    async def test_process_approval_reject(self, service, legal_entity_id, requester_id, approver_id):
        request = await service.submit_approval("Journal", uuid4(), requester_id=requester_id, legal_entity_id=legal_entity_id)
        result = await service.process_approval(
            request_id=request.id,
            decision="reject",
            actor_id=approver_id,
            legal_entity_id=legal_entity_id,
            notes="Rejected due to policy",
        )
        assert result is not None
        assert result.status == ApprovalStatus.REJECTED
        assert result.notes == "Rejected due to policy"
        assert service._stats["rejected"] == 1

    @pytest.mark.asyncio
    async def test_process_approval_escalate(self, service, legal_entity_id, requester_id, approver_id):
        request = await service.submit_approval("Journal", uuid4(), requester_id=requester_id, legal_entity_id=legal_entity_id)
        result = await service.process_approval(
            request_id=request.id,
            decision="escalate",
            actor_id=approver_id,
            legal_entity_id=legal_entity_id,
            notes="Escalated to director",
        )
        assert result is not None
        assert result.status == ApprovalStatus.ESCALATED
        assert result.level == 2
        assert result.current_approver_id == approver_id  # In test, escalate uses same actor_id
        history = service._history.get(request.id, [])
        assert len(history) == 2
        assert history[1].action == ApprovalAction.ESCALATED.value

    @pytest.mark.asyncio
    async def test_process_approval_not_pending_raises(self, service, legal_entity_id, requester_id, approver_id):
        request = await service.submit_approval("Journal", uuid4(), requester_id=requester_id, legal_entity_id=legal_entity_id)
        await service.process_approval(request.id, "approve", approver_id, legal_entity_id)
        # Second attempt should raise
        with pytest.raises(ValueError, match="is not pending"):
            await service.process_approval(request.id, "reject", approver_id, legal_entity_id)

    @pytest.mark.asyncio
    async def test_process_approval_unknown_decision(self, service, legal_entity_id, requester_id, approver_id):
        request = await service.submit_approval("Journal", uuid4(), requester_id=requester_id, legal_entity_id=legal_entity_id)
        with pytest.raises(ValueError, match="Unknown decision"):
            await service.process_approval(request.id, "unknown", approver_id, legal_entity_id)

    @pytest.mark.asyncio
    async def test_recall_approval(self, service, legal_entity_id, requester_id):
        request = await service.submit_approval("Journal", uuid4(), requester_id=requester_id, legal_entity_id=legal_entity_id)
        result = await service.recall_approval(request.id, requester_id, legal_entity_id)
        assert result is not None
        assert result.status == ApprovalStatus.RECALLED
        history = service._history.get(request.id, [])
        assert len(history) == 2
        assert history[1].action == ApprovalAction.RECALLED.value

    @pytest.mark.asyncio
    async def test_recall_approval_wrong_user_raises(self, service, legal_entity_id, requester_id):
        request = await service.submit_approval("Journal", uuid4(), requester_id=requester_id, legal_entity_id=legal_entity_id)
        wrong_user = uuid4()
        with pytest.raises(ValueError, match="Only requester can recall"):
            await service.recall_approval(request.id, wrong_user, legal_entity_id)

    @pytest.mark.asyncio
    async def test_get_approval_history(self, service, legal_entity_id, requester_id, approver_id):
        request = await service.submit_approval("Journal", uuid4(), requester_id=requester_id, legal_entity_id=legal_entity_id)
        await service.process_approval(request.id, "approve", approver_id, legal_entity_id)
        history = await service.get_approval_history(request.id, legal_entity_id)
        assert len(history) == 2
        assert history[0].action == ApprovalAction.SUBMITTED.value
        assert history[1].action == ApprovalAction.APPROVED.value

    @pytest.mark.asyncio
    async def test_get_approval_history_not_found(self, service):
        history = await service.get_approval_history(uuid4())
        assert history == []

    @pytest.mark.asyncio
    async def test_create_approval_matrix(self, service, legal_entity_id, requester_id):
        matrix = await service.create_approval_matrix(
            matrix_code="MAT-TEST",
            matrix_name="Test Matrix",
            entity_type="Journal",
            min_amount=Decimal("1000"),
            max_amount=Decimal("50000"),
            currency="IDR",
            rules=[{"level": 1, "role": "manager"}],
            is_active=True,
            notes="Test notes",
            created_by=requester_id,
            legal_entity_id=legal_entity_id,
        )
        assert matrix is not None
        assert matrix.matrix_code == "MAT-TEST"
        assert matrix.matrix_name == "Test Matrix"
        assert matrix.entity_type == "Journal"
        assert matrix.min_amount == Decimal("1000")
        assert matrix.max_amount == Decimal("50000")
        assert matrix.currency == "IDR"
        assert matrix.rules == [{"level": 1, "role": "manager"}]
        assert matrix.is_active is True
        assert matrix.notes == "Test notes"
        assert matrix.created_by == requester_id
        assert matrix.legal_entity_id == legal_entity_id
        assert matrix.id in service._matrices

    @pytest.mark.asyncio
    async def test_list_approval_matrices(self, service, legal_entity_id):
        await service.create_approval_matrix("MAT-1", "Matrix 1", "Journal", legal_entity_id=legal_entity_id)
        await service.create_approval_matrix("MAT-2", "Matrix 2", "PurchaseOrder", legal_entity_id=legal_entity_id)
        await service.create_approval_matrix("MAT-3", "Matrix 3", "Journal", is_active=False, legal_entity_id=legal_entity_id)

        all_mats = await service.list_approval_matrices(legal_entity_id=legal_entity_id)
        assert len(all_mats) == 3

        filtered = await service.list_approval_matrices(legal_entity_id=legal_entity_id, entity_type="Journal")
        assert len(filtered) == 2

        active = await service.list_approval_matrices(legal_entity_id=legal_entity_id, is_active=True)
        assert len(active) == 2

        inactive = await service.list_approval_matrices(legal_entity_id=legal_entity_id, is_active=False)
        assert len(inactive) == 1

    @pytest.mark.asyncio
    async def test_get_approval_matrix(self, service, legal_entity_id):
        matrix = await service.create_approval_matrix("MAT-1", "Matrix 1", "Journal", legal_entity_id=legal_entity_id)
        retrieved = await service.get_approval_matrix(matrix.id, legal_entity_id)
        assert retrieved is not None
        assert retrieved.id == matrix.id

        # Wrong legal_entity_id
        retrieved2 = await service.get_approval_matrix(matrix.id, uuid4())
        assert retrieved2 is None

    @pytest.mark.asyncio
    async def test_update_approval_matrix(self, service, legal_entity_id, requester_id):
        matrix = await service.create_approval_matrix(
            "MAT-OLD", "Old Name", "Journal",
            min_amount=Decimal("100"),
            max_amount=Decimal("1000"),
            is_active=True,
            legal_entity_id=legal_entity_id,
        )
        updated = await service.update_approval_matrix(
            matrix_id=matrix.id,
            matrix_code="MAT-NEW",
            matrix_name="New Name",
            entity_type="PurchaseOrder",
            min_amount=Decimal("500"),
            max_amount=Decimal("5000"),
            currency="USD",
            rules=[{"level": 2, "role": "director"}],
            is_active=False,
            notes="Updated notes",
            updated_by=requester_id,
            legal_entity_id=legal_entity_id,
        )
        assert updated is not None
        assert updated.matrix_code == "MAT-NEW"
        assert updated.matrix_name == "New Name"
        assert updated.entity_type == "PurchaseOrder"
        assert updated.min_amount == Decimal("500")
        assert updated.max_amount == Decimal("5000")
        assert updated.currency == "USD"
        assert updated.rules == [{"level": 2, "role": "director"}]
        assert updated.is_active is False
        assert updated.notes == "Updated notes"
        assert updated.updated_at is not None

    @pytest.mark.asyncio
    async def test_update_approval_matrix_not_found(self, service):
        result = await service.update_approval_matrix(uuid4(), matrix_code="NEW", legal_entity_id=uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_deactivate_approval_matrix(self, service, legal_entity_id, requester_id):
        matrix = await service.create_approval_matrix("MAT-1", "Matrix 1", "Journal", legal_entity_id=legal_entity_id)
        result = await service.deactivate_approval_matrix(matrix.id, legal_entity_id, updated_by=requester_id)
        assert result is True
        assert matrix.is_active is False

    @pytest.mark.asyncio
    async def test_deactivate_approval_matrix_not_found(self, service):
        result = await service.deactivate_approval_matrix(uuid4())
        assert result is False

    @pytest.mark.asyncio
    async def test_get_pending_tasks_for_user(self, service, legal_entity_id, requester_id, approver_id):
        # Submit two pending requests for same legal_entity
        await service.submit_approval("Journal", uuid4(), requester_id=requester_id, legal_entity_id=legal_entity_id)
        await service.submit_approval("Journal", uuid4(), requester_id=requester_id, legal_entity_id=legal_entity_id)
        # Submit one that gets approved
        req3 = await service.submit_approval("Journal", uuid4(), requester_id=requester_id, legal_entity_id=legal_entity_id)
        await service.process_approval(req3.id, "approve", approver_id, legal_entity_id)

        tasks = await service.get_pending_tasks_for_user(approver_id, legal_entity_id)
        assert len(tasks) == 2  # both pending

        # Filter by legal_entity
        tasks2 = await service.get_pending_tasks_for_user(approver_id, uuid4())
        assert len(tasks2) == 0

    @pytest.mark.asyncio
    async def test_get_stats(self, service, legal_entity_id, requester_id, approver_id):
        stats = service.get_stats()
        assert stats == {"submitted": 0, "approved": 0, "rejected": 0}

        await service.submit_approval("Journal", uuid4(), requester_id=requester_id, legal_entity_id=legal_entity_id)
        req2 = await service.submit_approval("Journal", uuid4(), requester_id=requester_id, legal_entity_id=legal_entity_id)
        await service.process_approval(req2.id, "approve", approver_id, legal_entity_id)
        req3 = await service.submit_approval("Journal", uuid4(), requester_id=requester_id, legal_entity_id=legal_entity_id)
        await service.process_approval(req3.id, "reject", approver_id, legal_entity_id)

        stats2 = service.get_stats()
        assert stats2["submitted"] == 3
        assert stats2["approved"] == 1
        assert stats2["rejected"] == 1

    @pytest.mark.asyncio
    async def test_get_audit_trail(self, service, legal_entity_id, requester_id, approver_id):
        # Initially empty
        assert len(service.get_audit_trail()) == 0

        await service.submit_approval("Journal", uuid4(), requester_id=requester_id, legal_entity_id=legal_entity_id)
        trail = service.get_audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "submit_approval"

        # More actions
        req2 = await service.submit_approval("Journal", uuid4(), requester_id=requester_id, legal_entity_id=legal_entity_id)
        await service.process_approval(req2.id, "approve", approver_id, legal_entity_id)
        trail2 = service.get_audit_trail()
        assert len(trail2) == 3  # submit + submit + process_approval

    # ---- Integration test for full workflow ----
    @pytest.mark.asyncio
    async def test_full_approval_workflow(self, service, legal_entity_id, requester_id, approver_id):
        # 1. Submit
        request = await service.submit_approval(
            entity_type="Journal",
            entity_id=uuid4(),
            requester_id=requester_id,
            legal_entity_id=legal_entity_id,
            notes="Initial submission",
        )
        assert request.status == ApprovalStatus.PENDING

        # 2. List and find
        results = await service.list_approval_requests(legal_entity_id=legal_entity_id, status="pending")
        assert results.total == 1

        # 3. Approve
        approved = await service.process_approval(request.id, "approve", approver_id, legal_entity_id, notes="OK")
        assert approved.status == ApprovalStatus.APPROVED

        # 4. Check history
        history = await service.get_approval_history(request.id, legal_entity_id)
        assert len(history) == 2
        assert history[0].action == ApprovalAction.SUBMITTED.value
        assert history[1].action == ApprovalAction.APPROVED.value

        # 5. Check stats
        stats = service.get_stats()
        assert stats["submitted"] == 1
        assert stats["approved"] == 1


# ============================================================================
# Test for audit decorator
# ============================================================================

def test_audit_decorator():
    @audit
    def test_func():
        return "ok"
    assert test_func() == "ok"


# ============================================================================
# Test for exports
# ============================================================================

def test_exports():
    from application.service_layer.service_approval import __all__
    expected = [
        "ApprovalAction",
        "ApprovalHistoryEntry",
        "ApprovalMatrix",
        "ApprovalRequest",
        "ApprovalService",
        "ApprovalStatus",
        "PaginatedResult",
        "audit",
    ]
    assert set(__all__) == set(expected)
