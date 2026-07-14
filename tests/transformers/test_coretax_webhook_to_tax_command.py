# AUTO-GENERATED TESTS for transformers/coretax_webhook_to_tax_command.py
# =========================================
# All tests use AsyncMock for async collaborators.

import hashlib
import hmac
from unittest.mock import AsyncMock, patch

import pytest

from transformers.coretax_webhook_to_tax_command import (
    BaseTransformer,
    CoretaxWebhookPayloadValidator,
    CoretaxWebhookSignatureVerifier,
    CoretaxWebhookToTaxCommandTransformer,
    CoretaxWebhookTransformerError,
    FakturNotFoundError,
    InvalidSignatureError,
    WebhookPayloadError,
    get_coretax_webhook_transformer,
    handle_coretax_webhook,
)


class TestBaseTransformer:
    """Tests for BaseTransformer."""

    def _build_instance(self):
        return BaseTransformer(name="test_value")

    def test_construction(self):
        instance = self._build_instance()
        assert isinstance(instance, BaseTransformer)

    def test_validate_smoke(self):
        instance = self._build_instance()
        result = instance.validate()
        assert result["is_valid"] is True

    def test_to_dict_smoke(self):
        instance = self._build_instance()
        result = instance.to_dict()
        assert "transformer_id" in result
        assert result["name"] == "test_value"

    def test_from_dict_smoke(self):
        result = BaseTransformer.from_dict(data={})
        assert result.name == "default"
        assert result._version == 1

    def test_clone_smoke(self):
        instance = self._build_instance()
        cloned = instance.clone()
        assert cloned is not instance
        assert cloned.name == instance.name


class TestCoretaxWebhookTransformerError:
    def test_construction(self):
        instance = CoretaxWebhookTransformerError()
        assert isinstance(instance, CoretaxWebhookTransformerError)


class TestInvalidSignatureError:
    def test_construction(self):
        instance = InvalidSignatureError()
        assert isinstance(instance, InvalidSignatureError)


class TestWebhookPayloadError:
    def test_construction(self):
        instance = WebhookPayloadError()
        assert isinstance(instance, WebhookPayloadError)


class TestFakturNotFoundError:
    def test_construction(self):
        instance = FakturNotFoundError()
        assert isinstance(instance, FakturNotFoundError)


class TestCoretaxWebhookSignatureVerifier:
    def _build_instance(self, secret="test-secret"):
        return CoretaxWebhookSignatureVerifier(webhook_secret=secret)

    def test_construction(self):
        instance = self._build_instance()
        assert isinstance(instance, CoretaxWebhookSignatureVerifier)

    def test_verify_smoke(self):
        """Test verify with correct signature."""
        instance = self._build_instance("test-secret")
        payload = b"test-payload"
        expected = hmac.new(b"test-secret", payload, hashlib.sha256).hexdigest()
        result = instance.verify(payload_body=payload, signature=expected)
        assert result is True

    def test_verify_fails_with_wrong_signature(self):
        instance = self._build_instance("test-secret")
        payload = b"test-payload"
        result = instance.verify(payload_body=payload, signature="wrong")
        assert result is False

    def test_verify_skips_when_no_secret(self):
        """Verify skips verification when no secret configured."""
        with patch.object(
            CoretaxWebhookSignatureVerifier, '_get_secret_from_config', return_value=None
        ):
            instance = CoretaxWebhookSignatureVerifier(webhook_secret=None)
            result = instance.verify(payload_body=b"test", signature="anything")
            assert result is True

    def test_validate_smoke(self):
        instance = self._build_instance()
        result = instance.validate()
        assert "is_valid" in result

    def test_to_dict_smoke(self):
        instance = self._build_instance()
        result = instance.to_dict()
        assert "has_secret" in result

    def test_from_dict_smoke(self):
        instance = CoretaxWebhookSignatureVerifier.from_dict(
            data={"webhook_secret": "test"}
        )
        assert instance.webhook_secret == "test"


class TestCoretaxWebhookPayloadValidator:
    def _build_instance(self):
        return CoretaxWebhookPayloadValidator()

    def test_construction(self):
        instance = self._build_instance()
        assert isinstance(instance, CoretaxWebhookPayloadValidator)

    def test_validate_faktur_payload_smoke(self):
        instance = self._build_instance()
        payload = {
            "faktur_number": "F-001",
            "status": "3",
            "approval_code": "APP-001",
            "tanggal_approval": "2024-01-01",
            "npwp": "1234567890"
        }
        result = instance.validate_faktur_payload(payload)
        assert result["faktur_number"] == "F-001"
        assert result["status"] == "approved"

    def test_validate_spt_payload_smoke(self):
        instance = self._build_instance()
        payload = {
            "spt_number": "SPT-001",
            "status": "approved",
            "tracking_id": "TRK-001",
            "approval_date": "2024-01-01",
            "npwp": "1234567890"
        }
        result = instance.validate_spt_payload(payload)
        assert result["spt_number"] == "SPT-001"
        assert result["status"] == "approved"

    def test_validate_bupot_payload_smoke(self):
        instance = self._build_instance()
        payload = {
            "bupot_number": "BUPOT-001",
            "status": "approved",
            "coretax_id": "C-001",
            "approval_code": "APP-001",
            "npwp": "1234567890"
        }
        result = instance.validate_bupot_payload(payload)
        assert result["bupot_number"] == "BUPOT-001"
        assert result["status"] == "approved"

    def test_validate_emeterai_payload_smoke(self):
        instance = self._build_instance()
        payload = {
            "meterai_code": "M-001",
            "status": "active",
            "used_at": "2024-01-01",
            "document_id": "DOC-001",
            "npwp": "1234567890"
        }
        result = instance.validate_emeterai_payload(payload)
        assert result["meterai_code"] == "M-001"
        assert result["status"] == "active"

    def test_validate_smoke(self):
        instance = self._build_instance()
        result = instance.validate()
        assert result["is_valid"] is True


class TestCoretaxWebhookToTaxCommandTransformer:
    def _build_instance(self):
        command_bus = AsyncMock()
        command_bus.dispatch = AsyncMock(return_value={"id": "test"})
        coretax_service = AsyncMock()
        tax_service = AsyncMock()
        tax_service.get_faktur_by_number = AsyncMock(return_value={"id": "fact-1", "reference_id": "ref-1"})
        return CoretaxWebhookToTaxCommandTransformer(
            command_bus=command_bus,
            coretax_service=coretax_service,
            tax_service=tax_service
        )

    def test_construction(self):
        instance = self._build_instance()
        assert isinstance(instance, CoretaxWebhookToTaxCommandTransformer)

    @pytest.mark.asyncio
    async def test_transform_smoke(self):
        instance = self._build_instance()
        envelope = AsyncMock()
        envelope.event_type = "coretax.health.webhook"
        envelope.id = "test-id"
        envelope.payload = {"status": "healthy", "message": "OK"}
        envelope.metadata = {}
        await instance.transform(envelope=envelope)

    @pytest.mark.asyncio
    async def test_transform_faktur(self):
        instance = self._build_instance()
        envelope = AsyncMock()
        envelope.event_type = "coretax.faktur.webhook"
        envelope.id = "faktur-test"
        envelope.payload = {
            "faktur_number": "F-001",
            "status": "3",
            "approval_code": "APP-001",
            "tanggal_approval": "2024-01-01",
            "npwp": "1234567890"
        }
        envelope.metadata = {}
        await instance.transform(envelope=envelope)
        instance._command_bus.dispatch.assert_called()

    @pytest.mark.asyncio
    async def test_reset_smoke(self):
        instance = self._build_instance()
        await instance.reset()
        assert len(instance._processed_events) == 0

    def test_validate_smoke(self):
        instance = self._build_instance()
        result = instance.validate()
        assert result["is_valid"] is True

    def test_to_dict_smoke(self):
        instance = self._build_instance()
        result = instance.to_dict()
        assert "processed_events_count" in result


@pytest.mark.asyncio
async def test_get_coretax_webhook_transformer_smoke():
    result = await get_coretax_webhook_transformer()
    assert result is not None


@pytest.mark.asyncio
async def test_handle_coretax_webhook_smoke():
    with patch('transformers.coretax_webhook_to_tax_command._coretax_webhook_transformer', None):
        with patch('transformers.coretax_webhook_to_tax_command.get_coretax_webhook_transformer') as mock_get:
            command_bus = AsyncMock()
            command_bus.dispatch = AsyncMock(return_value={"id": "test"})
            coretax_service = AsyncMock()
            tax_service = AsyncMock()
            tax_service.get_faktur_by_number = AsyncMock(return_value={"id": "fact-1"})
            transformer = CoretaxWebhookToTaxCommandTransformer(
                command_bus=command_bus,
                coretax_service=coretax_service,
                tax_service=tax_service
            )
            mock_get.return_value = transformer

            envelope = AsyncMock()
            envelope.event_type = "coretax.health.webhook"
            envelope.id = "test-id"
            envelope.payload = {"status": "healthy"}
            envelope.metadata = {}
            await handle_coretax_webhook(envelope=envelope)
            command_bus.dispatch.assert_called_once()
