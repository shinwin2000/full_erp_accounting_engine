# tests/adapters/primary_api/v1/test_fastapi_customer_router.py
# Perbaikan kualitas assertions: mengganti semua assert True dengan
# assertion yang memeriksa nilai aktual, efek samping, dan interaksi mock.

import json
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from adapters.primary_api.v1.fastapi_customer_router import (
    CreateCustomerRequest,
    CustomerResponseModel,
    CustomerStatusEnum,
    IdempotencyManager,
    UpdateBalanceRequest,
    UpdateCreditLimitRequest,
    UpdateCustomerRequest,
    router,
    _idempotency_manager,
    get_correlation_id,
    to_customer_response,
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
        storage_key = manager._get_key(key, method)
        # Simulate expiration by setting timestamp older than TTL
        old_time = datetime.now() - timedelta(seconds=manager._ttl_seconds + 10)
        manager._storage[storage_key] = (manager._storage[storage_key][0], old_time)
        cached = manager.get_cached_result(key, method)
        assert cached is None
        assert storage_key not in manager._storage

    def test_cache_result_fallback(self):
        manager = IdempotencyManager()
        class NonSerializable:
            pass
        manager.cache_result("key", "method", {"data": NonSerializable()})
        cached = manager.get_cached_result("key", "method")
        assert cached is not None
        assert "result" in cached  # fallback dict


# ============================================================================
# Enum tests
# ============================================================================
class TestCustomerStatusEnum:
    def test_members(self):
        expected = ["ACTIVE", "INACTIVE", "SUSPENDED", "BLACKLISTED"]
        for name in expected:
            assert hasattr(CustomerStatusEnum, name)
        assert CustomerStatusEnum.ACTIVE.value == "active"


# ============================================================================
# Pydantic model tests
# ============================================================================
class TestCreateCustomerRequest:
    def test_construction(self):
        le_id = uuid4()
        data = {
            "legal_entity_id": le_id,
            "customer_code": "CUST001",
            "name": "PT ABC",
            "npwp": "123456789012345",
            "address": "Jl. Merdeka 10",
            "city": "Jakarta",
            "country": "ID",
            "phone": "08123456789",
            "email": "info@abc.com",
            "contact_person": "John Doe",
            "credit_limit": Decimal("1000000"),
        }
        model = CreateCustomerRequest(**data)
        assert model.legal_entity_id == le_id
        assert model.customer_code == "CUST001"
        assert model.name == "PT ABC"
        assert model.credit_limit == Decimal("1000000")


class TestUpdateCustomerRequest:
    def test_construction(self):
        data = {
            "name": "PT ABC Updated",
            "address": "Jl. Merdeka 20",
            "city": "Bandung",
            "phone": "08123456788",
            "email": "info@abc.com",
            "contact_person": "Jane Doe",
            "is_active": False,
            "status": CustomerStatusEnum.SUSPENDED,
        }
        model = UpdateCustomerRequest(**data)
        assert model.name == "PT ABC Updated"
        assert model.status == CustomerStatusEnum.SUSPENDED
        assert model.is_active is False


class TestCustomerResponseModel:
    def test_construction(self):
        now = datetime.now()
        data = {
            "id": uuid4(),
            "legal_entity_id": uuid4(),
            "customer_code": "C001",
            "name": "PT ABC",
            "npwp": "123",
            "address": "Jl. Merdeka",
            "city": "Jakarta",
            "country": "ID",
            "phone": "081",
            "email": "info@abc.com",
            "contact_person": "John",
            "credit_limit": Decimal("1000000"),
            "current_balance": Decimal("500000"),
            "is_active": True,
            "status": "active",
            "created_at": now,
            "updated_at": now,
            "created_by": uuid4(),
            "version": 1,
        }
        model = CustomerResponseModel(**data)
        assert model.customer_code == "C001"
        assert model.current_balance == Decimal("500000")


class TestUpdateCreditLimitRequest:
    def test_construction(self):
        data = {"new_limit": Decimal("2000000")}
        model = UpdateCreditLimitRequest(**data)
        assert model.new_limit == Decimal("2000000")


class TestUpdateBalanceRequest:
    def test_construction(self):
        data = {"delta": Decimal("-50000")}
        model = UpdateBalanceRequest(**data)
        assert model.delta == Decimal("-50000")


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
    assert len(result) == 36  # UUID format


# ============================================================================
# to_customer_response helper
# ============================================================================
def test_to_customer_response():
    now = datetime.now()
    customer = MagicMock()
    customer.id = uuid4()
    customer.legal_entity_id = uuid4()
    customer.customer_code = "C001"
    customer.name = "PT ABC"
    customer.npwp = "123"
    customer.address = "Jl. Merdeka"
    customer.city = "Jakarta"
    customer.country = "ID"
    customer.phone = "081"
    customer.email = "info@abc.com"
    customer.contact_person = "John"
    customer.credit_limit = Decimal("1000000")
    customer.current_balance = Decimal("500000")
    customer.is_active = True
    customer.status = "active"
    customer.created_at = now
    customer.updated_at = now
    customer.created_by = uuid4()
    customer.version = 1

    response = to_customer_response(customer)
    assert response.customer_code == "C001"
    assert response.name == "PT ABC"
    assert response.credit_limit == Decimal("1000000")


# ============================================================================
# FastAPI endpoint tests with TestClient
# ============================================================================
@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture
def mock_customer_service():
    with patch("adapters.primary_api.v1.fastapi_customer_router.get_service") as mock_get:
        mock_service = AsyncMock()
        mock_get.return_value = mock_service
        yield mock_service


@pytest.fixture
def mock_current_user():
    with patch("adapters.primary_api.v1.fastapi_customer_router.get_current_user") as mock:
        mock.return_value = MagicMock(user_id=uuid4())
        yield mock


@pytest.fixture
def mock_idempotency():
    with patch("adapters.primary_api.v1.fastapi_customer_router._idempotency_manager") as mock:
        mock.get_cached_result.return_value = None
        mock.cache_result.return_value = None
        yield mock


# ----------------------------------------------------------------------------
# create_customer
# ----------------------------------------------------------------------------
def test_create_customer_success(client, mock_customer_service, mock_current_user, mock_idempotency):
    le_id = uuid4()
    cust_id = uuid4()
    now = datetime.now()

    # Mock service response
    mock_customer = MagicMock()
    mock_customer.id = cust_id
    mock_customer.legal_entity_id = le_id
    mock_customer.customer_code = "C001"
    mock_customer.name = "PT ABC"
    mock_customer.npwp = "123"
    mock_customer.address = "Jl. Merdeka"
    mock_customer.city = "Jakarta"
    mock_customer.country = "ID"
    mock_customer.phone = "081"
    mock_customer.email = "info@abc.com"
    mock_customer.contact_person = "John"
    mock_customer.credit_limit = Decimal("1000000")
    mock_customer.current_balance = Decimal("0")
    mock_customer.is_active = True
    mock_customer.status = "active"
    mock_customer.created_at = now
    mock_customer.updated_at = now
    mock_customer.created_by = uuid4()
    mock_customer.version = 1
    mock_customer_service.create_customer.return_value = mock_customer

    payload = {
        "legal_entity_id": str(le_id),
        "customer_code": "C001",
        "name": "PT ABC",
        "npwp": "123",
        "address": "Jl. Merdeka",
        "city": "Jakarta",
        "country": "ID",
        "phone": "081",
        "email": "info@abc.com",
        "contact_person": "John",
        "credit_limit": "1000000",
    }
    response = client.post("/customers", json=payload, headers={"Idempotency-Key": "idem123"})
    assert response.status_code == 201
    data = response.json()
    assert data["id"] == str(cust_id)
    assert data["customer_code"] == "C001"
    assert data["credit_limit"] == "1000000"
    mock_customer_service.create_customer.assert_awaited_once()
    mock_idempotency.cache_result.assert_called_once()

def test_create_customer_idempotent(client, mock_customer_service, mock_current_user, mock_idempotency):
    le_id = uuid4()
    cached_response = {
        "id": str(uuid4()),
        "legal_entity_id": str(le_id),
        "customer_code": "C001",
        "name": "PT ABC",
        "npwp": "123",
        "address": "Jl. Merdeka",
        "city": "Jakarta",
        "country": "ID",
        "phone": "081",
        "email": "info@abc.com",
        "contact_person": "John",
        "credit_limit": "1000000",
        "current_balance": "0",
        "is_active": True,
        "status": "active",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "created_by": str(uuid4()),
        "version": 1,
    }
    mock_idempotency.get_cached_result.return_value = cached_response

    payload = {
        "legal_entity_id": str(le_id),
        "customer_code": "C001",
        "name": "PT ABC",
    }
    response = client.post("/customers", json=payload, headers={"Idempotency-Key": "idem123"})
    assert response.status_code == 201
    data = response.json()
    assert data["id"] == cached_response["id"]
    mock_customer_service.create_customer.assert_not_awaited()

def test_create_customer_service_error(client, mock_customer_service, mock_current_user):
    le_id = uuid4()
    from application.service_layer.service_customer import CustomerServiceError
    mock_customer_service.create_customer.side_effect = CustomerServiceError("Duplicate customer code")

    payload = {
        "legal_entity_id": str(le_id),
        "customer_code": "C001",
        "name": "PT ABC",
    }
    response = client.post("/customers", json=payload)
    assert response.status_code == 400
    assert "Duplicate customer code" in response.text


# ----------------------------------------------------------------------------
# get_customer
# ----------------------------------------------------------------------------
def test_get_customer_success(client, mock_customer_service, mock_current_user):
    cust_id = uuid4()
    le_id = uuid4()
    now = datetime.now()

    mock_customer = MagicMock()
    mock_customer.id = cust_id
    mock_customer.legal_entity_id = le_id
    mock_customer.customer_code = "C001"
    mock_customer.name = "PT ABC"
    mock_customer.npwp = "123"
    mock_customer.address = "Jl. Merdeka"
    mock_customer.city = "Jakarta"
    mock_customer.country = "ID"
    mock_customer.phone = "081"
    mock_customer.email = "info@abc.com"
    mock_customer.contact_person = "John"
    mock_customer.credit_limit = Decimal("1000000")
    mock_customer.current_balance = Decimal("0")
    mock_customer.is_active = True
    mock_customer.status = "active"
    mock_customer.created_at = now
    mock_customer.updated_at = now
    mock_customer.created_by = uuid4()
    mock_customer.version = 1
    mock_customer_service.get_customer.return_value = mock_customer

    response = client.get(f"/customers/{cust_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(cust_id)
    assert data["customer_code"] == "C001"

def test_get_customer_not_found(client, mock_customer_service, mock_current_user):
    mock_customer_service.get_customer.return_value = None
    response = client.get(f"/customers/{uuid4()}")
    assert response.status_code == 404
    assert "not found" in response.text.lower()


# ----------------------------------------------------------------------------
# list_customers
# ----------------------------------------------------------------------------
def test_list_customers_success(client, mock_customer_service, mock_current_user):
    le_id = uuid4()
    now = datetime.now()
    mock_customer = MagicMock()
    mock_customer.id = uuid4()
    mock_customer.legal_entity_id = le_id
    mock_customer.customer_code = "C001"
    mock_customer.name = "PT ABC"
    mock_customer.npwp = "123"
    mock_customer.address = "Jl. Merdeka"
    mock_customer.city = "Jakarta"
    mock_customer.country = "ID"
    mock_customer.phone = "081"
    mock_customer.email = "info@abc.com"
    mock_customer.contact_person = "John"
    mock_customer.credit_limit = Decimal("1000000")
    mock_customer.current_balance = Decimal("0")
    mock_customer.is_active = True
    mock_customer.status = "active"
    mock_customer.created_at = now
    mock_customer.updated_at = now
    mock_customer.created_by = uuid4()
    mock_customer.version = 1
    mock_customer_service.list_customers.return_value = [mock_customer]

    response = client.get(f"/customers?legal_entity_id={le_id}&limit=10&offset=0")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["customer_code"] == "C001"


# ----------------------------------------------------------------------------
# update_customer
# ----------------------------------------------------------------------------
def test_update_customer_success(client, mock_customer_service, mock_current_user, mock_idempotency):
    cust_id = uuid4()
    le_id = uuid4()
    now = datetime.now()
    mock_customer = MagicMock()
    mock_customer.id = cust_id
    mock_customer.legal_entity_id = le_id
    mock_customer.customer_code = "C001"
    mock_customer.name = "PT ABC Updated"
    mock_customer.npwp = "123"
    mock_customer.address = "Jl. Merdeka 20"
    mock_customer.city = "Jakarta"
    mock_customer.country = "ID"
    mock_customer.phone = "081"
    mock_customer.email = "info@abc.com"
    mock_customer.contact_person = "John"
    mock_customer.credit_limit = Decimal("1000000")
    mock_customer.current_balance = Decimal("0")
    mock_customer.is_active = True
    mock_customer.status = "active"
    mock_customer.created_at = now
    mock_customer.updated_at = now
    mock_customer.created_by = uuid4()
    mock_customer.version = 2
    mock_customer_service.update_customer.return_value = mock_customer

    payload = {"name": "PT ABC Updated", "address": "Jl. Merdeka 20"}
    response = client.patch(f"/customers/{cust_id}", json=payload, headers={"Idempotency-Key": "idem123"})
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "PT ABC Updated"
    mock_customer_service.update_customer.assert_awaited_once()
    mock_idempotency.cache_result.assert_called_once()

def test_update_customer_not_found(client, mock_customer_service, mock_current_user):
    from application.service_layer.service_customer import CustomerNotFoundError
    mock_customer_service.update_customer.side_effect = CustomerNotFoundError("not found")
    payload = {"name": "New Name"}
    response = client.patch(f"/customers/{uuid4()}", json=payload)
    assert response.status_code == 404


# ----------------------------------------------------------------------------
# deactivate_customer
# ----------------------------------------------------------------------------
def test_deactivate_customer_success(client, mock_customer_service, mock_current_user, mock_idempotency):
    cust_id = uuid4()
    mock_customer = MagicMock()
    mock_customer.id = cust_id
    mock_customer_service.get_customer.return_value = mock_customer
    mock_customer_service.update_customer.return_value = mock_customer

    response = client.post(f"/customers/{cust_id}/deactivate", headers={"Idempotency-Key": "idem123"})
    assert response.status_code == 204
    mock_customer_service.update_customer.assert_awaited_once_with(
        customer_id=cust_id,
        is_active=False,
        updated_by=mock_current_user.return_value.user_id,
        correlation_id=response.request.headers.get("X-Correlation-ID")
    )
    mock_idempotency.cache_result.assert_called_once()

def test_deactivate_customer_idempotent(client, mock_customer_service, mock_current_user, mock_idempotency):
    mock_idempotency.get_cached_result.return_value = {"status": "success", "customer_id": str(uuid4())}
    response = client.post(f"/customers/{uuid4()}/deactivate", headers={"Idempotency-Key": "idem123"})
    assert response.status_code == 204
    mock_customer_service.update_customer.assert_not_awaited()


# ----------------------------------------------------------------------------
# activate_customer
# ----------------------------------------------------------------------------
def test_activate_customer_success(client, mock_customer_service, mock_current_user):
    cust_id = uuid4()
    mock_customer = MagicMock()
    mock_customer.id = cust_id
    mock_customer_service.get_customer.return_value = mock_customer
    mock_customer_service.update_customer.return_value = mock_customer

    response = client.post(f"/customers/{cust_id}/activate", headers={"Idempotency-Key": "idem123"})
    assert response.status_code == 204
    mock_customer_service.update_customer.assert_awaited_once_with(
        customer_id=cust_id,
        is_active=True,
        updated_by=mock_current_user.return_value.user_id,
        correlation_id=response.request.headers.get("X-Correlation-ID")
    )


# ----------------------------------------------------------------------------
# change_customer_status
# ----------------------------------------------------------------------------
def test_change_customer_status_success(client, mock_customer_service, mock_current_user):
    cust_id = uuid4()
    le_id = uuid4()
    now = datetime.now()
    mock_customer = MagicMock()
    mock_customer.id = cust_id
    mock_customer.legal_entity_id = le_id
    mock_customer.customer_code = "C001"
    mock_customer.name = "PT ABC"
    mock_customer.npwp = "123"
    mock_customer.address = "Jl. Merdeka"
    mock_customer.city = "Jakarta"
    mock_customer.country = "ID"
    mock_customer.phone = "081"
    mock_customer.email = "info@abc.com"
    mock_customer.contact_person = "John"
    mock_customer.credit_limit = Decimal("1000000")
    mock_customer.current_balance = Decimal("0")
    mock_customer.is_active = True
    mock_customer.status = "suspended"
    mock_customer.created_at = now
    mock_customer.updated_at = now
    mock_customer.created_by = uuid4()
    mock_customer.version = 1
    mock_customer_service.update_customer.return_value = mock_customer

    payload = {"status": "SUSPENDED"}
    response = client.post(f"/customers/{cust_id}/status", json=payload, headers={"Idempotency-Key": "idem123"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "suspended"


# ----------------------------------------------------------------------------
# update_credit_limit
# ----------------------------------------------------------------------------
def test_update_credit_limit_success(client, mock_customer_service, mock_current_user):
    cust_id = uuid4()
    le_id = uuid4()
    now = datetime.now()
    mock_customer = MagicMock()
    mock_customer.id = cust_id
    mock_customer.legal_entity_id = le_id
    mock_customer.customer_code = "C001"
    mock_customer.name = "PT ABC"
    mock_customer.npwp = "123"
    mock_customer.address = "Jl. Merdeka"
    mock_customer.city = "Jakarta"
    mock_customer.country = "ID"
    mock_customer.phone = "081"
    mock_customer.email = "info@abc.com"
    mock_customer.contact_person = "John"
    mock_customer.credit_limit = Decimal("2000000")
    mock_customer.current_balance = Decimal("0")
    mock_customer.is_active = True
    mock_customer.status = "active"
    mock_customer.created_at = now
    mock_customer.updated_at = now
    mock_customer.created_by = uuid4()
    mock_customer.version = 1
    mock_customer_service.update_credit_limit.return_value = mock_customer

    payload = {"new_limit": "2000000"}
    response = client.post(f"/customers/{cust_id}/credit-limit", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["credit_limit"] == "2000000"
    mock_customer_service.update_credit_limit.assert_awaited_once_with(
        customer_id=cust_id,
        new_limit=Decimal("2000000"),
        updated_by=mock_current_user.return_value.user_id,
        correlation_id=response.request.headers.get("X-Correlation-ID")
    )


# ----------------------------------------------------------------------------
# update_balance
# ----------------------------------------------------------------------------
def test_update_balance_success(client, mock_customer_service, mock_current_user):
    cust_id = uuid4()
    mock_customer_service.update_balance.return_value = Decimal("500000")

    payload = {"delta": "50000"}
    response = client.post(f"/customers/{cust_id}/balance", json=payload, headers={"Idempotency-Key": "idem123"})
    assert response.status_code == 200
    data = response.json()
    assert data["new_balance"] == "500000"
    mock_customer_service.update_balance.assert_awaited_once()

def test_update_balance_not_found(client, mock_customer_service, mock_current_user):
    from application.service_layer.service_customer import CustomerNotFoundError
    mock_customer_service.update_balance.side_effect = CustomerNotFoundError("not found")
    payload = {"delta": "1000"}
    response = client.post(f"/customers/{uuid4()}/balance", json=payload)
    assert response.status_code == 404


# ----------------------------------------------------------------------------
# get_balance
# ----------------------------------------------------------------------------
def test_get_balance_success(client, mock_customer_service, mock_current_user):
    cust_id = uuid4()
    mock_customer = MagicMock()
    mock_customer.current_balance = Decimal("750000")
    mock_customer_service.get_customer.return_value = mock_customer

    response = client.get(f"/customers/{cust_id}/balance")
    assert response.status_code == 200
    data = response.json()
    assert data["current_balance"] == "750000"

def test_get_balance_not_found(client, mock_customer_service, mock_current_user):
    mock_customer_service.get_customer.return_value = None
    response = client.get(f"/customers/{uuid4()}/balance")
    assert response.status_code == 404


# ----------------------------------------------------------------------------
# get_customer_stats
# ----------------------------------------------------------------------------
def test_get_customer_stats_success(client, mock_customer_service, mock_current_user):
    mock_customer_service.get_stats.return_value = {"total_customers": 10, "active": 8}
    response = client.get("/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["total_customers"] == 10
    assert data["active"] == 8