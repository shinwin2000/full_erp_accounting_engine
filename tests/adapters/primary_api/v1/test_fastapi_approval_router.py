# tests/adapters/primary_api/v1/test_fastapi_approval_router.py
"""
Comprehensive unit tests for FastAPI Approval Router.

Covers:
- All enum classes
- All request/response schemas (valid & invalid cases)
- All endpoint functions (with mocked service layer)
- Approval matrix rule validation (min/max amount)
- Delegation date validation
- Negative paths: ValueError, PermissionError, NotFound, etc.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from adapters.primary_api.v1.fastapi_approval_router import (
    ApprovalAction,
    ApprovalActionSchema,
    ApprovalDelegationResponseSchema,
    ApprovalDelegationSchema,
    ApprovalEntityType,
    ApprovalHistorySchema,
    ApprovalLevel,
    ApprovalMatrixCreateSchema,
    ApprovalMatrixResponseSchema,
    ApprovalMatrixRuleSchema,
    ApprovalMatrixUpdateSchema,
    ApprovalRequestCreateSchema,
    ApprovalResponseSchema,
    ApprovalStatsResponseSchema,
    ApprovalStatus,
    ApprovalTaskResponseSchema,
    cancel_approval,
    create_approval_matrix,
    delegate_approval,
    delete_approval_matrix,
    export_approval_requests,
    get_approval_history,
    get_approval_matrix,
    get_approval_request,
    get_approval_request_by_number,
    get_approval_statistics,
    get_approval_svc,
    get_entity_approval_status,
    get_my_approval_tasks,
    get_my_approval_tasks_count,
    list_approval_matrices,
    list_approval_requests,
    list_my_delegations,
    perform_approval_action,
    recall_approval,
    revoke_delegation,
    submit_for_approval,
    update_approval_matrix,
)

# =============================================================================
# FIXED DATETIME (untuk menghindari flaky)
# =============================================================================

FIXED_DATETIME = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
FIXED_DATE = date(2026, 1, 15)


@pytest.fixture(autouse=True)
def mock_datetime_now():
    with patch("adapters.primary_api.v1.fastapi_approval_router.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_DATETIME
        mock_dt.UTC = UTC
        yield mock_dt


# =============================================================================
# Helper fixtures
# =============================================================================

@pytest.fixture
def mock_token_payload():
    payload = MagicMock()
    payload.user_id = uuid4()
    return payload


@pytest.fixture
def mock_legal_entity_id():
    return uuid4()


@pytest.fixture
def mock_permission():
    return MagicMock()


@pytest.fixture
def mock_approval_service():
    svc = AsyncMock(spec=[
        "submit_approval", "get_approval_request", "get_approval_request_by_number",
        "recall_approval", "cancel_approval", "process_approval_action",
        "list_approval_requests", "get_pending_tasks_for_user", "get_pending_tasks_count",
        "get_approval_history", "create_approval_matrix", "get_approval_matrix",
        "list_approval_matrices", "update_approval_matrix", "delete_approval_matrix",
        "deactivate_approval_matrix", "create_delegation", "list_delegations",
        "revoke_delegation", "get_approval_statistics", "get_entity_approval_status",
        "export_approval_requests"
    ])

    # Create a base mock request
    def base_request(**kwargs):
        data = {
            "id": uuid4(),
            "request_number": "APR-2025-001",
            "entity_type": "journal",
            "entity_id": uuid4(),
            "entity_reference": "JRN-001",
            "amount": Decimal("1000000"),
            "status": "pending",
            "current_level": "level_1",
            "requester_id": uuid4(),
            "requester_name": "Requester A",
            "requester_notes": "Test",
            "submitted_at": FIXED_DATETIME,
            "current_approver_id": uuid4(),
            "current_approver_name": "Approver A",
            "current_approver_role": "Manager",
            "approval_matrix_id": uuid4(),
            "approval_matrix_name": "Standard",
            "due_date": FIXED_DATETIME + timedelta(days=2),
            "escalated_at": None,
            "escalated_to": None,
            "completed_at": None,
            "completed_by": None,
            "completed_by_name": None,
            "final_decision": None,
            "is_locked": False,
            "version": 1,
            "history": [],
        }
        data.update(kwargs)
        return MagicMock(**data)

    # Set return values
    svc.submit_approval.return_value = base_request()
    svc.get_approval_request.return_value = base_request()
    svc.get_approval_request_by_number.return_value = base_request()
    svc.recall_approval.return_value = base_request(status="cancelled")
    svc.cancel_approval.return_value = base_request(status="cancelled")
    svc.process_approval_action.return_value = base_request(status="approved")
    svc.list_approval_requests.return_value = MagicMock(
        items=[base_request()],
        total=1,
    )
    svc.get_pending_tasks_for_user.return_value = [
        MagicMock(
            id=uuid4(),
            request_number="APR-2025-001",
            entity_type="journal",
            entity_id=uuid4(),
            entity_reference="JRN-001",
            amount=Decimal("1000000"),
            requester_id=uuid4(),
            requester_name="Requester A",
            submitted_at=FIXED_DATETIME,
            current_level="level_1",
            due_date=FIXED_DATETIME + timedelta(days=2),
            days_remaining=2,
            is_overdue=False,
            notes="Please approve",
        )
    ]
    svc.get_pending_tasks_count.return_value = MagicMock(
        total=5,
        by_entity_type={"journal": 3, "ap_invoice": 2},
        overdue=1,
    )
    svc.get_approval_history.return_value = [
        MagicMock(
            id=uuid4(),
            approval_request_id=uuid4(),
            action="submit",
            from_level=None,
            to_level="level_1",
            actor_id=uuid4(),
            actor_name="Requester A",
            actor_role="User",
            action_at=FIXED_DATETIME,
            notes="Submitted",
            previous_approver_id=None,
            new_approver_id=uuid4(),
        )
    ]

    # Matrix responses
    matrix = MagicMock(
        id=uuid4(),
        matrix_code="MAT-001",
        matrix_name="Standard",
        entity_type="journal",
        min_amount=Decimal("0"),
        max_amount=Decimal("5000000"),
        currency="IDR",
        rules=[{"level": "level_1", "min_approvers": 1}],
        is_active=True,
        notes=None,
        created_at=FIXED_DATETIME,
        updated_at=FIXED_DATETIME,
        created_by=uuid4(),
        created_by_name="Admin",
        version=1,
    )
    svc.create_approval_matrix.return_value = matrix
    svc.get_approval_matrix.return_value = matrix
    svc.list_approval_matrices.return_value = [matrix]
    svc.update_approval_matrix.return_value = matrix
    svc.delete_approval_matrix.return_value = MagicMock(matrix_code="MAT-001")
    svc.deactivate_approval_matrix.return_value = MagicMock(matrix_code="MAT-001")

    # Delegation
    delegation = MagicMock(
        id=uuid4(),
        delegator_id=uuid4(),
        delegator_name="Delegator A",
        delegate_to_id=uuid4(),
        delegate_to_name="Delegate B",
        start_date=FIXED_DATE,
        end_date=FIXED_DATE + timedelta(days=5),
        reason="Vacation",
        is_active=True,
        created_at=FIXED_DATETIME,
        created_by=uuid4(),
    )
    svc.create_delegation.return_value = delegation
    svc.list_delegations.return_value = [delegation]
    svc.revoke_delegation.return_value = MagicMock(is_active=False)

    # Statistics
    stats = MagicMock(
        total_requests=100,
        pending_requests=20,
        approved_requests=60,
        rejected_requests=10,
        escalated_requests=5,
        expired_requests=5,
        average_approval_time_hours=24.5,
        by_entity_type={"journal": {"pending": 10, "approved": 30}},
        by_level={"level_1": 40, "level_2": 30},
    )
    svc.get_approval_statistics.return_value = stats

    # Entity status
    svc.get_entity_approval_status.return_value = base_request()

    # Export
    svc.export_approval_requests.return_value = b"csv data"

    return svc


# =============================================================================
# Tests for Enums
# =============================================================================

class TestEnums:
    def test_approval_status_values(self):
        assert ApprovalStatus.PENDING.value == "pending"
        assert ApprovalStatus.APPROVED.value == "approved"
        assert ApprovalStatus.REJECTED.value == "rejected"
        assert ApprovalStatus.ESCALATED.value == "escalated"
        assert ApprovalStatus.CANCELLED.value == "cancelled"
        assert ApprovalStatus.EXPIRED.value == "expired"
        assert ApprovalStatus.DELEGATED.value == "delegated"

    def test_approval_action_values(self):
        assert ApprovalAction.SUBMIT.value == "submit"
        assert ApprovalAction.APPROVE.value == "approve"
        assert ApprovalAction.REJECT.value == "reject"
        assert ApprovalAction.ESCALATE.value == "escalate"
        assert ApprovalAction.RECALL.value == "recall"
        assert ApprovalAction.CANCEL.value == "cancel"
        assert ApprovalAction.DELEGATE.value == "delegate"
        assert ApprovalAction.REASSIGN.value == "reassign"

    def test_approval_entity_type_values(self):
        assert ApprovalEntityType.JOURNAL.value == "journal"
        assert ApprovalEntityType.AP_INVOICE.value == "ap_invoice"
        assert ApprovalEntityType.AR_INVOICE.value == "ar_invoice"
        assert ApprovalEntityType.PURCHASE_ORDER.value == "purchase_order"
        assert ApprovalEntityType.SALES_ORDER.value == "sales_order"
        assert ApprovalEntityType.CREDIT_NOTE.value == "credit_note"
        assert ApprovalEntityType.DEBIT_NOTE.value == "debit_note"
        assert ApprovalEntityType.PAYMENT.value == "payment"
        assert ApprovalEntityType.RECEIPT.value == "receipt"
        assert ApprovalEntityType.BUDGET.value == "budget"
        assert ApprovalEntityType.FIXED_ASSET.value == "fixed_asset"
        assert ApprovalEntityType.PRICE_CHANGE.value == "price_change"
        assert ApprovalEntityType.CUSTOMER_CREDIT_LIMIT.value == "customer_credit_limit"
        assert ApprovalEntityType.VENDOR_CHANGE.value == "vendor_change"
        assert ApprovalEntityType.USER_ROLE.value == "user_role"

    def test_approval_level_values(self):
        assert ApprovalLevel.LEVEL_1.value == "level_1"
        assert ApprovalLevel.LEVEL_2.value == "level_2"
        assert ApprovalLevel.LEVEL_3.value == "level_3"
        assert ApprovalLevel.LEVEL_4.value == "level_4"
        assert ApprovalLevel.LEVEL_5.value == "level_5"
        assert ApprovalLevel.EXECUTIVE.value == "executive"
        assert ApprovalLevel.CFO.value == "cfo"
        assert ApprovalLevel.CEO.value == "ceo"
        assert ApprovalLevel.BOARD.value == "board"


# =============================================================================
# Tests for Schemas (validation)
# =============================================================================

class TestApprovalMatrixRuleSchema:
    def test_valid_rule(self):
        data = {
            "level": ApprovalLevel.LEVEL_1,
            "min_amount": Decimal("0"),
            "max_amount": Decimal("1000000"),
            "approver_role_ids": [uuid4()],
            "approver_user_ids": [],
            "min_approvers": 1,
            "max_approvers": 2,
            "auto_approve_if_requester_in_role": False,
            "is_final": False,
            "escalation_days": 2,
            "escalation_to_level": ApprovalLevel.LEVEL_2,
        }
        schema = ApprovalMatrixRuleSchema(**data)
        assert schema.level == ApprovalLevel.LEVEL_1
        assert schema.min_amount == Decimal("0")

    def test_min_amount_less_than_max(self):
        with pytest.raises(ValueError, match="Min amount cannot be greater than max amount"):
            ApprovalMatrixRuleSchema(
                level=ApprovalLevel.LEVEL_1,
                min_amount=Decimal("1000"),
                max_amount=Decimal("500"),
            )

    def test_min_approvers_positive(self):
        with pytest.raises(ValueError):
            ApprovalMatrixRuleSchema(
                level=ApprovalLevel.LEVEL_1,
                min_approvers=0,
            )


class TestApprovalMatrixCreateSchema:
    def test_valid_schema(self):
        data = {
            "matrix_code": "MAT-001",
            "matrix_name": "Standard Approval",
            "entity_type": ApprovalEntityType.JOURNAL,
            "min_amount": Decimal("0"),
            "max_amount": Decimal("5000000"),
            "currency": "IDR",
            "rules": [
                {
                    "level": ApprovalLevel.LEVEL_1,
                    "min_approvers": 1,
                }
            ],
            "is_active": True,
            "notes": "Test",
        }
        schema = ApprovalMatrixCreateSchema(**data)
        assert schema.matrix_code == "MAT-001"
        assert len(schema.rules) == 1

    def test_matrix_code_uppercase(self):
        schema = ApprovalMatrixCreateSchema(
            matrix_code="mat-001",
            matrix_name="Test",
            entity_type=ApprovalEntityType.JOURNAL,
            rules=[{"level": ApprovalLevel.LEVEL_1, "min_approvers": 1}],
        )
        assert schema.matrix_code == "MAT-001"

    def test_min_amount_less_than_max(self):
        with pytest.raises(ValueError, match="Min amount cannot be greater than max amount"):
            ApprovalMatrixCreateSchema(
                matrix_code="MAT-001",
                matrix_name="Test",
                entity_type=ApprovalEntityType.JOURNAL,
                min_amount=Decimal("1000"),
                max_amount=Decimal("500"),
                rules=[{"level": ApprovalLevel.LEVEL_1, "min_approvers": 1}],
            )

    def test_rules_required(self):
        with pytest.raises(ValueError):
            ApprovalMatrixCreateSchema(
                matrix_code="MAT-001",
                matrix_name="Test",
                entity_type=ApprovalEntityType.JOURNAL,
                rules=[],
            )


class TestApprovalDelegationSchema:
    def test_valid_schema(self):
        data = {
            "delegate_to_user_id": uuid4(),
            "start_date": date(2025, 1, 1),
            "end_date": date(2025, 1, 10),
            "reason": "Vacation",
        }
        schema = ApprovalDelegationSchema(**data)
        assert schema.reason == "Vacation"

    def test_end_date_after_start(self):
        with pytest.raises(ValueError, match="End date must be after start date"):
            ApprovalDelegationSchema(
                delegate_to_user_id=uuid4(),
                start_date=date(2025, 1, 10),
                end_date=date(2025, 1, 5),
                reason="Test",
            )


# =============================================================================
# Tests for Endpoint Functions (with mocks)
# =============================================================================

@pytest.mark.asyncio
class TestSubmitApproval:
    async def test_submit_success(self, mock_approval_service, mock_token_payload,
                                   mock_legal_entity_id, mock_permission):
        request = ApprovalRequestCreateSchema(
            entity_type=ApprovalEntityType.JOURNAL,
            entity_id=uuid4(),
            amount=Decimal("1000000"),
            notes="Test",
        )
        result = await submit_for_approval(
            request=request,
            _permission=mock_permission,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            approval_svc=mock_approval_service,
        )
        assert isinstance(result, ApprovalResponseSchema)
        assert result.status == ApprovalStatus.PENDING
        mock_approval_service.submit_approval.assert_called_once_with(
            entity_type="journal",
            entity_id=request.entity_id,
            approval_matrix_id=request.approval_matrix_id,
            requester_id=mock_token_payload.user_id,
            legal_entity_id=mock_legal_entity_id,
            amount=request.amount,
            notes=request.notes,
        )

    @pytest.mark.parametrize("exception, expected_status, expected_detail", [
        (ValueError("Invalid entity"), 422, "Invalid entity"),
        (PermissionError("Not allowed"), 403, "Not allowed"),
        (Exception("DB error"), 500, "Internal server error"),
    ])
    async def test_submit_errors(self, exception, expected_status, expected_detail,
                                 mock_approval_service, mock_token_payload,
                                 mock_legal_entity_id, mock_permission):
        mock_approval_service.submit_approval.side_effect = exception
        request = ApprovalRequestCreateSchema(
            entity_type=ApprovalEntityType.JOURNAL,
            entity_id=uuid4(),
        )
        with pytest.raises(HTTPException) as exc:
            await submit_for_approval(
                request=request,
                _permission=mock_permission,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                approval_svc=mock_approval_service,
            )
        assert exc.value.status_code == expected_status
        assert expected_detail in exc.value.detail


@pytest.mark.asyncio
class TestGetApprovalRequest:
    async def test_get_by_id_success(self, mock_approval_service, mock_legal_entity_id,
                                      mock_permission):
        req_id = uuid4()
        result = await get_approval_request(
            request_id=req_id,
            _permission=mock_permission,
            legal_entity_id=mock_legal_entity_id,
            approval_svc=mock_approval_service,
        )
        assert isinstance(result, ApprovalResponseSchema)
        mock_approval_service.get_approval_request.assert_called_once_with(req_id, mock_legal_entity_id)

    async def test_get_by_id_not_found(self, mock_approval_service, mock_legal_entity_id,
                                       mock_permission):
        mock_approval_service.get_approval_request.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_approval_request(
                request_id=uuid4(),
                _permission=mock_permission,
                legal_entity_id=mock_legal_entity_id,
                approval_svc=mock_approval_service,
            )
        assert exc.value.status_code == 404

    async def test_get_by_number_success(self, mock_approval_service, mock_legal_entity_id,
                                         mock_permission):
        result = await get_approval_request_by_number(
            request_number="APR-001",
            _permission=mock_permission,
            legal_entity_id=mock_legal_entity_id,
            approval_svc=mock_approval_service,
        )
        assert isinstance(result, ApprovalResponseSchema)
        mock_approval_service.get_approval_request_by_number.assert_called_once_with("APR-001", mock_legal_entity_id)

    async def test_get_by_number_not_found(self, mock_approval_service, mock_legal_entity_id,
                                           mock_permission):
        mock_approval_service.get_approval_request_by_number.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_approval_request_by_number(
                request_number="UNKNOWN",
                _permission=mock_permission,
                legal_entity_id=mock_legal_entity_id,
                approval_svc=mock_approval_service,
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
class TestRecallApproval:
    async def test_recall_success(self, mock_approval_service, mock_token_payload,
                                  mock_legal_entity_id, mock_permission):
        req_id = uuid4()
        result = await recall_approval(
            request_id=req_id,
            reason="Mistake",
            _permission=mock_permission,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            approval_svc=mock_approval_service,
        )
        assert isinstance(result, ApprovalResponseSchema)
        mock_approval_service.recall_approval.assert_called_once_with(
            req_id, mock_token_payload.user_id, mock_legal_entity_id, "Mistake"
        )

    async def test_recall_not_found(self, mock_approval_service, mock_token_payload,
                                    mock_legal_entity_id, mock_permission):
        mock_approval_service.recall_approval.return_value = None
        with pytest.raises(HTTPException) as exc:
            await recall_approval(
                request_id=uuid4(),
                reason="",
                _permission=mock_permission,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                approval_svc=mock_approval_service,
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
class TestCancelApproval:
    async def test_cancel_success(self, mock_approval_service, mock_token_payload,
                                  mock_legal_entity_id, mock_permission):
        req_id = uuid4()
        result = await cancel_approval(
            request_id=req_id,
            reason="Admin action",
            _permission=mock_permission,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            approval_svc=mock_approval_service,
        )
        assert result["status"] == "cancelled"
        mock_approval_service.cancel_approval.assert_called_once_with(
            req_id, mock_token_payload.user_id, mock_legal_entity_id, "Admin action"
        )

    async def test_cancel_not_found(self, mock_approval_service, mock_token_payload,
                                    mock_legal_entity_id, mock_permission):
        mock_approval_service.cancel_approval.return_value = None
        with pytest.raises(HTTPException) as exc:
            await cancel_approval(
                request_id=uuid4(),
                reason="",
                _permission=mock_permission,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                approval_svc=mock_approval_service,
            )
        assert exc.value.status_code == 404

    async def test_cancel_permission_error(self, mock_approval_service, mock_token_payload,
                                           mock_legal_entity_id, mock_permission):
        mock_approval_service.cancel_approval.side_effect = PermissionError("Not allowed")
        with pytest.raises(HTTPException) as exc:
            await cancel_approval(
                request_id=uuid4(),
                reason="",
                _permission=mock_permission,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                approval_svc=mock_approval_service,
            )
        assert exc.value.status_code == 403


@pytest.mark.asyncio
class TestPerformApprovalAction:
    async def test_approve_success(self, mock_approval_service, mock_token_payload,
                                   mock_legal_entity_id, mock_permission):
        req_id = uuid4()
        action_data = ApprovalActionSchema(action=ApprovalAction.APPROVE, notes="Approved")
        result = await perform_approval_action(
            request_id=req_id,
            action_data=action_data,
            _permission=mock_permission,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            approval_svc=mock_approval_service,
        )
        assert isinstance(result, ApprovalResponseSchema)
        mock_approval_service.process_approval_action.assert_called_once_with(
            request_id=req_id,
            action="approve",
            actor_id=mock_token_payload.user_id,
            legal_entity_id=mock_legal_entity_id,
            notes="Approved",
            delegate_to_user_id=None,
            escalation_level=None,
        )

    async def test_escalate_success(self, mock_approval_service, mock_token_payload,
                                    mock_legal_entity_id, mock_permission):
        req_id = uuid4()
        action_data = ApprovalActionSchema(
            action=ApprovalAction.ESCALATE,
            notes="Escalate to CFO",
            escalation_level=ApprovalLevel.CFO,
        )
        result = await perform_approval_action(
            request_id=req_id,
            action_data=action_data,
            _permission=mock_permission,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            approval_svc=mock_approval_service,
        )
        assert isinstance(result, ApprovalResponseSchema)
        mock_approval_service.process_approval_action.assert_called_once_with(
            request_id=req_id,
            action="escalate",
            actor_id=mock_token_payload.user_id,
            legal_entity_id=mock_legal_entity_id,
            notes="Escalate to CFO",
            delegate_to_user_id=None,
            escalation_level="cfo",
        )

    async def test_delegate_success(self, mock_approval_service, mock_token_payload,
                                    mock_legal_entity_id, mock_permission):
        req_id = uuid4()
        delegate_user = uuid4()
        action_data = ApprovalActionSchema(
            action=ApprovalAction.DELEGATE,
            notes="Delegate to John",
            delegate_to_user_id=delegate_user,
        )
        result = await perform_approval_action(
            request_id=req_id,
            action_data=action_data,
            _permission=mock_permission,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            approval_svc=mock_approval_service,
        )
        assert isinstance(result, ApprovalResponseSchema)
        mock_approval_service.process_approval_action.assert_called_once_with(
            request_id=req_id,
            action="delegate",
            actor_id=mock_token_payload.user_id,
            legal_entity_id=mock_legal_entity_id,
            notes="Delegate to John",
            delegate_to_user_id=delegate_user,
            escalation_level=None,
        )

    @pytest.mark.parametrize("exception, expected_status", [
        (ValueError("Invalid action"), 422),
        (PermissionError("Not allowed"), 403),
        (Exception("DB error"), 500),
    ])
    async def test_action_errors(self, exception, expected_status, mock_approval_service,
                                 mock_token_payload, mock_legal_entity_id, mock_permission):
        mock_approval_service.process_approval_action.side_effect = exception
        action_data = ApprovalActionSchema(action=ApprovalAction.APPROVE)
        with pytest.raises(HTTPException) as exc:
            await perform_approval_action(
                request_id=uuid4(),
                action_data=action_data,
                _permission=mock_permission,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                approval_svc=mock_approval_service,
            )
        assert exc.value.status_code == expected_status

    async def test_action_not_found(self, mock_approval_service, mock_token_payload,
                                    mock_legal_entity_id, mock_permission):
        mock_approval_service.process_approval_action.return_value = None
        action_data = ApprovalActionSchema(action=ApprovalAction.APPROVE)
        with pytest.raises(HTTPException) as exc:
            await perform_approval_action(
                request_id=uuid4(),
                action_data=action_data,
                _permission=mock_permission,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                approval_svc=mock_approval_service,
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
class TestListApprovalRequests:
    async def test_list_success(self, mock_approval_service, mock_legal_entity_id,
                                mock_permission):
        result = await list_approval_requests(
            entity_type=ApprovalEntityType.JOURNAL,
            status=ApprovalStatus.PENDING,
            requester_id=None,
            start_date=None,
            end_date=None,
            page=1,
            page_size=20,
            _permission=mock_permission,
            legal_entity_id=mock_legal_entity_id,
            approval_svc=mock_approval_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], ApprovalResponseSchema)
        mock_approval_service.list_approval_requests.assert_called_once()


@pytest.mark.asyncio
class TestApproverTasks:
    async def test_get_my_tasks(self, mock_approval_service, mock_token_payload,
                                mock_legal_entity_id, mock_permission):
        result = await get_my_approval_tasks(
            entity_type=ApprovalEntityType.JOURNAL,
            overdue_only=False,
            _permission=mock_permission,
            legal_entity_id=mock_legal_entity_id,
            current_user=mock_token_payload,
            approval_svc=mock_approval_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], ApprovalTaskResponseSchema)
        mock_approval_service.get_pending_tasks_for_user.assert_called_once_with(
            user_id=mock_token_payload.user_id,
            legal_entity_id=mock_legal_entity_id,
            entity_type="journal",
            overdue_only=False,
        )

    async def test_get_tasks_count(self, mock_approval_service, mock_token_payload,
                                   mock_legal_entity_id, mock_permission):
        result = await get_my_approval_tasks_count(
            _permission=mock_permission,
            legal_entity_id=mock_legal_entity_id,
            current_user=mock_token_payload,
            approval_svc=mock_approval_service,
        )
        assert result["total"] == 5
        assert result["overdue"] == 1
        mock_approval_service.get_pending_tasks_count.assert_called_once_with(
            user_id=mock_token_payload.user_id,
            legal_entity_id=mock_legal_entity_id,
        )


@pytest.mark.asyncio
class TestApprovalHistory:
    async def test_get_history(self, mock_approval_service, mock_legal_entity_id,
                               mock_permission):
        req_id = uuid4()
        result = await get_approval_history(
            request_id=req_id,
            _permission=mock_permission,
            legal_entity_id=mock_legal_entity_id,
            approval_svc=mock_approval_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], ApprovalHistorySchema)
        mock_approval_service.get_approval_history.assert_called_once_with(req_id, mock_legal_entity_id)


# =============================================================================
# Tests for Approval Matrix Endpoints
# =============================================================================

@pytest.mark.asyncio
class TestApprovalMatrixCRUD:
    async def test_create_matrix_success(self, mock_approval_service, mock_token_payload,
                                         mock_legal_entity_id, mock_permission):
        rule = ApprovalMatrixRuleSchema(level=ApprovalLevel.LEVEL_1, min_approvers=1)
        request = ApprovalMatrixCreateSchema(
            matrix_code="MAT-001",
            matrix_name="Standard",
            entity_type=ApprovalEntityType.JOURNAL,
            rules=[rule],
        )
        result = await create_approval_matrix(
            request=request,
            _permission=mock_permission,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            approval_svc=mock_approval_service,
        )
        assert isinstance(result, ApprovalMatrixResponseSchema)
        assert result.matrix_code == "MAT-001"
        mock_approval_service.create_approval_matrix.assert_called_once()

    async def test_list_matrices(self, mock_approval_service, mock_legal_entity_id,
                                 mock_permission):
        result = await list_approval_matrices(
            entity_type=ApprovalEntityType.JOURNAL,
            is_active=True,
            _permission=mock_permission,
            legal_entity_id=mock_legal_entity_id,
            approval_svc=mock_approval_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], ApprovalMatrixResponseSchema)
        mock_approval_service.list_approval_matrices.assert_called_once()

    async def test_get_matrix_success(self, mock_approval_service, mock_legal_entity_id,
                                      mock_permission):
        matrix_id = uuid4()
        result = await get_approval_matrix(
            matrix_id=matrix_id,
            _permission=mock_permission,
            legal_entity_id=mock_legal_entity_id,
            approval_svc=mock_approval_service,
        )
        assert isinstance(result, ApprovalMatrixResponseSchema)
        mock_approval_service.get_approval_matrix.assert_called_once_with(matrix_id, mock_legal_entity_id)

    async def test_get_matrix_not_found(self, mock_approval_service, mock_legal_entity_id,
                                        mock_permission):
        mock_approval_service.get_approval_matrix.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_approval_matrix(
                matrix_id=uuid4(),
                _permission=mock_permission,
                legal_entity_id=mock_legal_entity_id,
                approval_svc=mock_approval_service,
            )
        assert exc.value.status_code == 404

    async def test_update_matrix_success(self, mock_approval_service, mock_token_payload,
                                         mock_legal_entity_id, mock_permission):
        matrix_id = uuid4()
        request = ApprovalMatrixUpdateSchema(matrix_name="Updated Name")
        result = await update_approval_matrix(
            matrix_id=matrix_id,
            request=request,
            _permission=mock_permission,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            approval_svc=mock_approval_service,
        )
        assert isinstance(result, ApprovalMatrixResponseSchema)
        mock_approval_service.update_approval_matrix.assert_called_once()

    async def test_delete_matrix_deactivate(self, mock_approval_service, mock_token_payload,
                                            mock_legal_entity_id, mock_permission):
        matrix_id = uuid4()
        result = await delete_approval_matrix(
            matrix_id=matrix_id,
            permanent=False,
            _permission=mock_permission,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            approval_svc=mock_approval_service,
        )
        assert result["action"] == "deactivated"
        mock_approval_service.deactivate_approval_matrix.assert_called_once_with(
            matrix_id, mock_legal_entity_id, mock_token_payload.user_id
        )

    async def test_delete_matrix_permanent(self, mock_approval_service, mock_token_payload,
                                           mock_legal_entity_id, mock_permission):
        matrix_id = uuid4()
        result = await delete_approval_matrix(
            matrix_id=matrix_id,
            permanent=True,
            _permission=mock_permission,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            approval_svc=mock_approval_service,
        )
        assert result["action"] == "deleted"
        mock_approval_service.delete_approval_matrix.assert_called_once_with(
            matrix_id, mock_legal_entity_id, mock_token_payload.user_id
        )


# =============================================================================
# Tests for Delegation Endpoints
# =============================================================================

@pytest.mark.asyncio
class TestDelegation:
    async def test_delegate_success(self, mock_approval_service, mock_token_payload,
                                    mock_legal_entity_id, mock_permission):
        request = ApprovalDelegationSchema(
            delegate_to_user_id=uuid4(),
            start_date=FIXED_DATE,
            end_date=FIXED_DATE + timedelta(days=5),
            reason="Vacation",
        )
        result = await delegate_approval(
            request=request,
            _permission=mock_permission,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            approval_svc=mock_approval_service,
        )
        assert isinstance(result, ApprovalDelegationResponseSchema)
        assert result.reason == "Vacation"
        mock_approval_service.create_delegation.assert_called_once()

    async def test_list_delegations(self, mock_approval_service, mock_token_payload,
                                    mock_legal_entity_id, mock_permission):
        result = await list_my_delegations(
            is_active=True,
            _permission=mock_permission,
            legal_entity_id=mock_legal_entity_id,
            current_user=mock_token_payload,
            approval_svc=mock_approval_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], ApprovalDelegationResponseSchema)
        mock_approval_service.list_delegations.assert_called_once_with(
            delegator_id=mock_token_payload.user_id,
            legal_entity_id=mock_legal_entity_id,
            is_active=True,
        )

    async def test_revoke_delegation_success(self, mock_approval_service, mock_token_payload,
                                             mock_legal_entity_id, mock_permission):
        del_id = uuid4()
        result = await revoke_delegation(
            delegation_id=del_id,
            _permission=mock_permission,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            approval_svc=mock_approval_service,
        )
        assert result["revoked"] is True
        mock_approval_service.revoke_delegation.assert_called_once_with(
            del_id, mock_token_payload.user_id, mock_legal_entity_id
        )

    async def test_revoke_delegation_not_found(self, mock_approval_service, mock_token_payload,
                                               mock_legal_entity_id, mock_permission):
        mock_approval_service.revoke_delegation.return_value = None
        with pytest.raises(HTTPException) as exc:
            await revoke_delegation(
                delegation_id=uuid4(),
                _permission=mock_permission,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                approval_svc=mock_approval_service,
            )
        assert exc.value.status_code == 404


# =============================================================================
# Tests for Statistics and Status Endpoints
# =============================================================================

@pytest.mark.asyncio
class TestStatisticsAndStatus:
    async def test_get_statistics(self, mock_approval_service, mock_legal_entity_id,
                                  mock_permission):
        start = date(2025, 1, 1)
        end = date(2025, 1, 31)
        result = await get_approval_statistics(
            start_date=start,
            end_date=end,
            entity_type=ApprovalEntityType.JOURNAL,
            _permission=mock_permission,
            legal_entity_id=mock_legal_entity_id,
            approval_svc=mock_approval_service,
        )
        assert isinstance(result, ApprovalStatsResponseSchema)
        assert result.total_requests == 100
        assert result.pending_requests == 20
        mock_approval_service.get_approval_statistics.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            start_date=start,
            end_date=end,
            entity_type="journal",
        )

    async def test_get_entity_approval_status_found(self, mock_approval_service,
                                                    mock_legal_entity_id, mock_permission):
        entity_id = uuid4()
        result = await get_entity_approval_status(
            entity_type=ApprovalEntityType.JOURNAL,
            entity_id=entity_id,
            _permission=mock_permission,
            legal_entity_id=mock_legal_entity_id,
            approval_svc=mock_approval_service,
        )
        assert isinstance(result, ApprovalResponseSchema)
        mock_approval_service.get_entity_approval_status.assert_called_once_with(
            entity_type="journal",
            entity_id=entity_id,
            legal_entity_id=mock_legal_entity_id,
        )

    async def test_get_entity_approval_status_not_found(self, mock_approval_service,
                                                        mock_legal_entity_id, mock_permission):
        mock_approval_service.get_entity_approval_status.return_value = None
        result = await get_entity_approval_status(
            entity_type=ApprovalEntityType.JOURNAL,
            entity_id=uuid4(),
            _permission=mock_permission,
            legal_entity_id=mock_legal_entity_id,
            approval_svc=mock_approval_service,
        )
        assert result is None


# =============================================================================
# Tests for Export Endpoint
# =============================================================================

@pytest.mark.asyncio
class TestExport:
    async def test_export_csv(self, mock_approval_service, mock_legal_entity_id,
                              mock_permission):
        start = date(2025, 1, 1)
        end = date(2025, 1, 31)
        response = await export_approval_requests(
            start_date=start,
            end_date=end,
            format="csv",
            status=ApprovalStatus.APPROVED,
            _permission=mock_permission,
            legal_entity_id=mock_legal_entity_id,
            approval_svc=mock_approval_service,
        )
        assert response.body == b"csv data"
        assert response.media_type == "text/csv"
        assert "attachment" in response.headers["Content-Disposition"]
        mock_approval_service.export_approval_requests.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            start_date=start,
            end_date=end,
            format="csv",
            status="approved",
        )

    async def test_export_excel(self, mock_approval_service, mock_legal_entity_id,
                                mock_permission):
        mock_approval_service.export_approval_requests.return_value = b"excel data"
        start = date(2025, 1, 1)
        end = date(2025, 1, 31)
        response = await export_approval_requests(
            start_date=start,
            end_date=end,
            format="excel",
            status=None,
            _permission=mock_permission,
            legal_entity_id=mock_legal_entity_id,
            approval_svc=mock_approval_service,
        )
        assert response.media_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# =============================================================================
# Tests for Dependency Injection
# =============================================================================

@pytest.mark.asyncio
async def test_get_approval_svc():
    request = MagicMock()
    request.app.state.container = MagicMock()
    request.app.state.container.resolve.return_value = "service"
    result = await get_approval_svc(request)
    assert result == "service"
