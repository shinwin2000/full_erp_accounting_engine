# tests/adapters/primary_api/test_webhook_receiver_adapter.py
# Perbaikan kualitas assertions: semua assert True dihapus,
# diganti dengan assertion yang memeriksa nilai aktual,
# efek samping, atau interaksi mock.

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from adapters.primary_api.webhook_receiver_adapter import (
    IdempotencyManager,
    WebhookRouter,
    WebhookSignatureVerifier,
    router,
)


# ============================================================================
# IdempotencyManager tests
# ============================================================================
class TestIdempotencyManager:
    @pytest.fixture
    def manager(self) -> IdempotencyManager:
        return IdempotencyManager()

    async def test_is_processed_not_found(self, manager: IdempotencyManager):
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None
        with patch.object(manager, "_get_redis", return_value=mock_redis):
            processed, result = await manager.is_processed("key123")
        assert processed is False
        assert result is None
        mock_redis.get.assert_awaited_once_with("webhook:idempotent:key123")

    async def test_is_processed_found(self, manager: IdempotencyManager):
        mock_redis = AsyncMock()
        mock_redis.get.return_value = json.dumps({"status": "ok"})
        with patch.object(manager, "_get_redis", return_value=mock_redis):
            processed, result = await manager.is_processed("key123")
        assert processed is True
        assert result == {"status": "ok"}

    async def test_mark_processed(self, manager: IdempotencyManager):
        mock_redis = AsyncMock()
        with patch.object(manager, "_get_redis", return_value=mock_redis):
            await manager.mark_processed("key123", {"status": "ok"}, ttl_seconds=3600)
        mock_redis.setex.assert_awaited_once_with(
            "webhook:idempotent:key123", 3600, json.dumps({"status": "ok"})
        )


# ============================================================================
# WebhookSignatureVerifier tests
# ============================================================================
class TestWebhookSignatureVerifier:
    def test_verify_midtrans_valid(self):
        server_key = "abc123"
        order_id = "order1"
        status_code = "200"
        gross_amount = "10000"
        # compute signature as per method
        computed = hashlib.sha512(
            f"{order_id}{status_code}{gross_amount}{server_key}".encode()
        ).hexdigest()
        assert WebhookSignatureVerifier.verify_midtrans(
            computed, order_id, status_code, gross_amount, server_key
        ) is True

    def test_verify_midtrans_invalid(self):
        assert WebhookSignatureVerifier.verify_midtrans(
            "invalid", "order1", "200", "10000", "abc123"
        ) is False

    def test_verify_xendit_valid(self):
        token = "my_token"
        assert WebhookSignatureVerifier.verify_xendit(token, token) is True
        assert WebhookSignatureVerifier.verify_xendit(token, "other") is False

    def test_verify_stripe_valid(self):
        secret = "whsec_abc"
        payload = b'{"id":"evt_123"}'
        signature = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        assert WebhookSignatureVerifier.verify_stripe(signature, payload, secret) is True

    def test_verify_stripe_invalid(self):
        assert WebhookSignatureVerifier.verify_stripe(
            "invalid", b"payload", "secret"
        ) is False

    def test_verify_coretax_valid(self):
        payload = {"data": "test", "_signature": ""}
        secret = "secret"
        # compute expected
        data = json.dumps(payload, sort_keys=True)
        computed = hashlib.sha256(f"{data}{secret}".encode()).hexdigest()
        # remove _signature from payload for verification
        test_payload = {"data": "test", "_signature": computed}
        assert WebhookSignatureVerifier.verify_coretax(test_payload, secret) is True

    def test_verify_coretax_invalid(self):
        payload = {"data": "test", "_signature": "invalid"}
        assert WebhookSignatureVerifier.verify_coretax(payload, "secret") is False

    def test_verify_generic_sha256(self):
        secret = "sec"
        payload = b"hello"
        sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        assert WebhookSignatureVerifier.verify_generic(sig, payload, secret, "sha256") is True

    def test_verify_generic_sha1(self):
        secret = "sec"
        payload = b"hello"
        sig = hmac.new(secret.encode(), payload, hashlib.sha1).hexdigest()
        assert WebhookSignatureVerifier.verify_generic(sig, payload, secret, "sha1") is True

    def test_verify_generic_default(self):
        payload = b"hello"
        sig = hashlib.sha256(payload).hexdigest()
        # default algorithm just does sha256 of payload
        assert WebhookSignatureVerifier.verify_generic(sig, payload, "ignored", "other") is True
        assert WebhookSignatureVerifier.verify_generic("invalid", payload, "ignored", "other") is False


# ============================================================================
# WebhookRouter tests
# ============================================================================
class TestWebhookRouter:
    @pytest.fixture
    def router(self) -> WebhookRouter:
        return WebhookRouter()

    @pytest.fixture
    def mock_command_bus(self, router: WebhookRouter) -> AsyncMock:
        mock = AsyncMock()
        mock.dispatch.return_value = {"status": "ok"}
        router.command_bus = mock
        return mock

    # ---- payment gateway ----
    @pytest.mark.asyncio
    async def test_handle_payment_gateway_midtrans_success(
        self, router: WebhookRouter, mock_command_bus: AsyncMock
    ):
        payload = {
            "transaction_status": "settlement",
            "order_id": "ord123",
            "gross_amount": "10000",
        }
        result = await router.handle_payment_gateway("midtrans", payload)
        assert result["status"] == "processed"
        assert "command_result" in result
        mock_command_bus.dispatch.assert_awaited_once_with({
            "type": "ar.payment.create_from_webhook",
            "data": {
                "order_id": "ord123",
                "amount": "10000",
                "payment_method": "midtrans",
                "transaction_status": "settlement",
                "provider": "midtrans",
                "payload": payload,
            },
        })

    @pytest.mark.asyncio
    async def test_handle_payment_gateway_midtrans_ignored(
        self, router: WebhookRouter, mock_command_bus: AsyncMock
    ):
        payload = {"transaction_status": "pending", "order_id": "ord123"}
        result = await router.handle_payment_gateway("midtrans", payload)
        assert result["status"] == "ignored"
        assert "pending" in result["reason"]
        mock_command_bus.dispatch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_handle_payment_gateway_xendit_success(
        self, router: WebhookRouter, mock_command_bus: AsyncMock
    ):
        payload = {"id": "inv123", "status": "PAID", "amount": 20000}
        result = await router.handle_payment_gateway("xendit", payload)
        assert result["status"] == "processed"
        mock_command_bus.dispatch.assert_awaited_once_with({
            "type": "ar.payment.create_from_webhook",
            "data": {
                "invoice_id": "inv123",
                "amount": 20000,
                "payment_method": "xendit",
                "status": "PAID",
            },
        })

    @pytest.mark.asyncio
    async def test_handle_payment_gateway_xendit_ignored(
        self, router: WebhookRouter, mock_command_bus: AsyncMock
    ):
        payload = {"id": "inv123", "status": "EXPIRED"}
        result = await router.handle_payment_gateway("xendit", payload)
        assert result["status"] == "ignored"
        assert "EXPIRED" in result["reason"]
        mock_command_bus.dispatch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_handle_payment_gateway_stripe_success(
        self, router: WebhookRouter, mock_command_bus: AsyncMock
    ):
        payload = {
            "type": "payment_intent.succeeded",
            "data": {"object": {"id": "pi_123", "amount": 5000, "currency": "usd"}},
        }
        result = await router.handle_payment_gateway("stripe", payload)
        assert result["status"] == "processed"
        mock_command_bus.dispatch.assert_awaited_once_with({
            "type": "ar.payment.create_from_webhook",
            "data": {
                "payment_intent_id": "pi_123",
                "amount": 50.0,  # 5000/100
                "currency": "usd",
                "payment_method": "stripe",
            },
        })

    @pytest.mark.asyncio
    async def test_handle_payment_gateway_stripe_ignored(
        self, router: WebhookRouter, mock_command_bus: AsyncMock
    ):
        payload = {"type": "payment_intent.created"}
        result = await router.handle_payment_gateway("stripe", payload)
        assert result["status"] == "ignored"
        assert "payment_intent.created" in result["reason"]
        mock_command_bus.dispatch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_handle_payment_gateway_unsupported(
        self, router: WebhookRouter, mock_command_bus: AsyncMock
    ):
        result = await router.handle_payment_gateway("unknown", {})
        assert result["status"] == "unsupported_provider"
        mock_command_bus.dispatch.assert_not_awaited()

    # ---- bank ----
    @pytest.mark.asyncio
    async def test_handle_bank_webhook(self, router: WebhookRouter, mock_command_bus: AsyncMock):
        payload = {
            "account_number": "123456",
            "amount": 5000,
            "transaction_date": "2024-01-01",
            "reference": "ref123",
            "sender_name": "John",
        }
        result = await router.handle_bank_webhook(payload)
        assert result["status"] == "processed"
        mock_command_bus.dispatch.assert_awaited_once_with({
            "type": "bank.receive_transfer",
            "data": payload,
        })

    # ---- coretax ----
    @pytest.mark.asyncio
    async def test_handle_coretax_webhook_faktur(self, router: WebhookRouter, mock_command_bus: AsyncMock):
        payload = {
            "event_type": "faktur_status",
            "faktur_number": "F123",
            "status": "approved",
            "response_code": "00",
            "message": "OK",
        }
        result = await router.handle_coretax_webhook(payload)
        assert result["status"] == "processed"
        mock_command_bus.dispatch.assert_awaited_once_with({
            "type": "tax.update_faktur_status",
            "data": {
                "faktur_number": "F123",
                "status": "approved",
                "response_code": "00",
                "message": "OK",
            },
        })

    @pytest.mark.asyncio
    async def test_handle_coretax_webhook_spt(self, router: WebhookRouter, mock_command_bus: AsyncMock):
        payload = {"event_type": "spt_status", "spt_id": "spt1", "status": "approved"}
        result = await router.handle_coretax_webhook(payload)
        assert result["status"] == "processed"
        mock_command_bus.dispatch.assert_awaited_once_with({
            "type": "tax.update_spt_status",
            "data": {"spt_id": "spt1", "status": "approved"},
        })

    @pytest.mark.asyncio
    async def test_handle_coretax_webhook_ignored(self, router: WebhookRouter, mock_command_bus: AsyncMock):
        payload = {"event_type": "unknown"}
        result = await router.handle_coretax_webhook(payload)
        assert result["status"] == "ignored"
        mock_command_bus.dispatch.assert_not_awaited()

    # ---- supplier ----
    @pytest.mark.asyncio
    async def test_handle_supplier_portal(self, router: WebhookRouter, mock_command_bus: AsyncMock):
        payload = {
            "supplier_id": "sup1",
            "invoice_number": "INV001",
            "invoice_date": "2024-01-01",
            "due_date": "2024-02-01",
            "amount": 1000,
            "currency": "IDR",
        }
        result = await router.handle_supplier_portal(payload)
        assert result["status"] == "processed"
        mock_command_bus.dispatch.assert_awaited_once_with({
            "type": "ap.invoice.create_from_webhook",
            "data": payload,
        })


# ============================================================================
# FastAPI Endpoint Tests
# We'll use TestClient, but need to override dependencies.
# We'll mock the _idempotency_manager and _webhook_router at module level.
# Since they are global, we need to patch them.
# ============================================================================

@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture
def mock_idempotency():
    with patch("adapters.primary_api.webhook_receiver_adapter._idempotency_manager") as mock:
        mock.is_processed = AsyncMock(return_value=(False, None))
        mock.mark_processed = AsyncMock()
        yield mock


@pytest.fixture
def mock_webhook_router():
    with patch("adapters.primary_api.webhook_receiver_adapter._webhook_router") as mock:
        # make methods async
        mock.handle_payment_gateway = AsyncMock(return_value={"status": "processed"})
        mock.handle_bank_webhook = AsyncMock(return_value={"status": "processed"})
        mock.handle_coretax_webhook = AsyncMock(return_value={"status": "processed"})
        mock.handle_supplier_portal = AsyncMock(return_value={"status": "processed"})
        mock.command_bus = AsyncMock()
        yield mock


class TestWebhookEndpoints:
    def test_midtrans_webhook_success(self, client, mock_idempotency, mock_webhook_router):
        payload = {"order_id": "ord123", "transaction_status": "settlement", "gross_amount": "10000"}
        response = client.post("/webhooks/midtrans", json=payload, headers={"X-Signature": "sig"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "processed"
        mock_webhook_router.handle_payment_gateway.assert_awaited_once_with(
            "midtrans", payload, "sig"
        )
        mock_idempotency.is_processed.assert_awaited_once_with("ord123")
        mock_idempotency.mark_processed.assert_awaited_once_with("ord123", data)

    def test_midtrans_webhook_idempotent(self, client, mock_idempotency, mock_webhook_router):
        mock_idempotency.is_processed.return_value = (True, {"cached": "result"})
        response = client.post("/webhooks/midtrans", json={"order_id": "ord123"})
        assert response.status_code == 200
        assert response.json() == {"cached": "result"}
        mock_webhook_router.handle_payment_gateway.assert_not_awaited()
        mock_idempotency.mark_processed.assert_not_awaited()

    def test_xendit_webhook_success(self, client, mock_idempotency, mock_webhook_router):
        payload = {"id": "inv123", "status": "PAID", "amount": 20000}
        response = client.post("/webhooks/xendit", json=payload, headers={"X-Callback-Token": "token"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "processed"
        mock_webhook_router.handle_payment_gateway.assert_awaited_once_with(
            "xendit", payload, "token"
        )
        mock_idempotency.is_processed.assert_awaited_once_with("inv123")
        mock_idempotency.mark_processed.assert_awaited_once_with("inv123", data)

    def test_stripe_webhook_success(self, client, mock_idempotency, mock_webhook_router):
        payload = {"type": "payment_intent.succeeded", "id": "evt123"}
        response = client.post(
            "/webhooks/stripe",
            json=payload,
            headers={"Stripe-Signature": "sig"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "processed"
        mock_webhook_router.handle_payment_gateway.assert_awaited_once_with(
            "stripe", payload, "sig"
        )
        mock_idempotency.is_processed.assert_awaited_once_with("evt123")
        mock_idempotency.mark_processed.assert_awaited_once_with("evt123", data)

    def test_bank_webhook_success(self, client, mock_idempotency, mock_webhook_router):
        payload = {"reference": "ref123", "account_number": "123", "amount": 1000}
        response = client.post("/webhooks/bank", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "processed"
        mock_webhook_router.handle_bank_webhook.assert_awaited_once_with(payload)
        mock_idempotency.is_processed.assert_awaited_once_with("ref123")
        mock_idempotency.mark_processed.assert_awaited_once_with("ref123", data)

    def test_coretax_webhook_success(self, client, mock_idempotency, mock_webhook_router):
        payload = {"event_type": "faktur_status", "request_id": "req123"}
        response = client.post("/webhooks/coretax", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "processed"
        mock_webhook_router.handle_coretax_webhook.assert_awaited_once_with(payload)
        mock_idempotency.is_processed.assert_awaited_once_with("req123")
        mock_idempotency.mark_processed.assert_awaited_once_with("req123", data)

    def test_supplier_webhook_success(self, client, mock_idempotency, mock_webhook_router):
        payload = {"invoice_number": "INV001", "amount": 500}
        response = client.post("/webhooks/supplier/sup123", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "processed"
        expected_payload = payload.copy()
        expected_payload["supplier_id"] = "sup123"
        mock_webhook_router.handle_supplier_portal.assert_awaited_once_with(expected_payload)
        mock_idempotency.is_processed.assert_awaited_once_with("INV001")
        mock_idempotency.mark_processed.assert_awaited_once_with("INV001", data)

    def test_generic_webhook_success(self, client, mock_idempotency, mock_webhook_router):
        payload = {"data": "test"}
        headers = {
            "X-Signature": "sig",
            "X-Idempotency-Key": "idem123",
            "X-Source": "custom",
        }
        response = client.post("/webhooks/generic", json=payload, headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "processed"  # command_bus dispatch returns
        # verify command was dispatched
        mock_webhook_router.command_bus.dispatch.assert_awaited_once_with({
            "type": "webhook.generic",
            "data": {"source": "custom", "payload": payload, "signature": "sig"},
        })
        mock_idempotency.is_processed.assert_awaited_once_with("idem123")
        mock_idempotency.mark_processed.assert_awaited_once_with("idem123", data)

    def test_generic_webhook_no_idempotency_key(self, client, mock_idempotency, mock_webhook_router):
        payload = {"data": "test"}
        response = client.post("/webhooks/generic", json=payload)
        assert response.status_code == 200
        # idempotency key should be generated from source + timestamp
        # we can't easily test exact key, but we can check it was called
        mock_idempotency.is_processed.assert_awaited_once()
        mock_idempotency.mark_processed.assert_awaited_once()
