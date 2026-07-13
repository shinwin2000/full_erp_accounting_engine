
"""
Unit tests for adapters/coretax_djp/webhook_receiver.py
Menggunakan pytest dan mock untuk semua dependency eksternal.
"""

import sys
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

# Mock redis sebelum import module apa pun
redis_mock = MagicMock()
redis_asyncio = MagicMock()
redis_asyncio.from_url = MagicMock(return_value=AsyncMock())
redis_exceptions = MagicMock()
redis_exceptions.ConnectionError = Exception
redis_exceptions.RedisError = Exception
redis_exceptions.TimeoutError = TimeoutError

sys.modules["redis"] = redis_mock
sys.modules["redis.asyncio"] = redis_asyncio
sys.modules["redis.exceptions"] = redis_exceptions

import pytest

from adapters.coretax_djp.webhook_receiver import (
    WebhookDuplicateError,
    WebhookError,
    WebhookEventType,
    WebhookHandler,
    WebhookIdempotencyManager,
    WebhookInvalidTokenError,
    WebhookLog,
    WebhookLogger,
    WebhookNotFoundError,
    WebhookPayload,
    WebhookProcessingError,
    WebhookProcessingStatus,
    WebhookReceiver,
    WebhookResponse,
    WebhookSignatureError,
    WebhookVerifier,
    get_webhook_receiver,
)


class TestWebhookEventType:
    """Tests for the WebhookEventType enum."""

    def test_members_exist(self):
        """All expected enum members are defined."""
        assert hasattr(WebhookEventType, 'FAKTUR_STATUS')
        assert hasattr(WebhookEventType, 'FAKTUR_APPROVED')
        assert hasattr(WebhookEventType, 'FAKTUR_REJECTED')
        assert hasattr(WebhookEventType, 'FAKTUR_CANCELLED')
        assert hasattr(WebhookEventType, 'SPT_STATUS')
        assert hasattr(WebhookEventType, 'SPT_APPROVED')
        assert hasattr(WebhookEventType, 'SPT_REJECTED')
        assert hasattr(WebhookEventType, 'BUPOT_STATUS')
        assert hasattr(WebhookEventType, 'BUPOT_APPROVED')
        assert hasattr(WebhookEventType, 'BUPOT_REJECTED')
        assert hasattr(WebhookEventType, 'EMETERAI_STATUS')
        assert hasattr(WebhookEventType, 'EMETERAI_USED')
        assert hasattr(WebhookEventType, 'EMETERAI_EXPIRED')
        assert hasattr(WebhookEventType, 'NSFP_STATUS')
        assert hasattr(WebhookEventType, 'NTPN_VALIDATED')
        assert hasattr(WebhookEventType, 'HEALTH_CHECK')
        assert hasattr(WebhookEventType, 'UNKNOWN')

    def test_member_is_instance(self):
        """Enum members are instances of the enum class."""
        assert isinstance(WebhookEventType.FAKTUR_STATUS, WebhookEventType)
        assert isinstance(WebhookEventType.SPT_APPROVED, WebhookEventType)
        assert isinstance(WebhookEventType.BUPOT_REJECTED, WebhookEventType)

    def test_member_values(self):
        """Enum members have correct values."""
        assert WebhookEventType.FAKTUR_STATUS.value == "faktur_status"
        assert WebhookEventType.SPT_APPROVED.value == "spt_approved"
        assert WebhookEventType.BUPOT_REJECTED.value == "bupot_rejected"
        assert WebhookEventType.HEALTH_CHECK.value == "health_check"


class TestWebhookProcessingStatus:
    """Tests for the WebhookProcessingStatus enum."""

    def test_members_exist(self):
        """All expected enum members are defined."""
        assert hasattr(WebhookProcessingStatus, 'RECEIVED')
        assert hasattr(WebhookProcessingStatus, 'PROCESSING')
        assert hasattr(WebhookProcessingStatus, 'SUCCESS')
        assert hasattr(WebhookProcessingStatus, 'FAILED')
        assert hasattr(WebhookProcessingStatus, 'RETRY')
        assert hasattr(WebhookProcessingStatus, 'DUPLICATE')
        assert hasattr(WebhookProcessingStatus, 'EXPIRED')
        assert hasattr(WebhookProcessingStatus, 'REJECTED')

    def test_member_is_instance(self):
        """Enum members are instances of the enum class."""
        assert isinstance(WebhookProcessingStatus.RECEIVED, WebhookProcessingStatus)
        assert isinstance(WebhookProcessingStatus.SUCCESS, WebhookProcessingStatus)

    def test_member_values(self):
        """Enum members have correct values."""
        assert WebhookProcessingStatus.RECEIVED.value == "received"
        assert WebhookProcessingStatus.SUCCESS.value == "success"
        assert WebhookProcessingStatus.FAILED.value == "failed"


class TestWebhookPayload:
    """Tests for the WebhookPayload value object / model."""

    def test_construction_success(self):
        """WebhookPayload can be constructed with valid field values."""
        kwargs = dict(
            event_type="faktur_status",
            event_id="test-event-id",
            timestamp=datetime.now(UTC),
            data={"status": "approved"},
            signature="test-signature",
            source="coretax",
        )
        instance = WebhookPayload(**kwargs)
        assert isinstance(instance, WebhookPayload)
        assert instance.event_type == kwargs['event_type']
        assert instance.event_id == kwargs['event_id']

    def test_construction_optional_fields(self):
        """WebhookPayload handles optional fields correctly."""
        kwargs = dict(
            event_type="spt_status",
            event_id="test-id",
            timestamp=datetime.now(UTC),
            data={},
        )
        instance = WebhookPayload(**kwargs)
        assert instance.signature is None
        assert instance.source is None


class TestWebhookResponse:
    """Tests for the WebhookResponse value object / model."""

    def test_construction_success(self):
        """WebhookResponse can be constructed with valid field values."""
        kwargs = dict(
            status="success",
            webhook_id="test-webhook-id",
            event_id="test-event-id",
            processed_at=datetime.now(UTC),
            result={"message": "ok"},
            error=None,
        )
        instance = WebhookResponse(**kwargs)
        assert isinstance(instance, WebhookResponse)
        assert instance.status == kwargs['status']
        assert instance.webhook_id == kwargs['webhook_id']


class TestWebhookLog:
    """Tests for the WebhookLog value object / model."""

    def test_construction_success(self):
        """WebhookLog can be constructed with valid field values."""
        kwargs = dict(
            webhook_id="test-webhook-id",
            event_id="test-event-id",
            event_type="faktur_status",
            status=WebhookProcessingStatus.RECEIVED,
            received_at=datetime.now(UTC),
            processed_at=datetime.now(UTC),
            payload={"key": "value"},
            response={"result": "ok"},
            error=None,
            retry_count=0,
            source_ip="127.0.0.1",
            signature_valid=True,
        )
        instance = WebhookLog(**kwargs)
        assert isinstance(instance, WebhookLog)
        assert instance.webhook_id == kwargs['webhook_id']
        assert instance.status == WebhookProcessingStatus.RECEIVED


class TestWebhookExceptions:
    """Tests for Webhook exception classes."""

    def test_webhook_error_construction(self):
        """WebhookError can be instantiated."""
        instance = WebhookError("Test error message")
        assert isinstance(instance, WebhookError)
        assert str(instance) == "Test error message"

    def test_webhook_signature_error_construction(self):
        """WebhookSignatureError can be instantiated."""
        instance = WebhookSignatureError("Invalid signature")
        assert isinstance(instance, WebhookSignatureError)
        assert isinstance(instance, WebhookError)

    def test_webhook_invalid_token_error_construction(self):
        """WebhookInvalidTokenError can be instantiated."""
        instance = WebhookInvalidTokenError("Invalid token")
        assert isinstance(instance, WebhookInvalidTokenError)
        assert isinstance(instance, WebhookError)

    def test_webhook_duplicate_error_construction(self):
        """WebhookDuplicateError can be instantiated."""
        instance = WebhookDuplicateError("Duplicate webhook")
        assert isinstance(instance, WebhookDuplicateError)
        assert isinstance(instance, WebhookError)

    def test_webhook_processing_error_construction(self):
        """WebhookProcessingError can be instantiated."""
        instance = WebhookProcessingError("Processing failed")
        assert isinstance(instance, WebhookProcessingError)
        assert isinstance(instance, WebhookError)

    def test_webhook_not_found_error_construction(self):
        """WebhookNotFoundError can be instantiated."""
        instance = WebhookNotFoundError("Webhook not found")
        assert isinstance(instance, WebhookNotFoundError)
        assert isinstance(instance, WebhookError)


class TestWebhookVerifier:
    """Tests for WebhookVerifier."""

    @pytest.fixture
    def verifier(self):
        return WebhookVerifier()

    def test_construction(self, verifier):
        """WebhookVerifier can be instantiated."""
        assert isinstance(verifier, WebhookVerifier)

    def test_verify_signature_valid(self, monkeypatch):
        """verify_signature returns True for valid signature."""
        payload_body = b'{"event": "test"}'
        # Generate a valid HMAC signature
        import hashlib
        import hmac
        secret = "test-secret"
        signature = hmac.new(
            secret.encode(),
            payload_body,
            hashlib.sha256
        ).hexdigest()

        # Patch the secret retrieval
        monkeypatch.setenv("CORETAX_WEBHOOK_SECRET", secret)
        verifier_with_secret = WebhookVerifier()
        result = verifier_with_secret.verify_signature(
            payload_body=payload_body,
            signature=signature,
            algorithm="sha256"
        )
        assert result is True

    def test_verify_signature_invalid(self, monkeypatch):
        """verify_signature returns False for invalid signature."""
        payload_body = b'{"event": "test"}'
        invalid_signature = "invalidsignature"

        monkeypatch.setenv("CORETAX_WEBHOOK_SECRET", "test-secret")
        verifier_with_secret = WebhookVerifier()
        result = verifier_with_secret.verify_signature(
            payload_body=payload_body,
            signature=invalid_signature,
            algorithm="sha256"
        )
        assert result is False

    def test_verify_bearer_token_valid(self, monkeypatch):
        """verify_bearer_token returns True for valid token."""
        monkeypatch.setenv("CORETAX_WEBHOOK_TOKENS", "valid-token")
        verifier_with_token = WebhookVerifier()
        result = verifier_with_token.verify_bearer_token(authorization="Bearer valid-token")
        assert result is True

    def test_verify_bearer_token_invalid(self, monkeypatch):
        """verify_bearer_token returns False for invalid token."""
        monkeypatch.setenv("CORETAX_WEBHOOK_TOKENS", "valid-token")
        verifier_with_token = WebhookVerifier()
        result = verifier_with_token.verify_bearer_token(authorization="Bearer invalid-token")
        assert result is False

    def test_verify_source_ip_allowed(self, monkeypatch):
        """verify_source_ip returns True for allowed IP."""
        monkeypatch.setenv("CORETAX_WEBHOOK_ALLOWED_IPS", "127.0.0.1, 10.0.0.1")
        verifier_with_ips = WebhookVerifier()
        result = verifier_with_ips.verify_source_ip(client_ip="127.0.0.1")
        assert result is True

    def test_verify_source_ip_not_allowed(self, monkeypatch):
        """verify_source_ip returns False for disallowed IP."""
        monkeypatch.setenv("CORETAX_WEBHOOK_ALLOWED_IPS", "10.0.0.1")
        verifier_with_ips = WebhookVerifier()
        result = verifier_with_ips.verify_source_ip(client_ip="192.168.1.1")
        assert result is False

    def test_verify_all_success(self, monkeypatch):
        """verify_all returns True when all checks pass."""
        payload_body = b'{"event": "test"}'
        import hashlib
        import hmac
        secret = "test-secret"
        signature = hmac.new(
            secret.encode(),
            payload_body,
            hashlib.sha256
        ).hexdigest()

        monkeypatch.setenv("CORETAX_WEBHOOK_SECRET", secret)
        monkeypatch.setenv("CORETAX_WEBHOOK_TOKENS", "token")
        monkeypatch.setenv("CORETAX_WEBHOOK_ALLOWED_IPS", "127.0.0.1")

        verifier_with_all = WebhookVerifier()
        result = verifier_with_all.verify_all(
            payload_body=payload_body,
            signature=signature,
            authorization="Bearer token",
            client_ip="127.0.0.1"
        )
        assert result is True


class TestWebhookIdempotencyManager:
    """Tests for WebhookIdempotencyManager."""

    @pytest.fixture
    def idempotency_manager(self):
        with patch('adapters.coretax_djp.webhook_receiver.get_redis_client', new_callable=AsyncMock) as mock_get_redis:
            mock_redis = AsyncMock()
            mock_get_redis.return_value = mock_redis
            manager = WebhookIdempotencyManager()
            manager.redis = mock_redis
            return manager

    @pytest.mark.asyncio
    async def test_is_processed_true(self, idempotency_manager):
        """is_processed returns True when webhook was processed."""
        idempotency_manager.redis.get = AsyncMock(return_value=b"processed")
        result = await idempotency_manager.is_processed("webhook-123")
        assert result is True

    @pytest.mark.asyncio
    async def test_is_processed_false(self, idempotency_manager):
        """is_processed returns False when webhook was not processed."""
        idempotency_manager.redis.get = AsyncMock(return_value=None)
        result = await idempotency_manager.is_processed("webhook-123")
        assert result is False

    @pytest.mark.asyncio
    async def test_mark_processed(self, idempotency_manager):
        """mark_processed sets the processed flag in Redis."""
        idempotency_manager.redis.setex = AsyncMock()
        await idempotency_manager.mark_processed(
            webhook_id="webhook-123",
            result={"status": "success"},
            ttl=3600
        )
        idempotency_manager.redis.setex.assert_called_once()

    @pytest.mark.asyncio
    async def test_mark_failed(self, idempotency_manager):
        """mark_failed sets the failed flag in Redis."""
        idempotency_manager.redis.setex = AsyncMock()
        await idempotency_manager.mark_failed(
            webhook_id="webhook-123",
            error="Processing error",
            ttl=3600
        )
        idempotency_manager.redis.setex.assert_called_once()

    @pytest.mark.asyncio
    async def test_mark_pending(self, idempotency_manager):
        """mark_pending sets the pending flag in Redis."""
        idempotency_manager.redis.setex = AsyncMock()
        await idempotency_manager.mark_pending(
            webhook_id="webhook-123",
            payload={"event": "test"},
            ttl=3600
        )
        idempotency_manager.redis.setex.assert_called_once()


class TestWebhookHandler:
    """Tests for WebhookHandler."""

    @pytest.fixture
    def handler(self):
        mock_service = MagicMock()
        return WebhookHandler(coretax_service=mock_service)

    def test_construction(self, handler):
        """WebhookHandler can be instantiated."""
        assert isinstance(handler, WebhookHandler)
        assert handler._coretax_service is not None

    def test_register_handler(self, handler):
        """register_handler adds a handler for an event type."""
        mock_handler_func = AsyncMock()
        handler.register_handler(WebhookEventType.FAKTUR_STATUS.value, mock_handler_func)
        assert WebhookEventType.FAKTUR_STATUS.value in handler._handlers

    def test_get_handler_found(self, handler):
        """get_handler returns the registered handler."""
        mock_handler_func = AsyncMock()
        handler.register_handler(WebhookEventType.FAKTUR_STATUS.value, mock_handler_func)
        result = handler.get_handler(WebhookEventType.FAKTUR_STATUS.value)
        assert result is mock_handler_func

    def test_get_handler_not_found(self, handler):
        """get_handler returns None when no handler registered."""
        result = handler.get_handler("unknown_event")
        assert result is None

    @pytest.mark.asyncio
    async def test_handle_faktur_status(self, handler):
        """handle_faktur_status processes faktur status payload."""
        payload = {"faktur_number": "123", "status": "approved"}
        handler._coretax_service.update_faktur_status = AsyncMock()
        result = await handler.handle_faktur_status(payload, handler._coretax_service)
        assert isinstance(result, dict)
        assert "processed" in result

    @pytest.mark.asyncio
    async def test_handle_faktur_approved(self, handler):
        """handle_faktur_approved processes approved faktur."""
        payload = {"faktur_number": "123"}
        handler._coretax_service.approve_faktur = AsyncMock()
        result = await handler.handle_faktur_approved(payload, handler._coretax_service)
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_handle_faktur_rejected(self, handler):
        """handle_faktur_rejected processes rejected faktur."""
        payload = {"faktur_number": "123", "rejection_reason": "Invalid data"}
        handler._coretax_service.reject_faktur = AsyncMock()
        result = await handler.handle_faktur_rejected(payload, handler._coretax_service)
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_handle_spt_status(self, handler):
        """handle_spt_status processes SPT status payload."""
        payload = {"tracking_id": "456", "status": "approved"}
        handler._coretax_service.update_spt_status = AsyncMock()
        result = await handler.handle_spt_status(payload, handler._coretax_service)
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_handle_bupot_status(self, handler):
        """handle_bupot_status processes e-Bupot status payload."""
        payload = {"bupot_number": "789", "status": "approved"}
        handler._coretax_service.update_bupot_status = AsyncMock()
        result = await handler.handle_bupot_status(payload, handler._coretax_service)
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_handle_emeterai_status(self, handler):
        """handle_emeterai_status processes e-Meterai status payload."""
        payload = {"meterai_code": "321", "status": "used"}
        handler._coretax_service.update_emeterai_status = AsyncMock()
        result = await handler.handle_emeterai_status(payload, handler._coretax_service)
        assert isinstance(result, dict)


class TestWebhookLogger:
    """Tests for WebhookLogger."""

    @pytest.fixture
    def logger_instance(self):
        return WebhookLogger()

    def test_construction(self, logger_instance):
        """WebhookLogger can be instantiated."""
        assert isinstance(logger_instance, WebhookLogger)

    @pytest.mark.asyncio
    async def test_log(self, logger_instance):
        """log creates a webhook log entry."""
        mock_log = MagicMock(spec=WebhookLog)
        mock_log.webhook_id = "test-123"
        mock_log.event_type = "test_event"
        mock_log.status = WebhookProcessingStatus.RECEIVED
        result = await logger_instance.log(mock_log)
        assert result is None
        assert "test-123" in logger_instance._storage

    @pytest.mark.asyncio
    async def test_get_found(self, logger_instance):
        """get returns a webhook log by ID."""
        mock_log = MagicMock(spec=WebhookLog)
        mock_log.webhook_id = "webhook-123"
        logger_instance._storage["webhook-123"] = mock_log
        result = await logger_instance.get("webhook-123")
        assert result is mock_log

    @pytest.mark.asyncio
    async def test_get_not_found(self, logger_instance):
        """get returns None when webhook not found."""
        result = await logger_instance.get("webhook-999")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_event_id(self, logger_instance):
        """get_by_event_id returns logs by event ID."""
        mock_log = MagicMock(spec=WebhookLog)
        mock_log.event_id = "event-123"
        logger_instance._storage["webhook-123"] = mock_log
        result = await logger_instance.get_by_event_id("event-123")
        assert result is mock_log

    @pytest.mark.asyncio
    async def test_get_by_status(self, logger_instance):
        """get_by_status returns logs by status."""
        mock_log = MagicMock(spec=WebhookLog)
        mock_log.status = WebhookProcessingStatus.SUCCESS
        logger_instance._storage["webhook-123"] = mock_log
        result = await logger_instance.get_by_status(WebhookProcessingStatus.SUCCESS)
        assert len(result) == 1
        assert result[0] is mock_log


class TestWebhookReceiver:
    """Tests for WebhookReceiver."""

    @pytest.fixture
    def receiver(self):
        mock_service = MagicMock()
        return WebhookReceiver(coretax_service=mock_service)

    def test_construction(self, receiver):
        """WebhookReceiver can be instantiated."""
        assert isinstance(receiver, WebhookReceiver)

    def test_set_coretax_service(self, receiver):
        """set_coretax_service updates the service."""
        new_service = MagicMock()
        receiver.set_coretax_service(new_service)
        assert receiver._coretax_service is new_service

    @pytest.mark.asyncio
    async def test_receive_success(self, receiver, monkeypatch):
        """receive processes a valid webhook request."""
        mock_request = MagicMock()
        mock_request.client = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.json = AsyncMock(return_value={"event_type": "faktur_status", "event_id": "123"})
        mock_request.body = AsyncMock(return_value=b'{"event_type": "faktur_status"}')

        # Setup mocks
        monkeypatch.setenv("CORETAX_WEBHOOK_SECRET", "")
        monkeypatch.setenv("CORETAX_WEBHOOK_TOKENS", "")
        monkeypatch.setenv("CORETAX_WEBHOOK_ALLOWED_IPS", "")

        receiver.verifier = WebhookVerifier()
        receiver.idempotency.is_processed = AsyncMock(return_value=False)
        receiver.idempotency.mark_processed = AsyncMock()
        receiver.idempotency.remove_pending = AsyncMock()
        receiver.handler.process_event = AsyncMock(return_value={"status": "success"})
        receiver.logger.log = AsyncMock()
        receiver.logger.update_status = AsyncMock()

        result = await receiver.receive(
            request=mock_request,
            x_signature="sha256=test",
            x_webhook_id="webhook-123",
            authorization="Bearer token"
        )
        assert isinstance(result, dict)
        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_receive_invalid_signature(self, receiver, monkeypatch):
        """receive rejects webhook with invalid signature."""
        mock_request = MagicMock()
        mock_request.client = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.body = AsyncMock(return_value=b'{}')

        monkeypatch.setenv("CORETAX_WEBHOOK_SECRET", "test-secret")
        monkeypatch.setenv("CORETAX_WEBHOOK_TOKENS", "token")
        monkeypatch.setenv("CORETAX_WEBHOOK_ALLOWED_IPS", "127.0.0.1")

        receiver.verifier = WebhookVerifier()

        with pytest.raises(WebhookSignatureError):
            await receiver.receive(
                request=mock_request,
                x_signature="sha256=invalid",
                x_webhook_id="webhook-123",
                authorization="Bearer wrong-token"
            )

    @pytest.mark.asyncio
    async def test_receive_duplicate(self, receiver, monkeypatch):
        """receive handles duplicate webhook."""
        mock_request = MagicMock()
        mock_request.client = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.json = AsyncMock(return_value={"event_type": "faktur_status"})
        mock_request.body = AsyncMock(return_value=b'{}')

        monkeypatch.setenv("CORETAX_WEBHOOK_SECRET", "")
        monkeypatch.setenv("CORETAX_WEBHOOK_TOKENS", "")
        monkeypatch.setenv("CORETAX_WEBHOOK_ALLOWED_IPS", "")

        receiver.verifier = WebhookVerifier()
        receiver.idempotency.is_processed = AsyncMock(return_value=True)

        result = await receiver.receive(
            request=mock_request,
            x_signature="sha256=test",
            x_webhook_id="webhook-123",
            authorization="Bearer token"
        )
        assert isinstance(result, dict)
        assert result["status"] == "already_processed"

    @pytest.mark.asyncio
    async def test_retry_failed(self, receiver):
        """retry_failed retries a failed webhook."""
        receiver.idempotency.get_pending_webhooks = AsyncMock(return_value=[("webhook-123", {})])
        result = await receiver.retry_failed("webhook-123")
        assert isinstance(result, dict)
        assert "status" in result

    @pytest.mark.asyncio
    async def test_retry_all_failed(self, receiver):
        """retry_all_failed retries all failed webhooks."""
        mock_logs = [
            ("w1", {}),
            ("w2", {}),
        ]
        receiver.idempotency.get_pending_webhooks = AsyncMock(return_value=mock_logs)
        receiver.retry_failed = AsyncMock(return_value={"status": "retried"})
        result = await receiver.retry_all_failed()
        assert isinstance(result, dict)
        assert "total" in result


# Module-level function tests
def test_get_webhook_receiver():
    """get_webhook_receiver returns a WebhookReceiver instance."""
    mock_service = MagicMock()
    result = get_webhook_receiver(coretax_service=mock_service)
    assert isinstance(result, WebhookReceiver)


@pytest.mark.asyncio
async def test_coretax_faktur_webhook(monkeypatch):
    """coretax_faktur_webhook endpoint processes faktur webhook."""
    mock_request = MagicMock()
    mock_request.client = MagicMock()
    mock_request.client.host = "127.0.0.1"
    mock_request.json = AsyncMock(return_value={"event_type": "faktur_status"})
    mock_request.body = AsyncMock(return_value=b'{}')

    mock_receiver = MagicMock(spec=WebhookReceiver)
    mock_receiver.receive = AsyncMock(return_value={
        "status": "ok",
        "webhook_id": "123...",
        "event_id": "evt-123...",
        "event_type": "faktur_status",
        "result": {},
        "processed_at": datetime.now().isoformat(),
    })

    monkeypatch.setenv("CORETAX_WEBHOOK_SECRET", "")
    monkeypatch.setenv("CORETAX_WEBHOOK_TOKENS", "")
    monkeypatch.setenv("CORETAX_WEBHOOK_ALLOWED_IPS", "")

    with patch('adapters.coretax_djp.webhook_receiver.get_webhook_receiver', return_value=mock_receiver):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        from adapters.coretax_djp.webhook_receiver import router
        app.include_router(router)

        client = TestClient(app)

        response = client.post(
            "/coretax/webhook/faktur",
            json={"event_type": "faktur_status"},
            headers={
                "X-Signature": "sha256=test",
                "X-Webhook-Id": "webhook-123",
                "Authorization": "Bearer token"
            }
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_coretax_spt_webhook(monkeypatch):
    """coretax_spt_webhook endpoint processes SPT webhook."""
    mock_request = MagicMock()
    mock_request.client = MagicMock()
    mock_request.client.host = "127.0.0.1"
    mock_request.json = AsyncMock(return_value={"event_type": "spt_status"})
    mock_request.body = AsyncMock(return_value=b'{}')

    mock_receiver = MagicMock(spec=WebhookReceiver)
    mock_receiver.receive = AsyncMock(return_value={
        "status": "ok",
        "webhook_id": "123...",
        "event_id": "evt-123...",
        "event_type": "spt_status",
        "result": {},
        "processed_at": datetime.now().isoformat(),
    })

    monkeypatch.setenv("CORETAX_WEBHOOK_SECRET", "")
    monkeypatch.setenv("CORETAX_WEBHOOK_TOKENS", "")
    monkeypatch.setenv("CORETAX_WEBHOOK_ALLOWED_IPS", "")

    with patch('adapters.coretax_djp.webhook_receiver.get_webhook_receiver', return_value=mock_receiver):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        from adapters.coretax_djp.webhook_receiver import router
        app.include_router(router)

        client = TestClient(app)

        response = client.post(
            "/coretax/webhook/spt",
            json={"event_type": "spt_status"},
            headers={
                "X-Signature": "sha256=test",
                "X-Webhook-Id": "webhook-123",
                "Authorization": "Bearer token"
            }
        )
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_coretax_bupot_webhook(monkeypatch):
    """coretax_bupot_webhook endpoint processes e-Bupot webhook."""
    mock_request = MagicMock()
    mock_request.client = MagicMock()
    mock_request.client.host = "127.0.0.1"
    mock_request.json = AsyncMock(return_value={"event_type": "bupot_status"})
    mock_request.body = AsyncMock(return_value=b'{}')

    mock_receiver = MagicMock(spec=WebhookReceiver)
    mock_receiver.receive = AsyncMock(return_value={
        "status": "ok",
        "webhook_id": "123...",
        "event_id": "evt-123...",
        "event_type": "bupot_status",
        "result": {},
        "processed_at": datetime.now().isoformat(),
    })

    monkeypatch.setenv("CORETAX_WEBHOOK_SECRET", "")
    monkeypatch.setenv("CORETAX_WEBHOOK_TOKENS", "")
    monkeypatch.setenv("CORETAX_WEBHOOK_ALLOWED_IPS", "")

    with patch('adapters.coretax_djp.webhook_receiver.get_webhook_receiver', return_value=mock_receiver):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        from adapters.coretax_djp.webhook_receiver import router
        app.include_router(router)

        client = TestClient(app)

        response = client.post(
            "/coretax/webhook/bupot",
            json={"event_type": "bupot_status"},
            headers={
                "X-Signature": "sha256=test",
                "X-Webhook-Id": "webhook-123",
                "Authorization": "Bearer token"
            }
        )
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_coretax_emeterai_webhook(monkeypatch):
    """coretax_emeterai_webhook endpoint processes e-Meterai webhook."""
    mock_request = MagicMock()
    mock_request.client = MagicMock()
    mock_request.client.host = "127.0.0.1"
    mock_request.json = AsyncMock(return_value={"event_type": "emeterai_status"})
    mock_request.body = AsyncMock(return_value=b'{}')

    mock_receiver = MagicMock(spec=WebhookReceiver)
    mock_receiver.receive = AsyncMock(return_value={
        "status": "ok",
        "webhook_id": "123...",
        "event_id": "evt-123...",
        "event_type": "emeterai_status",
        "result": {},
        "processed_at": datetime.now().isoformat(),
    })

    monkeypatch.setenv("CORETAX_WEBHOOK_SECRET", "")
    monkeypatch.setenv("CORETAX_WEBHOOK_TOKENS", "")
    monkeypatch.setenv("CORETAX_WEBHOOK_ALLOWED_IPS", "")

    with patch('adapters.coretax_djp.webhook_receiver.get_webhook_receiver', return_value=mock_receiver):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        from adapters.coretax_djp.webhook_receiver import router
        app.include_router(router)

        client = TestClient(app)

        response = client.post(
            "/coretax/webhook/emeterai",
            json={"event_type": "emeterai_status"},
            headers={
                "X-Signature": "sha256=test",
                "X-Webhook-Id": "webhook-123",
                "Authorization": "Bearer token"
            }
        )
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_coretax_health_webhook(monkeypatch):
    """coretax_health_webhook endpoint processes health check."""
    mock_request = MagicMock()
    mock_request.client = MagicMock()
    mock_request.client.host = "127.0.0.1"
    mock_request.json = AsyncMock(return_value={"event_type": "health_check"})
    mock_request.body = AsyncMock(return_value=b'{}')

    mock_receiver = MagicMock(spec=WebhookReceiver)
    mock_receiver.receive = AsyncMock(return_value={
        "status": "ok",
        "webhook_id": "123...",
        "event_id": "evt-123...",
        "event_type": "health_check",
        "result": {},
        "processed_at": datetime.now().isoformat(),
    })

    monkeypatch.setenv("CORETAX_WEBHOOK_SECRET", "")
    monkeypatch.setenv("CORETAX_WEBHOOK_TOKENS", "")
    monkeypatch.setenv("CORETAX_WEBHOOK_ALLOWED_IPS", "")

    with patch('adapters.coretax_djp.webhook_receiver.get_webhook_receiver', return_value=mock_receiver):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        from adapters.coretax_djp.webhook_receiver import router
        app.include_router(router)

        client = TestClient(app)

        response = client.post(
            "/coretax/webhook/health",
            json={"event_type": "health_check"},
            headers={
                "Authorization": "Bearer token"
            }
        )
        assert response.status_code == 200
