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
        assert isinstance(WebhookEventType.FAKTUR_STATUS, WebhookEventType)
        assert isinstance(WebhookEventType.SPT_APPROVED, WebhookEventType)

    def test_member_values(self):
        assert WebhookEventType.FAKTUR_STATUS.value == "faktur_status"
        assert WebhookEventType.SPT_APPROVED.value == "spt_approved"
        assert WebhookEventType.HEALTH_CHECK.value == "health_check"


class TestWebhookProcessingStatus:
    def test_members_exist(self):
        assert hasattr(WebhookProcessingStatus, 'RECEIVED')
        assert hasattr(WebhookProcessingStatus, 'PROCESSING')
        assert hasattr(WebhookProcessingStatus, 'SUCCESS')
        assert hasattr(WebhookProcessingStatus, 'FAILED')
        assert hasattr(WebhookProcessingStatus, 'RETRY')
        assert hasattr(WebhookProcessingStatus, 'DUPLICATE')
        assert hasattr(WebhookProcessingStatus, 'EXPIRED')
        assert hasattr(WebhookProcessingStatus, 'REJECTED')

    def test_member_is_instance(self):
        assert isinstance(WebhookProcessingStatus.RECEIVED, WebhookProcessingStatus)

    def test_member_values(self):
        assert WebhookProcessingStatus.RECEIVED.value == "received"
        assert WebhookProcessingStatus.SUCCESS.value == "success"


class TestWebhookPayload:
    def test_construction_success(self):
        kwargs = {
            "event_type": "faktur_status",
            "event_id": "test-event-id",
            "timestamp": datetime.now(UTC),
            "data": {"status": "approved"},
            "signature": "test-signature",
            "source": "coretax",
        }
        instance = WebhookPayload(**kwargs)
        assert isinstance(instance, WebhookPayload)
        assert instance.event_type == kwargs['event_type']
        assert instance.event_id == kwargs['event_id']

    def test_construction_optional_fields(self):
        kwargs = {
            "event_type": "spt_status",
            "event_id": "test-id",
            "timestamp": datetime.now(UTC),
            "data": {},
        }
        instance = WebhookPayload(**kwargs)
        assert instance.signature is None
        assert instance.source is None


class TestWebhookResponse:
    def test_construction_success(self):
        kwargs = {
            "status": "success",
            "webhook_id": "test-webhook-id",
            "event_id": "test-event-id",
            "processed_at": datetime.now(UTC),
            "result": {"message": "ok"},
            "error": None,
        }
        instance = WebhookResponse(**kwargs)
        assert isinstance(instance, WebhookResponse)
        assert instance.status == kwargs['status']


class TestWebhookLog:
    def test_construction_success(self):
        kwargs = {
            "webhook_id": "test-webhook-id",
            "event_id": "test-event-id",
            "event_type": "faktur_status",
            "status": WebhookProcessingStatus.RECEIVED,
            "received_at": datetime.now(UTC),
            "processed_at": datetime.now(UTC),
            "payload": {"key": "value"},
            "response": {"result": "ok"},
            "error": None,
            "retry_count": 0,
            "source_ip": "127.0.0.1",
            "signature_valid": True,
        }
        instance = WebhookLog(**kwargs)
        assert isinstance(instance, WebhookLog)
        assert instance.webhook_id == kwargs['webhook_id']


class TestWebhookExceptions:
    def test_webhook_error(self):
        with pytest.raises(WebhookError):
            raise WebhookError("test")

    def test_webhook_signature_error(self):
        with pytest.raises(WebhookSignatureError):
            raise WebhookSignatureError("test")

    def test_webhook_invalid_token_error(self):
        with pytest.raises(WebhookInvalidTokenError):
            raise WebhookInvalidTokenError("test")

    def test_webhook_duplicate_error(self):
        with pytest.raises(WebhookDuplicateError):
            raise WebhookDuplicateError("test")

    def test_webhook_processing_error(self):
        with pytest.raises(WebhookProcessingError):
            raise WebhookProcessingError("test")

    def test_webhook_not_found_error(self):
        with pytest.raises(WebhookNotFoundError):
            raise WebhookNotFoundError("test")


# ============================================================================
# WEBHOOK VERIFIER TESTS (including private methods)
# ============================================================================

class TestWebhookVerifier:
    @pytest.fixture
    def verifier(self):
        return WebhookVerifier()

    def test_construction(self, verifier):
        assert isinstance(verifier, WebhookVerifier)

    def test_get_webhook_secret_from_env(self, monkeypatch):
        monkeypatch.setenv("CORETAX_WEBHOOK_SECRET", "my-secret")
        verifier = WebhookVerifier()
        assert verifier.secret == "my-secret"

    def test_get_webhook_secret_default(self, monkeypatch):
        monkeypatch.delenv("CORETAX_WEBHOOK_SECRET", raising=False)
        verifier = WebhookVerifier()
        assert verifier.secret == ""

    def test_get_webhook_expected_tokens_from_env(self, monkeypatch):
        monkeypatch.setenv("CORETAX_WEBHOOK_TOKENS", "token1, token2, token3")
        verifier = WebhookVerifier()
        assert verifier.expected_tokens == ["token1", "token2", "token3"]

    def test_get_webhook_expected_tokens_default(self, monkeypatch):
        monkeypatch.delenv("CORETAX_WEBHOOK_TOKENS", raising=False)
        verifier = WebhookVerifier()
        assert verifier.expected_tokens == []

    def test_get_allowed_ips_from_env(self, monkeypatch):
        monkeypatch.setenv("CORETAX_WEBHOOK_ALLOWED_IPS", "127.0.0.1, 10.0.0.0/8")
        verifier = WebhookVerifier()
        assert verifier.allowed_ips == ["127.0.0.1", "10.0.0.0/8"]

    def test_get_allowed_ips_default(self, monkeypatch):
        monkeypatch.delenv("CORETAX_WEBHOOK_ALLOWED_IPS", raising=False)
        verifier = WebhookVerifier()
        assert verifier.allowed_ips == []

    def test_ip_in_cidr_exact_match(self, verifier):
        assert verifier._ip_in_cidr("192.168.1.1", "192.168.1.1/32") is True
        assert verifier._ip_in_cidr("192.168.1.2", "192.168.1.1/32") is False

    def test_ip_in_cidr_subnet(self, verifier):
        assert verifier._ip_in_cidr("10.0.0.1", "10.0.0.0/24") is True
        assert verifier._ip_in_cidr("10.0.1.1", "10.0.0.0/24") is False
        assert verifier._ip_in_cidr("192.168.0.5", "192.168.0.0/16") is True

    def test_ip_in_cidr_invalid(self, verifier):
        # Should return False if parsing fails
        assert verifier._ip_in_cidr("invalid", "10.0.0.0/24") is False

    def test_verify_signature_valid(self, monkeypatch):
        payload_body = b'{"event": "test"}'
        import hashlib
        import hmac
        secret = "test-secret"
        signature = hmac.new(secret.encode(), payload_body, hashlib.sha256).hexdigest()
        monkeypatch.setenv("CORETAX_WEBHOOK_SECRET", secret)
        verifier = WebhookVerifier()
        assert verifier.verify_signature(payload_body, signature) is True

    def test_verify_signature_invalid(self, monkeypatch):
        payload_body = b'{"event": "test"}'
        monkeypatch.setenv("CORETAX_WEBHOOK_SECRET", "test-secret")
        verifier = WebhookVerifier()
        assert verifier.verify_signature(payload_body, "invalid") is False

    def test_verify_signature_missing_secret(self, monkeypatch):
        monkeypatch.delenv("CORETAX_WEBHOOK_SECRET", raising=False)
        verifier = WebhookVerifier()
        # Should return True when secret is missing (skip verification)
        assert verifier.verify_signature(b"data", "sig") is True

    def test_verify_signature_sha512(self, monkeypatch):
        payload_body = b'{"event": "test"}'
        import hashlib
        import hmac
        secret = "test-secret"
        signature = hmac.new(secret.encode(), payload_body, hashlib.sha512).hexdigest()
        monkeypatch.setenv("CORETAX_WEBHOOK_SECRET", secret)
        verifier = WebhookVerifier()
        assert verifier.verify_signature(payload_body, signature, algorithm="sha512") is True

    def test_verify_bearer_token_valid(self, monkeypatch):
        monkeypatch.setenv("CORETAX_WEBHOOK_TOKENS", "token1, token2")
        verifier = WebhookVerifier()
        assert verifier.verify_bearer_token("Bearer token2") is True

    def test_verify_bearer_token_invalid(self, monkeypatch):
        monkeypatch.setenv("CORETAX_WEBHOOK_TOKENS", "token1, token2")
        verifier = WebhookVerifier()
        assert verifier.verify_bearer_token("Bearer token3") is False

    def test_verify_bearer_token_missing_tokens(self, monkeypatch):
        monkeypatch.delenv("CORETAX_WEBHOOK_TOKENS", raising=False)
        verifier = WebhookVerifier()
        # Should return True when no tokens configured (skip verification)
        assert verifier.verify_bearer_token("Bearer any") is True

    def test_verify_bearer_token_no_auth_header(self, monkeypatch):
        monkeypatch.setenv("CORETAX_WEBHOOK_TOKENS", "token1")
        verifier = WebhookVerifier()
        assert verifier.verify_bearer_token(None) is False
        assert verifier.verify_bearer_token("Basic auth") is False

    def test_verify_source_ip_allowed(self, monkeypatch):
        monkeypatch.setenv("CORETAX_WEBHOOK_ALLOWED_IPS", "127.0.0.1, 10.0.0.0/8")
        verifier = WebhookVerifier()
        assert verifier.verify_source_ip("127.0.0.1") is True
        assert verifier.verify_source_ip("10.0.0.5") is True
        assert verifier.verify_source_ip("10.1.0.1") is False

    def test_verify_source_ip_no_ips_configured(self, monkeypatch):
        monkeypatch.delenv("CORETAX_WEBHOOK_ALLOWED_IPS", raising=False)
        verifier = WebhookVerifier()
        assert verifier.verify_source_ip("any") is True

    def test_verify_source_ip_no_client_ip(self, monkeypatch):
        monkeypatch.setenv("CORETAX_WEBHOOK_ALLOWED_IPS", "127.0.0.1")
        verifier = WebhookVerifier()
        assert verifier.verify_source_ip(None) is False

    def test_verify_all_success(self, monkeypatch):
        payload_body = b'{"event": "test"}'
        import hashlib
        import hmac
        secret = "test-secret"
        signature = hmac.new(secret.encode(), payload_body, hashlib.sha256).hexdigest()
        monkeypatch.setenv("CORETAX_WEBHOOK_SECRET", secret)
        monkeypatch.setenv("CORETAX_WEBHOOK_TOKENS", "token")
        monkeypatch.setenv("CORETAX_WEBHOOK_ALLOWED_IPS", "127.0.0.1")
        verifier = WebhookVerifier()
        assert verifier.verify_all(payload_body, signature, "Bearer token", "127.0.0.1") is True

    def test_verify_all_ip_fails(self, monkeypatch):
        monkeypatch.setenv("CORETAX_WEBHOOK_ALLOWED_IPS", "10.0.0.1")
        verifier = WebhookVerifier()
        assert verifier.verify_all(b"data", None, None, "192.168.1.1") is False

    def test_verify_all_token_fails(self, monkeypatch):
        monkeypatch.setenv("CORETAX_WEBHOOK_TOKENS", "valid-token")
        monkeypatch.delenv("CORETAX_WEBHOOK_ALLOWED_IPS", raising=False)
        verifier = WebhookVerifier()
        assert verifier.verify_all(b"data", None, "Bearer invalid", "127.0.0.1") is False

    def test_verify_all_signature_fails(self, monkeypatch):
        monkeypatch.setenv("CORETAX_WEBHOOK_SECRET", "secret")
        monkeypatch.delenv("CORETAX_WEBHOOK_TOKENS", raising=False)
        monkeypatch.delenv("CORETAX_WEBHOOK_ALLOWED_IPS", raising=False)
        verifier = WebhookVerifier()
        assert verifier.verify_all(b"data", "invalid", "Bearer any", "127.0.0.1") is False


# ============================================================================
# WEBHOOK IDEMPOTENCY MANAGER TESTS
# ============================================================================

class TestWebhookIdempotencyManager:
    @pytest.fixture
    def manager(self):
        with patch('adapters.coretax_djp.webhook_receiver.get_redis_client', new_callable=AsyncMock) as mock_get_redis:
            mock_redis = AsyncMock()
            mock_get_redis.return_value = mock_redis
            manager = WebhookIdempotencyManager()
            manager.redis = mock_redis
            return manager

    def test_get_key(self, manager):
        assert manager._get_key("webhook-123") == "coretax:webhook:processed:webhook-123"

    def test_get_failed_key(self, manager):
        assert manager._get_failed_key("webhook-123") == "coretax:webhook:failed:webhook-123"

    def test_get_pending_key(self, manager):
        assert manager._get_pending_key("webhook-123") == "coretax:webhook:pending:webhook-123"

    @pytest.mark.asyncio
    async def test_is_processed_true(self, manager):
        manager.redis.get = AsyncMock(return_value=b"processed")
        assert await manager.is_processed("webhook-123") is True

    @pytest.mark.asyncio
    async def test_is_processed_false(self, manager):
        manager.redis.get = AsyncMock(return_value=None)
        assert await manager.is_processed("webhook-123") is False

    @pytest.mark.asyncio
    async def test_is_processed_fallback_to_cache(self, manager):
        manager.redis.get = AsyncMock(side_effect=Exception("Redis error"))
        manager._cache["webhook-123"] = {"status": "ok"}
        assert await manager.is_processed("webhook-123") is True

    @pytest.mark.asyncio
    async def test_mark_processed(self, manager):
        manager.redis.setex = AsyncMock()
        await manager.mark_processed("webhook-123", {"status": "ok"}, ttl=100)
        manager.redis.setex.assert_called_once_with(
            "coretax:webhook:processed:webhook-123",
            100,
            '{"status": "ok"}'
        )
        assert "webhook-123" in manager._cache

    @pytest.mark.asyncio
    async def test_mark_processed_redis_fails(self, manager):
        manager.redis.setex = AsyncMock(side_effect=Exception("Redis error"))
        await manager.mark_processed("webhook-123", {"status": "ok"})
        # Should still cache locally
        assert "webhook-123" in manager._cache

    @pytest.mark.asyncio
    async def test_mark_failed(self, manager):
        manager.redis.setex = AsyncMock()
        await manager.mark_failed("webhook-123", "error")
        manager.redis.setex.assert_called_once()

    @pytest.mark.asyncio
    async def test_mark_pending(self, manager):
        manager.redis.setex = AsyncMock()
        await manager.mark_pending("webhook-123", {"key": "value"}, ttl=3600)
        manager.redis.setex.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_pending_webhooks(self, manager):
        manager.redis.keys = AsyncMock(return_value=[b"coretax:webhook:pending:w1", b"coretax:webhook:pending:w2"])
        manager.redis.get = AsyncMock(return_value=b'{"key":"value"}')
        result = await manager.get_pending_webhooks(limit=10)
        assert len(result) == 2
        assert result[0][0] == "w1"
        assert result[0][1] == {"key": "value"}

    @pytest.mark.asyncio
    async def test_get_pending_webhooks_redis_fails(self, manager):
        manager.redis.keys = AsyncMock(side_effect=Exception("Redis error"))
        result = await manager.get_pending_webhooks()
        assert result == []

    @pytest.mark.asyncio
    async def test_remove_pending(self, manager):
        manager.redis.delete = AsyncMock()
        await manager.remove_pending("webhook-123")
        manager.redis.delete.assert_called_once_with("coretax:webhook:pending:webhook-123")

    @pytest.mark.asyncio
    async def test_remove_pending_redis_fails(self, manager):
        manager.redis.delete = AsyncMock(side_effect=Exception("Redis error"))
        # Should not raise
        await manager.remove_pending("webhook-123")


# ============================================================================
# WEBHOOK HANDLER TESTS
# ============================================================================

class TestWebhookHandler:
    @pytest.fixture
    def handler(self):
        mock_service = MagicMock()
        return WebhookHandler(coretax_service=mock_service)

    def test_construction(self, handler):
        assert isinstance(handler, WebhookHandler)
        assert handler._coretax_service is not None
        # Check default handlers registered
        assert WebhookEventType.FAKTUR_STATUS.value in handler._handlers
        assert WebhookEventType.SPT_STATUS.value in handler._handlers
        assert WebhookEventType.BUPOT_STATUS.value in handler._handlers
        assert WebhookEventType.EMETERAI_STATUS.value in handler._handlers
        assert WebhookEventType.HEALTH_CHECK.value in handler._handlers

    def test_register_default_handlers(self, handler):
        # This is called in __init__, but we can call it again to test
        handler._register_default_handlers()
        assert WebhookEventType.FAKTUR_STATUS.value in handler._handlers

    def test_register_handler(self, handler):
        mock_func = AsyncMock()
        handler.register_handler("custom_event", mock_func)
        assert handler.get_handler("custom_event") is mock_func

    def test_get_handler_found(self, handler):
        mock_func = AsyncMock()
        handler.register_handler("test_event", mock_func)
        assert handler.get_handler("test_event") is mock_func

    def test_get_handler_not_found(self, handler):
        assert handler.get_handler("unknown") is None

    def test_resolve_service_with_service(self, handler):
        service = MagicMock()
        resolved = handler._resolve_service(service)
        assert resolved is service

    def test_resolve_service_with_instance_service(self, handler):
        # handler already has _coretax_service
        resolved = handler._resolve_service(None)
        assert resolved is handler._coretax_service

    def test_resolve_service_no_service_raises(self):
        handler = WebhookHandler(coretax_service=None)
        with pytest.raises(RuntimeError, match="CoretaxService belum terinisialisasi"):
            handler._resolve_service(None)

    @pytest.mark.asyncio
    async def test_handle_faktur_status(self, handler):
        payload = {"faktur_number": "123", "status": "approved"}
        handler._coretax_service.update_faktur_status = AsyncMock()
        result = await handler.handle_faktur_status(payload)
        assert result["processed"] is True
        handler._coretax_service.update_faktur_status.assert_called_once_with(
            faktur_number="123",
            status="approved",
            approval_code=None,
            approval_date=None,
            rejection_reason=None,
        )

    @pytest.mark.asyncio
    async def test_handle_faktur_status_missing_number(self, handler):
        payload = {"status": "approved"}
        result = await handler.handle_faktur_status(payload)
        assert result["processed"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_handle_faktur_approved(self, handler):
        payload = {"faktur_number": "123", "approval_code": "APP-001"}
        handler._coretax_service.approve_faktur = AsyncMock()
        result = await handler.handle_faktur_approved(payload)
        assert result["processed"] is True
        handler._coretax_service.approve_faktur.assert_called_once_with(
            faktur_number="123",
            approval_code="APP-001",
            approval_date=None,
            qr_code=None,
        )

    @pytest.mark.asyncio
    async def test_handle_faktur_rejected(self, handler):
        payload = {"faktur_number": "123", "rejection_reason": "Invalid"}
        handler._coretax_service.reject_faktur = AsyncMock()
        result = await handler.handle_faktur_rejected(payload)
        assert result["processed"] is True

    @pytest.mark.asyncio
    async def test_handle_faktur_cancelled(self, handler):
        payload = {"faktur_number": "123", "reason": "Duplicate"}
        handler._coretax_service.cancel_faktur = AsyncMock()
        result = await handler.handle_faktur_cancelled(payload)
        assert result["processed"] is True

    @pytest.mark.asyncio
    async def test_handle_spt_status(self, handler):
        payload = {"tracking_id": "T123", "status": "approved"}
        handler._coretax_service.update_spt_status = AsyncMock()
        result = await handler.handle_spt_status(payload)
        assert result["processed"] is True

    @pytest.mark.asyncio
    async def test_handle_spt_approved(self, handler):
        payload = {"tracking_id": "T123"}
        handler._coretax_service.approve_spt = AsyncMock()
        result = await handler.handle_spt_approved(payload)
        assert result["processed"] is True

    @pytest.mark.asyncio
    async def test_handle_spt_rejected(self, handler):
        payload = {"tracking_id": "T123", "rejection_reason": "Data error"}
        handler._coretax_service.reject_spt = AsyncMock()
        result = await handler.handle_spt_rejected(payload)
        assert result["processed"] is True

    @pytest.mark.asyncio
    async def test_handle_bupot_status(self, handler):
        payload = {"bupot_number": "B001", "status": "approved"}
        handler._coretax_service.update_bupot_status = AsyncMock()
        result = await handler.handle_bupot_status(payload)
        assert result["processed"] is True

    @pytest.mark.asyncio
    async def test_handle_bupot_approved(self, handler):
        payload = {"bupot_number": "B001"}
        handler._coretax_service.approve_bupot = AsyncMock()
        result = await handler.handle_bupot_approved(payload)
        assert result["processed"] is True

    @pytest.mark.asyncio
    async def test_handle_bupot_rejected(self, handler):
        payload = {"bupot_number": "B001", "rejection_reason": "Invalid"}
        handler._coretax_service.reject_bupot = AsyncMock()
        result = await handler.handle_bupot_rejected(payload)
        assert result["processed"] is True

    @pytest.mark.asyncio
    async def test_handle_emeterai_status(self, handler):
        payload = {"meterai_code": "M001", "status": "used"}
        handler._coretax_service.update_emeterai_status = AsyncMock()
        result = await handler.handle_emeterai_status(payload)
        assert result["processed"] is True

    @pytest.mark.asyncio
    async def test_handle_emeterai_used(self, handler):
        payload = {"meterai_code": "M001", "document_id": "DOC-001"}
        handler._coretax_service.mark_emeterai_used = AsyncMock()
        result = await handler.handle_emeterai_used(payload)
        assert result["processed"] is True

    @pytest.mark.asyncio
    async def test_handle_ntpn_validated_valid(self, handler):
        payload = {"ntpn": "1234567890", "is_valid": True}
        handler._coretax_service.mark_ntpn_valid = AsyncMock()
        result = await handler.handle_ntpn_validated(payload)
        assert result["processed"] is True
        assert result["is_valid"] is True

    @pytest.mark.asyncio
    async def test_handle_ntpn_validated_invalid(self, handler):
        payload = {"ntpn": "1234567890", "is_valid": False, "message": "Invalid"}
        handler._coretax_service.mark_ntpn_invalid = AsyncMock()
        result = await handler.handle_ntpn_validated(payload)
        assert result["processed"] is True
        assert result["is_valid"] is False

    @pytest.mark.asyncio
    async def test_handle_health(self, handler):
        result = await handler.handle_health({})
        assert result["processed"] is True
        assert "Health check received" in result["message"]

    @pytest.mark.asyncio
    async def test_process_event_found(self, handler):
        mock_func = AsyncMock(return_value={"status": "ok"})
        handler.register_handler("test_event", mock_func)
        result = await handler.process_event("test_event", {})
        assert result["status"] == "ok"
        mock_func.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_event_not_found(self, handler):
        result = await handler.process_event("unknown", {})
        assert result["processed"] is False
        assert "No handler" in result["error"]


# ============================================================================
# WEBHOOK LOGGER TESTS
# ============================================================================

class TestWebhookLogger:
    @pytest.fixture
    def logger(self):
        return WebhookLogger()

    @pytest.mark.asyncio
    async def test_log(self, logger):
        mock_log = MagicMock(spec=WebhookLog)
        mock_log.webhook_id = "w1"
        mock_log.event_type = "test"
        mock_log.status = WebhookProcessingStatus.RECEIVED
        await logger.log(mock_log)
        assert "w1" in logger._storage

    @pytest.mark.asyncio
    async def test_get(self, logger):
        mock_log = MagicMock(spec=WebhookLog)
        mock_log.webhook_id = "w1"
        logger._storage["w1"] = mock_log
        result = await logger.get("w1")
        assert result is mock_log
        assert await logger.get("none") is None

    @pytest.mark.asyncio
    async def test_get_by_event_id(self, logger):
        mock_log = MagicMock(spec=WebhookLog)
        mock_log.event_id = "e1"
        logger._storage["w1"] = mock_log
        result = await logger.get_by_event_id("e1")
        assert result is mock_log
        assert await logger.get_by_event_id("e2") is None

    @pytest.mark.asyncio
    async def test_get_by_status(self, logger):
        log1 = MagicMock(spec=WebhookLog)
        log1.status = WebhookProcessingStatus.SUCCESS
        log1.webhook_id = "w1"
        log2 = MagicMock(spec=WebhookLog)
        log2.status = WebhookProcessingStatus.FAILED
        log2.webhook_id = "w2"
        logger._storage["w1"] = log1
        logger._storage["w2"] = log2
        result = await logger.get_by_status(WebhookProcessingStatus.SUCCESS)
        assert len(result) == 1
        assert result[0] is log1

    @pytest.mark.asyncio
    async def test_get_failed(self, logger):
        log1 = MagicMock(spec=WebhookLog)
        log1.status = WebhookProcessingStatus.FAILED
        logger._storage["w1"] = log1
        result = await logger.get_failed(limit=10)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_pending(self, logger):
        log1 = MagicMock(spec=WebhookLog)
        log1.status = WebhookProcessingStatus.PENDING
        logger._storage["w1"] = log1
        result = await logger.get_pending()
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_update_status(self, logger):
        log = MagicMock(spec=WebhookLog)
        log.webhook_id = "w1"
        logger._storage["w1"] = log
        await logger.update_status("w1", WebhookProcessingStatus.SUCCESS, error=None)
        assert log.status == WebhookProcessingStatus.SUCCESS
        assert log.processed_at is not None
        assert log.error is None


# ============================================================================
# WEBHOOK RECEIVER TESTS
# ============================================================================

class TestWebhookReceiver:
    @pytest.fixture
    def receiver(self):
        mock_service = MagicMock()
        return WebhookReceiver(coretax_service=mock_service)

    def test_construction(self, receiver):
        assert isinstance(receiver, WebhookReceiver)
        assert receiver._coretax_service is not None

    def test_set_coretax_service(self, receiver):
        new_service = MagicMock()
        receiver.set_coretax_service(new_service)
        assert receiver._coretax_service is new_service
        assert receiver.handler._coretax_service is new_service

    @pytest.mark.asyncio
    async def test_receive_success(self, receiver, monkeypatch):
        mock_request = MagicMock()
        mock_request.client = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.json = AsyncMock(return_value={"event_type": "faktur_status", "event_id": "e1"})
        mock_request.body = AsyncMock(return_value=b'{"event_type": "faktur_status"}')

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
        assert result["status"] == "ok"
        assert "webhook_id" in result
        assert "event_type" in result

    @pytest.mark.asyncio
    async def test_receive_invalid_signature(self, receiver, monkeypatch):
        mock_request = MagicMock()
        mock_request.client = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.body = AsyncMock(return_value=b'{}')

        monkeypatch.setenv("CORETAX_WEBHOOK_SECRET", "secret")
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
        assert result["status"] == "already_processed"

    @pytest.mark.asyncio
    async def test_receive_processing_error_queues_retry(self, receiver, monkeypatch):
        mock_request = MagicMock()
        mock_request.client = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.json = AsyncMock(return_value={"event_type": "faktur_status", "retry_count": 0})
        mock_request.body = AsyncMock(return_value=b'{}')

        monkeypatch.setenv("CORETAX_WEBHOOK_SECRET", "")
        monkeypatch.setenv("CORETAX_WEBHOOK_TOKENS", "")
        monkeypatch.setenv("CORETAX_WEBHOOK_ALLOWED_IPS", "")

        receiver.verifier = WebhookVerifier()
        receiver.idempotency.is_processed = AsyncMock(return_value=False)
        receiver.handler.process_event = AsyncMock(side_effect=Exception("Processing error"))
        receiver.logger.log = AsyncMock()
        receiver.idempotency.mark_failed = AsyncMock()
        receiver.idempotency.mark_pending = AsyncMock()

        with pytest.raises(WebhookProcessingError):
            await receiver.receive(
                request=mock_request,
                x_signature="sha256=test",
                x_webhook_id="webhook-123",
                authorization="Bearer token"
            )
        receiver.idempotency.mark_pending.assert_called_once()

    @pytest.mark.asyncio
    async def test_receive_infer_event_type(self, receiver, monkeypatch):
        mock_request = MagicMock()
        mock_request.client = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.json = AsyncMock(return_value={"faktur_number": "123", "approval_code": "APP"})
        mock_request.body = AsyncMock(return_value=b'{}')

        monkeypatch.setenv("CORETAX_WEBHOOK_SECRET", "")
        monkeypatch.setenv("CORETAX_WEBHOOK_TOKENS", "")
        monkeypatch.setenv("CORETAX_WEBHOOK_ALLOWED_IPS", "")

        receiver.verifier = WebhookVerifier()
        receiver.idempotency.is_processed = AsyncMock(return_value=False)
        receiver.idempotency.mark_processed = AsyncMock()
        receiver.handler.process_event = AsyncMock(return_value={"status": "success"})
        receiver.logger.log = AsyncMock()

        result = await receiver.receive(
            request=mock_request,
            x_signature="sha256=test",
            x_webhook_id="webhook-123",
            authorization="Bearer token"
        )
        # Should infer event type as FAKTUR_APPROVED
        assert result["event_type"] == "faktur_approved"

    @pytest.mark.asyncio
    async def test_retry_failed_found(self, receiver):
        receiver.idempotency.get_pending_webhooks = AsyncMock(return_value=[("w1", {})])
        result = await receiver.retry_failed("w1")
        assert result["status"] == "retried"

    @pytest.mark.asyncio
    async def test_retry_failed_not_found(self, receiver):
        receiver.idempotency.get_pending_webhooks = AsyncMock(return_value=[])
        result = await receiver.retry_failed("w1")
        assert result["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_retry_all_failed(self, receiver):
        receiver.idempotency.get_pending_webhooks = AsyncMock(return_value=[("w1", {}), ("w2", {})])
        receiver.retry_failed = AsyncMock(return_value={"status": "retried"})
        result = await receiver.retry_all_failed()
        assert result["total"] == 2
        assert len(result["results"]) == 2

    @pytest.mark.asyncio
    async def test_get_webhook_status(self, receiver):
        mock_log = MagicMock(spec=WebhookLog)
        receiver.logger.get = AsyncMock(return_value=mock_log)
        result = await receiver.get_webhook_status("w1")
        assert result is mock_log

    @pytest.mark.asyncio
    async def test_get_history(self, receiver):
        receiver.logger.get_by_status = AsyncMock(return_value=[])
        receiver.logger.get_failed = AsyncMock(return_value=[])
        receiver.logger.get_pending = AsyncMock(return_value=[])
        result = await receiver.get_history(limit=10)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_replay_webhook(self, receiver):
        mock_log = MagicMock(spec=WebhookLog)
        mock_log.payload = {"key": "value"}
        receiver.logger.get = AsyncMock(return_value=mock_log)
        receiver.idempotency.mark_pending = AsyncMock()
        receiver.logger.update_status = AsyncMock()
        result = await receiver.replay_webhook("w1")
        assert result["status"] == "queued"

    @pytest.mark.asyncio
    async def test_replay_webhook_not_found(self, receiver):
        receiver.logger.get = AsyncMock(return_value=None)
        result = await receiver.replay_webhook("w1")
        assert result["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_acknowledge(self, receiver):
        mock_log = MagicMock(spec=WebhookLog)
        mock_log.event_id = "e1"
        mock_log.received_at = datetime.now(UTC)
        receiver.logger.get = AsyncMock(return_value=mock_log)
        result = await receiver.acknowledge("w1")
        assert result["status"] == "acknowledged"

    @pytest.mark.asyncio
    async def test_acknowledge_not_found(self, receiver):
        receiver.logger.get = AsyncMock(return_value=None)
        result = await receiver.acknowledge("w1")
        assert result["status"] == "not_found"

    def test_infer_event_type(self, receiver):
        # Faktur approved
        assert receiver._infer_event_type({"faktur_number": "123", "approval_code": "APP"}) == "faktur_approved"
        # Faktur rejected
        assert receiver._infer_event_type({"faktur_number": "123", "rejection_reason": "Bad"}) == "faktur_rejected"
        # Faktur status
        assert receiver._infer_event_type({"faktur_number": "123"}) == "faktur_status"
        # SPT status
        assert receiver._infer_event_type({"spt_number": "S123"}) == "spt_status"
        assert receiver._infer_event_type({"tracking_id": "T123"}) == "spt_status"
        # Bupot status
        assert receiver._infer_event_type({"bupot_number": "B123"}) == "bupot_status"
        assert receiver._infer_event_type({"coretax_id": "C123"}) == "bupot_status"
        # e-Meterai used
        assert receiver._infer_event_type({"meterai_code": "M123", "used_at": "now"}) == "emeterai_used"
        # e-Meterai status
        assert receiver._infer_event_type({"meterai_code": "M123"}) == "emeterai_status"
        # NTPN
        assert receiver._infer_event_type({"ntpn": "1234567890"}) == "ntpn_validated"
        # Health
        assert receiver._infer_event_type({"type": "health"}) == "health_check"
        # Unknown
        assert receiver._infer_event_type({"unknown": "field"}) == "unknown"


# ============================================================================
# MODULE-LEVEL FUNCTION TESTS
# ============================================================================

def test_get_webhook_receiver():
    mock_service = MagicMock()
    result = get_webhook_receiver(coretax_service=mock_service)
    assert isinstance(result, WebhookReceiver)
    # Should return singleton
    result2 = get_webhook_receiver()
    assert result is result2


# ============================================================================
# FASTAPI ENDPOINT INTEGRATION TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_coretax_faktur_webhook(monkeypatch):
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
    mock_receiver = MagicMock(spec=WebhookReceiver)
    mock_receiver.receive = AsyncMock(return_value={"status": "ok"})

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
    mock_receiver = MagicMock(spec=WebhookReceiver)
    mock_receiver.receive = AsyncMock(return_value={"status": "ok"})

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
    mock_receiver = MagicMock(spec=WebhookReceiver)
    mock_receiver.receive = AsyncMock(return_value={"status": "ok"})

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
    mock_receiver = MagicMock(spec=WebhookReceiver)
    mock_receiver.receive = AsyncMock(return_value={"status": "ok"})

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


@pytest.mark.asyncio
async def test_get_webhook_status_endpoint(monkeypatch):
    mock_receiver = MagicMock(spec=WebhookReceiver)
    mock_log = MagicMock(spec=WebhookLog)
    mock_log.webhook_id = "w1"
    mock_log.event_id = "e1"
    mock_log.event_type = "test"
    mock_log.status = WebhookProcessingStatus.SUCCESS
    mock_log.received_at = datetime.now(UTC)
    mock_log.processed_at = datetime.now(UTC)
    mock_log.error = None
    mock_log.retry_count = 0
    mock_receiver.get_webhook_status = AsyncMock(return_value=mock_log)

    with patch('adapters.coretax_djp.webhook_receiver.get_webhook_receiver', return_value=mock_receiver):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        from adapters.coretax_djp.webhook_receiver import router
        app.include_router(router)

        client = TestClient(app)
        response = client.get("/coretax/webhook/status/w1")
        assert response.status_code == 200
        assert response.json()["status"] == "success"


@pytest.mark.asyncio
async def test_retry_webhook_endpoint(monkeypatch):
    mock_receiver = MagicMock(spec=WebhookReceiver)
    mock_receiver.retry_failed = AsyncMock(return_value={"status": "retried"})

    with patch('adapters.coretax_djp.webhook_receiver.get_webhook_receiver', return_value=mock_receiver):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        from adapters.coretax_djp.webhook_receiver import router
        app.include_router(router)

        client = TestClient(app)
        response = client.post("/coretax/webhook/retry/w1")
        assert response.status_code == 200
        assert response.json()["status"] == "retried"


@pytest.mark.asyncio
async def test_retry_all_webhooks_endpoint(monkeypatch):
    mock_receiver = MagicMock(spec=WebhookReceiver)
    mock_receiver.retry_all_failed = AsyncMock(return_value={"total": 2, "results": []})

    with patch('adapters.coretax_djp.webhook_receiver.get_webhook_receiver', return_value=mock_receiver):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        from adapters.coretax_djp.webhook_receiver import router
        app.include_router(router)

        client = TestClient(app)
        response = client.post("/coretax/webhook/retry-all")
        assert response.status_code == 200
        assert response.json()["total"] == 2


@pytest.mark.asyncio
async def test_webhook_history_endpoint(monkeypatch):
    mock_receiver = MagicMock(spec=WebhookReceiver)
    mock_log = MagicMock(spec=WebhookLog)
    mock_log.webhook_id = "w1"
    mock_log.event_id = "e1"
    mock_log.event_type = "test"
    mock_log.status = WebhookProcessingStatus.SUCCESS
    mock_log.received_at = datetime.now(UTC)
    mock_log.processed_at = datetime.now(UTC)
    mock_log.error = None
    mock_log.retry_count = 0
    mock_receiver.get_history = AsyncMock(return_value=[mock_log])

    with patch('adapters.coretax_djp.webhook_receiver.get_webhook_receiver', return_value=mock_receiver):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        from adapters.coretax_djp.webhook_receiver import router
        app.include_router(router)

        client = TestClient(app)
        response = client.get("/coretax/webhook/history")
        assert response.status_code == 200
        assert response.json()["total"] == 1


@pytest.mark.asyncio
async def test_replay_webhook_endpoint(monkeypatch):
    mock_receiver = MagicMock(spec=WebhookReceiver)
    mock_receiver.replay_webhook = AsyncMock(return_value={"status": "queued"})

    with patch('adapters.coretax_djp.webhook_receiver.get_webhook_receiver', return_value=mock_receiver):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        from adapters.coretax_djp.webhook_receiver import router
        app.include_router(router)

        client = TestClient(app)
        response = client.post("/coretax/webhook/replay/w1")
        assert response.status_code == 200
        assert response.json()["status"] == "queued"


@pytest.mark.asyncio
async def test_acknowledge_webhook_endpoint(monkeypatch):
    mock_receiver = MagicMock(spec=WebhookReceiver)
    mock_receiver.acknowledge = AsyncMock(return_value={"status": "acknowledged"})

    with patch('adapters.coretax_djp.webhook_receiver.get_webhook_receiver', return_value=mock_receiver):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        from adapters.coretax_djp.webhook_receiver import router
        app.include_router(router)

        client = TestClient(app)
        response = client.post("/coretax/webhook/acknowledge/w1")
        assert response.status_code == 200
        assert response.json()["status"] == "acknowledged"
