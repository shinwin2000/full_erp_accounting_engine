# adapters/primary_api/v1/test_fastapi_capital_router.py
"""
Comprehensive unit tests for FastAPI Capital Router.

Covers:
- IdempotencyManager (cache, TTL, key generation)
- Enums: ContributionType, DividendStatus
- All request/response Pydantic models (construction & validation)
- All endpoint functions using FastAPI TestClient with dependency overrides:
  - Capital contribution: record, approve, post (idempotent), cancel
  - Capital withdrawal: record, approve, post (idempotent), cancel
  - Dividend: declare, approve, pay, cancel
  - Retained earnings: adjust, transfer, update (idempotent)
  - Stats endpoint
- Error handling (service exceptions -> HTTP 500)
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI, status
from fastapi.testclient import TestClient

from adapters.primary_api.v1.fastapi_capital_router import (
    CancelCapitalContributionRequest,
    CancelCapitalWithdrawalRequest,
    CancelDividendRequest,
    ContributionType,
    DeclareDividendRequest,
    DividendStatus,
    IdempotencyManager,
    RecordCapitalContributionRequest,
    get_correlation_id,
    router,
)

# =============================================================================
# Helper: Create FastAPI app with dependency overrides
# =============================================================================


@pytest.fixture
def mock_capital_service():
    service = AsyncMock()

    # Contribution
    service.record_capital_contribution.return_value = MagicMock(
        contribution_id=uuid4(),
        legal_entity_id=uuid4(),
        amount=Decimal("1000000"),
        contribution_date=date.today(),
        status="PENDING",
        created_at=datetime.now(UTC),
    )
    service.approve_capital_contribution.return_value = None
    service.post_capital_contribution.return_value = None
    service.cancel_capital_contribution.return_value = None

    # Withdrawal
    service.record_capital_withdrawal.return_value = None
    service.approve_capital_withdrawal.return_value = None
    service.post_capital_withdrawal.return_value = None
    service.cancel_capital_withdrawal.return_value = None

    # Dividend
    service.declare_dividend.return_value = MagicMock(
        dividend_id=uuid4(),
        legal_entity_id=uuid4(),
        total_amount=Decimal("500000"),
        paid_amount=Decimal("0"),
        declaration_date=date.today(),
        status="DECLARED",
        created_at=datetime.now(UTC),
    )
    service.approve_dividend.return_value = None
    service.pay_dividend.return_value = None
    service.cancel_dividend.return_value = None

    # Retained earnings
    service.adjust_retained_earnings.return_value = None
    service.transfer_retained_earnings.return_value = None
    service.update_retained_earnings.return_value = None

    # Stats
    service.get_stats.return_value = {"total_contributions": 10, "total_dividends": 5}

    return service


@pytest.fixture
def app(mock_capital_service):
    app = FastAPI()
    app.include_router(router)

    # Override dependency
    async def override_get_service(cls):
        return mock_capital_service

    app.dependency_overrides[
        "adapters.dependency_provider.get_service"
    ] = override_get_service

    return app


@pytest.fixture
def client(app):
    return TestClient(app)


# =============================================================================
# Tests for IdempotencyManager
# =============================================================================

class TestIdempotencyManager:
    def test_initialization(self):
        manager = IdempotencyManager()
        assert manager._storage == {}
        assert manager._ttl_seconds == 86400

    def test_get_cached_result_miss(self):
        manager = IdempotencyManager()
        result = manager.get_cached_result("key1", "method1")
        assert result is None

    def test_cache_and_retrieve(self):
        manager = IdempotencyManager()
        data = {"id": "123", "status": "ok"}
        manager.cache_result("key1", "method1", data)
        cached = manager.get_cached_result("key1", "method1")
        assert cached == data

    def test_cache_serializes_complex_types(self):
        manager = IdempotencyManager()
        data = {"date": date.today(), "decimal": Decimal("10.50")}
        manager.cache_result("key2", "method2", data)
        cached = manager.get_cached_result("key2", "method2")
        assert cached is not None
        assert "date" in cached

    def test_cache_expiration(self):
        manager = IdempotencyManager()
        manager._ttl_seconds = 0
        manager.cache_result("key3", "method3", {"foo": "bar"})
        cached = manager.get_cached_result("key3", "method3")
        assert cached is None

    def test_key_generation_deterministic(self):
        manager = IdempotencyManager()
        key1 = manager._get_key("abc", "post_capital_contribution")
        key2 = manager._get_key("abc", "post_capital_contribution")
        key3 = manager._get_key("abc", "post_capital_withdrawal")
        assert key1 == key2
        assert key1 != key3


# =============================================================================
# Tests for Enums
# =============================================================================

class TestEnums:
    def test_contribution_type_values(self):
        assert ContributionType.CASH.value == "CASH"
        assert ContributionType.ASSET.value == "ASSET"
        assert ContributionType.INVENTORY.value == "INVENTORY"
        assert ContributionType.INTELLECTUAL_PROPERTY.value == "INTELLECTUAL_PROPERTY"

    def test_dividend_status_values(self):
        assert DividendStatus.DECLARED.value == "DECLARED"
        assert DividendStatus.APPROVED.value == "APPROVED"
        assert DividendStatus.PAID.value == "PAID"
        assert DividendStatus.PARTIALLY_PAID.value == "PARTIALLY_PAID"
        assert DividendStatus.CANCELLED.value == "CANCELLED"


# =============================================================================
# Tests for Pydantic Models (validation)
# =============================================================================

class TestModels:
    def test_record_capital_contribution_request_valid(self):
        req = RecordCapitalContributionRequest(
            legal_entity_id=uuid4(),
            amount=Decimal("1000"),
            contribution_date=date.today(),
            description="Test",
            contributor_id=uuid4(),
            contribution_type=ContributionType.CASH,
        )
        assert req.amount == Decimal("1000")
        assert req.contribution_type == ContributionType.CASH

    def test_record_capital_contribution_request_amount_positive(self):
        with pytest.raises(ValueError):
            RecordCapitalContributionRequest(
                legal_entity_id=uuid4(),
                amount=Decimal("-100"),
                contribution_date=date.today(),
            )

    def test_declare_dividend_request_valid(self):
        req = DeclareDividendRequest(
            legal_entity_id=uuid4(),
            total_amount=Decimal("1000"),
            declaration_date=date.today(),
            payment_date=date.today(),
            description="Test",
        )
        assert req.total_amount == Decimal("1000")

    def test_declare_dividend_request_payment_after_declaration(self):
        # payment_date earlier than declaration_date should raise
        with pytest.raises(ValueError):
            DeclareDividendRequest(
                legal_entity_id=uuid4(),
                total_amount=Decimal("1000"),
                declaration_date=date(2025, 1, 10),
                payment_date=date(2025, 1, 5),
            )

    def test_cancel_requests_require_reason(self):
        with pytest.raises(ValueError):
            CancelCapitalContributionRequest(
                contribution_id=uuid4(),
                reason="",
            )
        with pytest.raises(ValueError):
            CancelCapitalWithdrawalRequest(
                withdrawal_id=uuid4(),
                reason="",
            )
        with pytest.raises(ValueError):
            CancelDividendRequest(
                dividend_id=uuid4(),
                reason="",
            )


# =============================================================================
# Tests for get_correlation_id helper
# =============================================================================

def test_get_correlation_id_from_header():
    request = MagicMock()
    request.headers = {"X-Correlation-ID": "test-123"}
    result = get_correlation_id(request)
    assert result == "test-123"


def test_get_correlation_id_generates_new():
    request = MagicMock()
    request.headers = {}
    result = get_correlation_id(request)
    assert result is not None
    assert len(result) > 0


# =============================================================================
# Tests for Capital Contribution Endpoints
# =============================================================================

class TestCapitalContribution:
    def test_record_success(self, client, mock_capital_service):
        payload = {
            "legal_entity_id": str(uuid4()),
            "amount": "1000000",
            "contribution_date": date.today().isoformat(),
            "description": "Initial capital",
            "contributor_id": str(uuid4()),
            "contribution_type": "CASH",
        }
        response = client.post("/contributions", json=payload)
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert "contribution_id" in data
        assert data["status"] == "PENDING"
        mock_capital_service.record_capital_contribution.assert_awaited_once()

    def test_record_service_error(self, client, mock_capital_service):
        mock_capital_service.record_capital_contribution.side_effect = Exception("Service error")
        payload = {
            "legal_entity_id": str(uuid4()),
            "amount": "1000",
            "contribution_date": date.today().isoformat(),
        }
        response = client.post("/contributions", json=payload)
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert "Service error" in response.text

    def test_approve_success(self, client, mock_capital_service):
        payload = {"contribution_id": str(uuid4())}
        response = client.post("/contributions/approve", json=payload)
        assert response.status_code == status.HTTP_204_NO_CONTENT
        # Verify service was called with the correct contribution_id
        call_args = mock_capital_service.approve_capital_contribution.call_args
        assert call_args is not None
        assert call_args.kwargs["contribution_id"] == payload["contribution_id"]

    def test_approve_service_error(self, client, mock_capital_service):
        mock_capital_service.approve_capital_contribution.side_effect = Exception("Error")
        payload = {"contribution_id": str(uuid4())}
        response = client.post("/contributions/approve", json=payload)
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_post_success(self, client, mock_capital_service):
        payload = {"contribution_id": str(uuid4())}
        response = client.post("/contributions/post", json=payload)
        assert response.status_code == status.HTTP_204_NO_CONTENT
        mock_capital_service.post_capital_contribution.assert_awaited_once()

    def test_post_idempotent(self, client, mock_capital_service):
        # First call
        payload = {"contribution_id": str(uuid4())}
        response1 = client.post("/contributions/post", json=payload, headers={"Idempotency-Key": "key123"})
        assert response1.status_code == status.HTTP_204_NO_CONTENT
        # Second call with same key should not call service again
        response2 = client.post("/contributions/post", json=payload, headers={"Idempotency-Key": "key123"})
        assert response2.status_code == status.HTTP_204_NO_CONTENT
        # Service should have been called only once
        assert mock_capital_service.post_capital_contribution.call_count == 1

    def test_post_service_error(self, client, mock_capital_service):
        mock_capital_service.post_capital_contribution.side_effect = Exception("Error")
        payload = {"contribution_id": str(uuid4())}
        response = client.post("/contributions/post", json=payload)
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_cancel_success(self, client, mock_capital_service):
        payload = {"contribution_id": str(uuid4()), "reason": "Changed mind"}
        response = client.post("/contributions/cancel", json=payload)
        assert response.status_code == status.HTTP_204_NO_CONTENT
        mock_capital_service.cancel_capital_contribution.assert_awaited_once()

    def test_cancel_service_error(self, client, mock_capital_service):
        mock_capital_service.cancel_capital_contribution.side_effect = Exception("Error")
        payload = {"contribution_id": str(uuid4()), "reason": "Test"}
        response = client.post("/contributions/cancel", json=payload)
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


# =============================================================================
# Tests for Capital Withdrawal Endpoints
# =============================================================================

class TestCapitalWithdrawal:
    def test_record_success(self, client, mock_capital_service):
        payload = {
            "legal_entity_id": str(uuid4()),
            "amount": "500000",
            "withdrawal_date": date.today().isoformat(),
            "description": "Withdraw for expenses",
        }
        response = client.post("/withdrawals", json=payload)
        assert response.status_code == status.HTTP_204_NO_CONTENT
        mock_capital_service.record_capital_withdrawal.assert_awaited_once()

    def test_record_service_error(self, client, mock_capital_service):
        mock_capital_service.record_capital_withdrawal.side_effect = Exception("Error")
        payload = {
            "legal_entity_id": str(uuid4()),
            "amount": "1000",
            "withdrawal_date": date.today().isoformat(),
        }
        response = client.post("/withdrawals", json=payload)
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_approve_success(self, client, mock_capital_service):
        payload = {"withdrawal_id": str(uuid4())}
        response = client.post("/withdrawals/approve", json=payload)
        assert response.status_code == status.HTTP_204_NO_CONTENT
        call_args = mock_capital_service.approve_capital_withdrawal.call_args
        assert call_args is not None
        assert call_args.kwargs["withdrawal_id"] == payload["withdrawal_id"]

    def test_approve_service_error(self, client, mock_capital_service):
        mock_capital_service.approve_capital_withdrawal.side_effect = Exception("Error")
        payload = {"withdrawal_id": str(uuid4())}
        response = client.post("/withdrawals/approve", json=payload)
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_post_success(self, client, mock_capital_service):
        payload = {"withdrawal_id": str(uuid4())}
        response = client.post("/withdrawals/post", json=payload)
        assert response.status_code == status.HTTP_204_NO_CONTENT
        mock_capital_service.post_capital_withdrawal.assert_awaited_once()

    def test_post_idempotent(self, client, mock_capital_service):
        payload = {"withdrawal_id": str(uuid4())}
        response1 = client.post("/withdrawals/post", json=payload, headers={"Idempotency-Key": "key456"})
        assert response1.status_code == status.HTTP_204_NO_CONTENT
        response2 = client.post("/withdrawals/post", json=payload, headers={"Idempotency-Key": "key456"})
        assert response2.status_code == status.HTTP_204_NO_CONTENT
        assert mock_capital_service.post_capital_withdrawal.call_count == 1

    def test_post_service_error(self, client, mock_capital_service):
        mock_capital_service.post_capital_withdrawal.side_effect = Exception("Error")
        payload = {"withdrawal_id": str(uuid4())}
        response = client.post("/withdrawals/post", json=payload)
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_cancel_success(self, client, mock_capital_service):
        payload = {"withdrawal_id": str(uuid4()), "reason": "Cancel"}
        response = client.post("/withdrawals/cancel", json=payload)
        assert response.status_code == status.HTTP_204_NO_CONTENT
        mock_capital_service.cancel_capital_withdrawal.assert_awaited_once()

    def test_cancel_service_error(self, client, mock_capital_service):
        mock_capital_service.cancel_capital_withdrawal.side_effect = Exception("Error")
        payload = {"withdrawal_id": str(uuid4()), "reason": "Test"}
        response = client.post("/withdrawals/cancel", json=payload)
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


# =============================================================================
# Tests for Dividend Endpoints
# =============================================================================

class TestDividend:
    def test_declare_success(self, client, mock_capital_service):
        payload = {
            "legal_entity_id": str(uuid4()),
            "total_amount": "500000",
            "declaration_date": date.today().isoformat(),
            "payment_date": date.today().isoformat(),
            "description": "Annual dividend",
        }
        response = client.post("/dividends", json=payload)
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert "dividend_id" in data
        assert data["status"] == "DECLARED"
        assert data["total_amount"] == "500000"
        mock_capital_service.declare_dividend.assert_awaited_once()

    def test_declare_service_error(self, client, mock_capital_service):
        mock_capital_service.declare_dividend.side_effect = Exception("Error")
        payload = {
            "legal_entity_id": str(uuid4()),
            "total_amount": "1000",
            "declaration_date": date.today().isoformat(),
        }
        response = client.post("/dividends", json=payload)
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_approve_success(self, client, mock_capital_service):
        payload = {"dividend_id": str(uuid4())}
        response = client.post("/dividends/approve", json=payload)
        assert response.status_code == status.HTTP_204_NO_CONTENT
        call_args = mock_capital_service.approve_dividend.call_args
        assert call_args is not None
        assert call_args.kwargs["dividend_id"] == payload["dividend_id"]

    def test_approve_service_error(self, client, mock_capital_service):
        mock_capital_service.approve_dividend.side_effect = Exception("Error")
        payload = {"dividend_id": str(uuid4())}
        response = client.post("/dividends/approve", json=payload)
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_pay_success(self, client, mock_capital_service):
        payload = {
            "dividend_id": str(uuid4()),
            "amount": "500000",
            "is_full": True,
        }
        response = client.post("/dividends/pay", json=payload)
        assert response.status_code == status.HTTP_204_NO_CONTENT
        mock_capital_service.pay_dividend.assert_awaited_once()

    def test_pay_service_error(self, client, mock_capital_service):
        mock_capital_service.pay_dividend.side_effect = Exception("Error")
        payload = {"dividend_id": str(uuid4()), "amount": "100", "is_full": False}
        response = client.post("/dividends/pay", json=payload)
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_cancel_success(self, client, mock_capital_service):
        payload = {"dividend_id": str(uuid4()), "reason": "Cancelled"}
        response = client.post("/dividends/cancel", json=payload)
        assert response.status_code == status.HTTP_204_NO_CONTENT
        mock_capital_service.cancel_dividend.assert_awaited_once()

    def test_cancel_service_error(self, client, mock_capital_service):
        mock_capital_service.cancel_dividend.side_effect = Exception("Error")
        payload = {"dividend_id": str(uuid4()), "reason": "Test"}
        response = client.post("/dividends/cancel", json=payload)
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


# =============================================================================
# Tests for Retained Earnings Endpoints
# =============================================================================

class TestRetainedEarnings:
    def test_adjust_success(self, client, mock_capital_service):
        payload = {
            "legal_entity_id": str(uuid4()),
            "amount": "100000",
            "adjustment_date": date.today().isoformat(),
            "description": "Prior period adjustment",
        }
        response = client.post("/retained-earnings/adjust", json=payload)
        assert response.status_code == status.HTTP_204_NO_CONTENT
        mock_capital_service.adjust_retained_earnings.assert_awaited_once()

    def test_adjust_service_error(self, client, mock_capital_service):
        mock_capital_service.adjust_retained_earnings.side_effect = Exception("Error")
        payload = {
            "legal_entity_id": str(uuid4()),
            "amount": "100",
            "adjustment_date": date.today().isoformat(),
            "description": "Test",
        }
        response = client.post("/retained-earnings/adjust", json=payload)
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_transfer_success(self, client, mock_capital_service):
        payload = {
            "from_legal_entity_id": str(uuid4()),
            "to_legal_entity_id": str(uuid4()),
            "amount": "200000",
            "transfer_date": date.today().isoformat(),
        }
        response = client.post("/retained-earnings/transfer", json=payload)
        assert response.status_code == status.HTTP_204_NO_CONTENT
        mock_capital_service.transfer_retained_earnings.assert_awaited_once()

    def test_transfer_service_error(self, client, mock_capital_service):
        mock_capital_service.transfer_retained_earnings.side_effect = Exception("Error")
        payload = {
            "from_legal_entity_id": str(uuid4()),
            "to_legal_entity_id": str(uuid4()),
            "amount": "100",
            "transfer_date": date.today().isoformat(),
        }
        response = client.post("/retained-earnings/transfer", json=payload)
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_update_success(self, client, mock_capital_service):
        payload = {
            "legal_entity_id": str(uuid4()),
            "new_balance": "1500000",
            "as_of_date": date.today().isoformat(),
        }
        response = client.post("/retained-earnings/update", json=payload)
        assert response.status_code == status.HTTP_204_NO_CONTENT
        mock_capital_service.update_retained_earnings.assert_awaited_once()

    def test_update_idempotent(self, client, mock_capital_service):
        payload = {
            "legal_entity_id": str(uuid4()),
            "new_balance": "1000",
            "as_of_date": date.today().isoformat(),
        }
        response1 = client.post("/retained-earnings/update", json=payload, headers={"Idempotency-Key": "key789"})
        assert response1.status_code == status.HTTP_204_NO_CONTENT
        response2 = client.post("/retained-earnings/update", json=payload, headers={"Idempotency-Key": "key789"})
        assert response2.status_code == status.HTTP_204_NO_CONTENT
        assert mock_capital_service.update_retained_earnings.call_count == 1

    def test_update_service_error(self, client, mock_capital_service):
        mock_capital_service.update_retained_earnings.side_effect = Exception("Error")
        payload = {
            "legal_entity_id": str(uuid4()),
            "new_balance": "100",
            "as_of_date": date.today().isoformat(),
        }
        response = client.post("/retained-earnings/update", json=payload)
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


# =============================================================================
# Tests for Stats Endpoint
# =============================================================================

class TestStats:
    def test_get_stats_success(self, client, mock_capital_service):
        response = client.get("/stats")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "total_contributions" in data
        assert data["total_contributions"] == 10
        assert data["total_dividends"] == 5
        mock_capital_service.get_stats.assert_called_once()

    def test_get_stats_service_error(self, client, mock_capital_service):
        mock_capital_service.get_stats.side_effect = Exception("Error")
        response = client.get("/stats")
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
