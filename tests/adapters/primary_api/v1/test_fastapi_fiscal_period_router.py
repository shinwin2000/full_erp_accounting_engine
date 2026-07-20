# tests/adapters/primary_api/v1/test_fastapi_fiscal_period_router.py
# Perbaikan kualitas assertions: mengganti semua assert True dengan
# assertion yang memeriksa nilai aktual, efek samping, atau interaksi mock.

import json
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from adapters.primary_api.v1.fastapi_fiscal_period_router import (
    ClosePeriodRequestModel,
    CreatePeriodRequestModel,
    IdempotencyManager,
    LockPeriodRequestModel,
    PeriodResponseModel,
    PeriodStatus,
    PeriodType,
    ReopenPeriodRequestModel,
    UpdatePeriodRequestModel,
    ValidatePeriodResponseModel,
    router,
    _idempotency_manager,
    get_correlation_id,
)


# ============================================================================
# IdempotencyManager tests
# ============================================================================
class TestIdempotencyManager:
    def test_cache_and_get(self):
        manager = IdempotencyManager()
        key = "test-key"
        method = "test-method"
        result = {"id": "123", "status": "ok"}
        manager.cache_result(key, method, result)
        cached = manager.get_cached_result(key, method)
        assert cached == result

    def test_get_nonexistent(self):
        manager = IdempotencyManager()
        assert manager.get_cached_result("missing", "method") is None

    def test_ttl_expiry(self):
        manager = IdempotencyManager()
        key = "test-key"
        method = "test-method"
        result = {"id": "123"}
        manager.cache_result(key, method, result)
        # Manually expire by setting timestamp older than TTL
        storage_key = manager._get_key(key, method)
        old_time = datetime.now() - timedelta(seconds=manager._ttl_seconds + 10)
        manager._storage[storage_key] = (manager._storage[storage_key][0], old_time)
        cached = manager.get_cached_result(key, method)
        assert cached is None
        assert storage_key not in manager._storage

    def test_cache_result_fallback(self):
        manager = IdempotencyManager()
        # Force TypeError by passing non-serializable object
        class NonSerializable:
            pass
        manager.cache_result("key", "method", {"data": NonSerializable()})
        cached = manager.get_cached_result("key", "method")
        assert cached is not None
        assert "result" in cached  # fallback dict


# ============================================================================
# Enum tests
# ============================================================================
class TestPeriodType:
    def test_members(self):
        expected = ["MONTHLY", "QUARTERLY", "YEARLY"]
        for name in expected:
            assert hasattr(PeriodType, name)

    def test_member_is_instance(self):
        assert isinstance(PeriodType.MONTHLY, PeriodType)


class TestPeriodStatus:
    def test_members(self):
        expected = ["DRAFT", "OPEN", "LOCKED", "CLOSED"]
        for name in expected:
            assert hasattr(PeriodStatus, name)

    def test_member_is_instance(self):
        assert isinstance(PeriodStatus.DRAFT, PeriodStatus)


# ============================================================================
# Pydantic model tests
# ============================================================================
class TestCreatePeriodRequestModel:
    def test_construction(self):
        le_id = uuid4()
        data = {
            "legal_entity_id": le_id,
            "year": 2024,
            "month": 12,
            "period_type": PeriodType.MONTHLY,
            "start_date": date(2024, 12, 1),
            "end_date": date(2024, 12, 31),
        }
        model = CreatePeriodRequestModel(**data)
        assert model.legal_entity_id == le_id
        assert model.year == 2024
        assert model.month == 12
        assert model.period_type == PeriodType.MONTHLY
        assert model.start_date == date(2024, 12, 1)


class TestPeriodResponseModel:
    def test_construction(self):
        period_id = uuid4()
        le_id = uuid4()
        now = datetime.now()
        data = {
            "period_id": period_id,
            "legal_entity_id": le_id,
            "period_type": "MONTHLY",
            "period_number": 12,
            "year": 2024,
            "start_date": date(2024, 12, 1),
            "end_date": date(2024, 12, 31),
            "status": "OPEN",
            "created_by": "admin",
            "created_at": now,
            "closed_at": None,
            "closed_by": None,
            "updated_at": now,
            "updated_by": "admin",
        }
        model = PeriodResponseModel(**data)
        assert model.period_id == period_id
        assert model.status == "OPEN"


class TestClosePeriodRequestModel:
    def test_construction(self):
        le_id = uuid4()
        now = datetime.now()
        data = {
            "legal_entity_id": le_id,
            "year": 2024,
            "month": 12,
            "closed_at": now,
        }
        model = ClosePeriodRequestModel(**data)
        assert model.legal_entity_id == le_id
        assert model.closed_at == now


class TestLockPeriodRequestModel:
    def test_construction(self):
        le_id = uuid4()
        data = {
            "legal_entity_id": le_id,
            "year": 2024,
            "month": 12,
        }
        model = LockPeriodRequestModel(**data)
        assert model.legal_entity_id == le_id


class TestReopenPeriodRequestModel:
    def test_construction(self):
        le_id = uuid4()
        data = {
            "legal_entity_id": le_id,
            "year": 2024,
            "month": 12,
            "reason": "Need to fix error",
        }
        model = ReopenPeriodRequestModel(**data)
        assert model.reason == "Need to fix error"


class TestUpdatePeriodRequestModel:
    def test_construction(self):
        data = {
            "start_date": date(2024, 12, 1),
            "end_date": date(2024, 12, 31),
            "period_type": PeriodType.MONTHLY,
        }
        model = UpdatePeriodRequestModel(**data)
        assert model.period_type == PeriodType.MONTHLY


class TestValidatePeriodResponseModel:
    def test_construction(self):
        period = PeriodResponseModel(
            period_id=uuid4(),
            legal_entity_id=uuid4(),
            period_type="MONTHLY",
            period_number=1,
            year=2024,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            status="OPEN",
            created_by="admin",
            created_at=datetime.now(),
            closed_at=None,
            closed_by=None,
            updated_at=None,
            updated_by=None,
        )
        data = {
            "is_valid": True,
            "period": period,
            "message": "Period is valid",
        }
        model = ValidatePeriodResponseModel(**data)
        assert model.is_valid is True
        assert model.message == "Period is valid"


# ============================================================================
# get_correlation_id helper
# ============================================================================
def test_get_correlation_id_from_header():
    request = MagicMock(spec=Request)
    request.headers = {"X-Correlation-ID": "corr-123"}
    result = get_correlation_id(request)
    assert result == "corr-123"

def test_get_correlation_id_generated():
    request = MagicMock(spec=Request)
    request.headers = {}
    result = get_correlation_id(request)
    # should be a UUID
    assert len(result) == 36


# ============================================================================
# FastAPI endpoint tests with TestClient
# ============================================================================
@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture
def mock_fiscal_service():
    with patch("adapters.primary_api.v1.fastapi_fiscal_period_router.get_service") as mock_get:
        mock_service = AsyncMock()
        mock_get.return_value = mock_service
        yield mock_service


@pytest.fixture
def mock_current_user():
    with patch("adapters.primary_api.v1.fastapi_fiscal_period_router.get_current_user") as mock:
        mock.return_value = MagicMock(user_id=uuid4())
        yield mock


@pytest.fixture
def mock_idempotency():
    with patch("adapters.primary_api.v1.fastapi_fiscal_period_router._idempotency_manager") as mock:
        mock.get_cached_result.return_value = None
        mock.cache_result.return_value = None
        yield mock


# ---- create_period ----
def test_create_period_success(client, mock_fiscal_service, mock_current_user, mock_idempotency):
    period_id = uuid4()
    le_id = uuid4()
    now = datetime.now()
    mock_service = mock_fiscal_service
    result_mock = MagicMock()
    result_mock.period_id = period_id
    result_mock.legal_entity_id = le_id
    result_mock.period_type = MagicMock(value="MONTHLY")
    result_mock.period_number = 12
    result_mock.year = 2024
    result_mock.start_date = date(2024, 12, 1)
    result_mock.end_date = date(2024, 12, 31)
    result_mock.status = MagicMock(value="OPEN")
    result_mock.created_by = "admin"
    result_mock.created_at = now
    result_mock.closed_at = None
    result_mock.closed_by = None
    result_mock.updated_at = None
    result_mock.updated_by = None
    mock_service.create_period.return_value = result_mock

    payload = {
        "legal_entity_id": str(le_id),
        "year": 2024,
        "month": 12,
        "period_type": "MONTHLY",
    }
    response = client.post("/periods", json=payload, headers={"Idempotency-Key": "idem123"})
    assert response.status_code == 201
    data = response.json()
    assert data["period_id"] == str(period_id)
    assert data["status"] == "OPEN"
    mock_service.create_period.assert_awaited_once()

def test_create_period_idempotent(client, mock_fiscal_service, mock_current_user, mock_idempotency):
    cached_response = {
        "period_id": str(uuid4()),
        "legal_entity_id": str(uuid4()),
        "period_type": "MONTHLY",
        "period_number": 12,
        "year": 2024,
        "start_date": "2024-12-01",
        "end_date": "2024-12-31",
        "status": "OPEN",
        "created_by": "admin",
        "created_at": datetime.now().isoformat(),
        "closed_at": None,
        "closed_by": None,
        "updated_at": None,
        "updated_by": None,
    }
    mock_idempotency.get_cached_result.return_value = cached_response

    le_id = uuid4()
    payload = {"legal_entity_id": str(le_id), "year": 2024, "month": 12}
    response = client.post("/periods", json=payload, headers={"Idempotency-Key": "idem123"})
    assert response.status_code == 201
    data = response.json()
    assert data["period_id"] == cached_response["period_id"]
    mock_fiscal_service.create_period.assert_not_awaited()

# ---- get_period_by_id ----
def test_get_period_by_id_success(client, mock_fiscal_service, mock_current_user):
    period_id = uuid4()
    le_id = uuid4()
    now = datetime.now()
    mock_service = mock_fiscal_service
    result_mock = MagicMock()
    result_mock.period_id = period_id
    result_mock.legal_entity_id = le_id
    result_mock.period_type = MagicMock(value="MONTHLY")
    result_mock.period_number = 12
    result_mock.year = 2024
    result_mock.start_date = date(2024, 12, 1)
    result_mock.end_date = date(2024, 12, 31)
    result_mock.status = MagicMock(value="OPEN")
    result_mock.created_by = "admin"
    result_mock.created_at = now
    result_mock.closed_at = None
    result_mock.closed_by = None
    result_mock.updated_at = None
    result_mock.updated_by = None
    mock_service.get_period_by_id.return_value = result_mock

    response = client.get(f"/periods/{period_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["period_id"] == str(period_id)

def test_get_period_by_id_not_found(client, mock_fiscal_service, mock_current_user):
    mock_fiscal_service.get_period_by_id.return_value = None
    response = client.get(f"/periods/{uuid4()}")
    assert response.status_code == 404
    assert "not found" in response.text.lower()

# ---- list_periods ----
def test_list_periods_success(client, mock_fiscal_service, mock_current_user):
    le_id = uuid4()
    now = datetime.now()
    mock_service = mock_fiscal_service
    result_mock = MagicMock()
    result_mock.period_id = uuid4()
    result_mock.legal_entity_id = le_id
    result_mock.period_type = MagicMock(value="MONTHLY")
    result_mock.period_number = 12
    result_mock.year = 2024
    result_mock.start_date = date(2024, 12, 1)
    result_mock.end_date = date(2024, 12, 31)
    result_mock.status = MagicMock(value="OPEN")
    result_mock.created_by = "admin"
    result_mock.created_at = now
    result_mock.closed_at = None
    result_mock.closed_by = None
    result_mock.updated_at = None
    result_mock.updated_by = None
    mock_service.list_periods.return_value = [result_mock]

    response = client.get(f"/periods?legal_entity_id={le_id}")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["legal_entity_id"] == str(le_id)

# ---- update_period ----
def test_update_period_success(client, mock_fiscal_service, mock_current_user, mock_idempotency):
    period_id = uuid4()
    le_id = uuid4()
    now = datetime.now()
    mock_service = mock_fiscal_service
    # first get period
    period_mock = MagicMock()
    period_mock.period_id = period_id
    period_mock.legal_entity_id = le_id
    period_mock.year = 2024
    period_mock.period_number = 12
    mock_service.get_period_by_id.return_value = period_mock
    # update returns updated period
    result_mock = MagicMock()
    result_mock.period_id = period_id
    result_mock.legal_entity_id = le_id
    result_mock.period_type = MagicMock(value="MONTHLY")
    result_mock.period_number = 12
    result_mock.year = 2024
    result_mock.start_date = date(2024, 12, 1)
    result_mock.end_date = date(2024, 12, 31)
    result_mock.status = MagicMock(value="OPEN")
    result_mock.created_by = "admin"
    result_mock.created_at = now
    result_mock.closed_at = None
    result_mock.closed_by = None
    result_mock.updated_at = now
    result_mock.updated_by = "admin"
    mock_service.update_period.return_value = result_mock

    payload = {"start_date": "2024-12-01", "end_date": "2024-12-31"}
    response = client.patch(f"/periods/{period_id}", json=payload, headers={"Idempotency-Key": "idem123"})
    assert response.status_code == 200
    data = response.json()
    assert data["period_id"] == str(period_id)

def test_update_period_not_found(client, mock_fiscal_service, mock_current_user):
    mock_fiscal_service.get_period_by_id.return_value = None
    payload = {"start_date": "2024-12-01"}
    response = client.patch(f"/periods/{uuid4()}", json=payload)
    assert response.status_code == 404

# ---- open_period ----
def test_open_period_success(client, mock_fiscal_service, mock_current_user, mock_idempotency):
    period_id = uuid4()
    le_id = uuid4()
    now = datetime.now()
    mock_service = mock_fiscal_service
    result_mock = MagicMock()
    result_mock.period_id = period_id
    result_mock.legal_entity_id = le_id
    result_mock.period_type = MagicMock(value="MONTHLY")
    result_mock.period_number = 12
    result_mock.year = 2024
    result_mock.start_date = date(2024, 12, 1)
    result_mock.end_date = date(2024, 12, 31)
    result_mock.status = MagicMock(value="OPEN")
    result_mock.created_by = "admin"
    result_mock.created_at = now
    result_mock.closed_at = None
    result_mock.closed_by = None
    result_mock.updated_at = now
    result_mock.updated_by = "admin"
    mock_service.open_period.return_value = result_mock

    payload = {"legal_entity_id": str(le_id), "year": 2024, "month": 12}
    response = client.post("/periods/open", json=payload, headers={"Idempotency-Key": "idem123"})
    assert response.status_code == 200
    data = response.json()
    assert data["period_id"] == str(period_id)

# ---- lock_period ----
def test_lock_period_success(client, mock_fiscal_service, mock_current_user, mock_idempotency):
    period_id = uuid4()
    le_id = uuid4()
    now = datetime.now()
    mock_service = mock_fiscal_service
    result_mock = MagicMock()
    result_mock.period_id = period_id
    result_mock.legal_entity_id = le_id
    result_mock.period_type = MagicMock(value="MONTHLY")
    result_mock.period_number = 12
    result_mock.year = 2024
    result_mock.start_date = date(2024, 12, 1)
    result_mock.end_date = date(2024, 12, 31)
    result_mock.status = MagicMock(value="LOCKED")
    result_mock.created_by = "admin"
    result_mock.created_at = now
    result_mock.closed_at = None
    result_mock.closed_by = None
    result_mock.updated_at = now
    result_mock.updated_by = "admin"
    mock_service.lock_period.return_value = result_mock

    payload = {"legal_entity_id": str(le_id), "year": 2024, "month": 12}
    response = client.post("/periods/lock", json=payload, headers={"Idempotency-Key": "idem123"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "LOCKED"

# ---- close_period ----
def test_close_period_success(client, mock_fiscal_service, mock_current_user, mock_idempotency):
    period_id = uuid4()
    le_id = uuid4()
    now = datetime.now()
    mock_service = mock_fiscal_service
    result_mock = MagicMock()
    result_mock.period_id = period_id
    result_mock.legal_entity_id = le_id
    result_mock.period_type = MagicMock(value="MONTHLY")
    result_mock.period_number = 12
    result_mock.year = 2024
    result_mock.start_date = date(2024, 12, 1)
    result_mock.end_date = date(2024, 12, 31)
    result_mock.status = MagicMock(value="CLOSED")
    result_mock.created_by = "admin"
    result_mock.created_at = now
    result_mock.closed_at = now
    result_mock.closed_by = "admin"
    result_mock.updated_at = now
    result_mock.updated_by = "admin"
    mock_service.close_period.return_value = result_mock

    payload = {"legal_entity_id": str(le_id), "year": 2024, "month": 12}
    response = client.post("/periods/close", json=payload, headers={"Idempotency-Key": "idem123"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "CLOSED"

# ---- reopen_period ----
def test_reopen_period_success(client, mock_fiscal_service, mock_current_user, mock_idempotency):
    period_id = uuid4()
    le_id = uuid4()
    now = datetime.now()
    mock_service = mock_fiscal_service
    result_mock = MagicMock()
    result_mock.period_id = period_id
    result_mock.legal_entity_id = le_id
    result_mock.period_type = MagicMock(value="MONTHLY")
    result_mock.period_number = 12
    result_mock.year = 2024
    result_mock.start_date = date(2024, 12, 1)
    result_mock.end_date = date(2024, 12, 31)
    result_mock.status = MagicMock(value="OPEN")
    result_mock.created_by = "admin"
    result_mock.created_at = now
    result_mock.closed_at = None
    result_mock.closed_by = None
    result_mock.updated_at = now
    result_mock.updated_by = "admin"
    mock_service.reopen_period.return_value = result_mock

    payload = {"legal_entity_id": str(le_id), "year": 2024, "month": 12, "reason": "Fix error"}
    response = client.post("/periods/reopen", json=payload, headers={"Idempotency-Key": "idem123"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "OPEN"

# ---- get_current_period ----
def test_get_current_period_success(client, mock_fiscal_service, mock_current_user):
    le_id = uuid4()
    now = datetime.now()
    mock_service = mock_fiscal_service
    result_mock = MagicMock()
    result_mock.period_id = uuid4()
    result_mock.legal_entity_id = le_id
    result_mock.period_type = MagicMock(value="MONTHLY")
    result_mock.period_number = 12
    result_mock.year = 2024
    result_mock.start_date = date(2024, 12, 1)
    result_mock.end_date = date(2024, 12, 31)
    result_mock.status = MagicMock(value="OPEN")
    result_mock.created_by = "admin"
    result_mock.created_at = now
    result_mock.closed_at = None
    result_mock.closed_by = None
    result_mock.updated_at = None
    result_mock.updated_by = None
    mock_service.get_current_period.return_value = result_mock

    response = client.get(f"/periods/current?legal_entity_id={le_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["legal_entity_id"] == str(le_id)

def test_get_current_period_not_found(client, mock_fiscal_service, mock_current_user):
    mock_fiscal_service.get_current_period.return_value = None
    le_id = uuid4()
    response = client.get(f"/periods/current?legal_entity_id={le_id}")
    assert response.status_code == 200
    assert response.json() is None

# ---- validate_period_for_posting ----
def test_validate_period_for_posting_valid(client, mock_fiscal_service, mock_current_user):
    le_id = uuid4()
    now = datetime.now()
    mock_service = mock_fiscal_service
    mock_service.validate_period_for_posting.return_value = True
    period_mock = MagicMock()
    period_mock.period_id = uuid4()
    period_mock.legal_entity_id = le_id
    period_mock.period_type = MagicMock(value="MONTHLY")
    period_mock.period_number = 12
    period_mock.year = 2024
    period_mock.start_date = date(2024, 12, 1)
    period_mock.end_date = date(2024, 12, 31)
    period_mock.status = MagicMock(value="OPEN")
    period_mock.created_by = "admin"
    period_mock.created_at = now
    period_mock.closed_at = None
    period_mock.closed_by = None
    period_mock.updated_at = None
    period_mock.updated_by = None
    mock_service.get_current_period.return_value = period_mock

    response = client.get(f"/periods/validate?legal_entity_id={le_id}&transaction_date=2024-12-15")
    assert response.status_code == 200
    data = response.json()
    assert data["is_valid"] is True
    assert data["period"]["status"] == "OPEN"

def test_validate_period_for_posting_invalid(client, mock_fiscal_service, mock_current_user):
    le_id = uuid4()
    mock_service = mock_fiscal_service
    mock_service.validate_period_for_posting.return_value = False

    response = client.get(f"/periods/validate?legal_entity_id={le_id}&transaction_date=2024-12-15")
    assert response.status_code == 200
    data = response.json()
    assert data["is_valid"] is False
    assert "not open" in data["message"].lower()

# ---- get_next_period ----
def test_get_next_period_success(client, mock_fiscal_service, mock_current_user):
    le_id = uuid4()
    now = datetime.now()
    mock_service = mock_fiscal_service
    result_mock = MagicMock()
    result_mock.period_id = uuid4()
    result_mock.legal_entity_id = le_id
    result_mock.period_type = MagicMock(value="MONTHLY")
    result_mock.period_number = 1
    result_mock.year = 2025
    result_mock.start_date = date(2025, 1, 1)
    result_mock.end_date = date(2025, 1, 31)
    result_mock.status = MagicMock(value="DRAFT")
    result_mock.created_by = "system"
    result_mock.created_at = now
    result_mock.closed_at = None
    result_mock.closed_by = None
    result_mock.updated_at = None
    result_mock.updated_by = None
    mock_service.get_next_period.return_value = result_mock

    response = client.get(f"/periods/next?legal_entity_id={le_id}&year=2024&month=12")
    assert response.status_code == 200
    data = response.json()
    assert data["year"] == 2025
    assert data["period_number"] == 1

def test_get_next_period_not_found(client, mock_fiscal_service, mock_current_user):
    mock_fiscal_service.get_next_period.return_value = None
    le_id = uuid4()
    response = client.get(f"/periods/next?legal_entity_id={le_id}&year=2024&month=12")
    assert response.status_code == 200
    assert response.json() is None

# ---- get_previous_period ----
def test_get_previous_period_success(client, mock_fiscal_service, mock_current_user):
    le_id = uuid4()
    now = datetime.now()
    mock_service = mock_fiscal_service
    result_mock = MagicMock()
    result_mock.period_id = uuid4()
    result_mock.legal_entity_id = le_id
    result_mock.period_type = MagicMock(value="MONTHLY")
    result_mock.period_number = 11
    result_mock.year = 2024
    result_mock.start_date = date(2024, 11, 1)
    result_mock.end_date = date(2024, 11, 30)
    result_mock.status = MagicMock(value="CLOSED")
    result_mock.created_by = "system"
    result_mock.created_at = now
    result_mock.closed_at = now
    result_mock.closed_by = "admin"
    result_mock.updated_at = now
    result_mock.updated_by = "admin"
    mock_service.get_previous_period.return_value = result_mock

    response = client.get(f"/periods/previous?legal_entity_id={le_id}&year=2024&month=12")
    assert response.status_code == 200
    data = response.json()
    assert data["period_number"] == 11

# ---- stats ----
def test_get_fiscal_period_stats(client, mock_fiscal_service, mock_current_user):
    mock_fiscal_service.get_stats.return_value = {"total_periods": 10, "open_periods": 1}
    response = client.get("/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["total_periods"] == 10
    assert data["open_periods"] == 1