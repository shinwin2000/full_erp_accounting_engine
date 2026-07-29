# tests/transformers/test_coretax_webhook_to_tax_command.py
"""
Comprehensive unit tests for transformers/coretax_webhook_to_tax_command.py.
Covers all classes, methods, edge cases, negative paths, and exceptions.
"""

import hashlib
import hmac
import os
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

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

# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_command_bus():
    bus = AsyncMock()
    bus.dispatch = AsyncMock(return_value={"id": "cmd-123"})
    return bus


@pytest.fixture
def mock_coretax_service():
    return AsyncMock()


@pytest.fixture
def mock_tax_service():
    svc = AsyncMock()
    svc.get_faktur_by_number = AsyncMock(return_value={
        "id": "fact-123",
        "reference_id": "ref-456",
        "npwp": "1234567890",
    })
    svc.record_ntpn_validation = AsyncMock()
    return svc


@pytest.fixture
def transformer(mock_command_bus, mock_coretax_service, mock_tax_service):
    return CoretaxWebhookToTaxCommandTransformer(
        command_bus=mock_command_bus,
        coretax_service=mock_coretax_service,
        tax_service=mock_tax_service,
    )


@pytest.fixture
def mock_envelope():
    env = MagicMock()
    env.id = "evt-123"
    env.event_type = "coretax.health.webhook"
    env.payload = {"status": "healthy", "message": "OK"}
    env.metadata = {"signature": "", "raw_payload": ""}
    return env


# ============================================================================
# TESTS FOR BASE TRANSFORMER
# ============================================================================

class TestBaseTransformer:
    def test_construction_default(self):
        instance = BaseTransformer()
        assert instance.name == "default"
        assert instance._version == 1
        assert instance._transformer_id is not None
        assert instance._audit_trail == []
        assert instance._snapshots == []

    def test_construction_custom_name(self):
        instance = BaseTransformer("custom")
        assert instance.name == "custom"

    def test_validate(self):
        instance = BaseTransformer()
        result = instance.validate()
        assert result == {"is_valid": True, "errors": []}

    def test_to_dict(self):
        instance = BaseTransformer("test")
        d = instance.to_dict()
        assert d["name"] == "test"
        assert d["version"] == 1
        assert "transformer_id" in d

    def test_from_dict_with_name(self):
        data = {"name": "restored", "version": 5, "transformer_id": "some-id"}
        instance = BaseTransformer.from_dict(data)
        assert instance.name == "restored"
        assert instance._version == 5
        assert instance._transformer_id == "some-id"

    def test_from_dict_without_name(self):
        data = {"version": 3}
        instance = BaseTransformer.from_dict(data)
        assert instance.name == "default"
        assert instance._version == 3

    def test_clone(self):
        instance = BaseTransformer("original")
        clone = instance.clone()
        assert clone is not instance
        assert clone.name == "original"
        assert clone._version == instance._version + 1
        # Audit trail should have CLONE entry
        assert len(clone._audit_trail) == 1
        assert clone._audit_trail[0]["action"] == "CLONE"

    def test_snapshot(self):
        instance = BaseTransformer("test")
        snap = instance.snapshot()
        assert snap["name"] == "test"
        assert snap["version"] == instance._version
        assert snap["transformer_id"] == instance._transformer_id
        assert "timestamp" in snap

    def test_version(self):
        instance = BaseTransformer()
        assert instance.version() == 1
        instance._version = 5
        assert instance.version() == 5

    def test_audit_trail(self):
        instance = BaseTransformer()
        instance._record_audit("ACTION1", "user1", {"detail": "a"})
        instance._record_audit("ACTION2", "user2", {"detail": "b"})
        trail = instance.audit_trail()
        assert len(trail) == 2
        assert trail[0]["action"] == "ACTION1"
        assert trail[1]["action"] == "ACTION2"

    def test_audit_trail_limit(self):
        instance = BaseTransformer()
        for i in range(150):
            instance._record_audit(f"ACTION{i}", "user", {})
        trail = instance.audit_trail(limit=100)
        assert len(trail) == 100

    def test_touch(self):
        instance = BaseTransformer()
        old_version = instance.version()
        result = instance.touch("admin")
        assert result is instance
        assert instance.version() == old_version + 1
        assert len(instance._audit_trail) == 1
        assert instance._audit_trail[0]["action"] == "TOUCH"

    def test_take_snapshot(self):
        instance = BaseTransformer()
        instance._take_snapshot()
        assert len(instance._snapshots) == 1
        snap = instance._snapshots[0]
        assert snap["version"] == instance._version
        assert snap["transformer_id"] == instance._transformer_id
        # Test that snapshot list doesn't exceed 10
        for _ in range(20):
            instance._take_snapshot()
        assert len(instance._snapshots) <= 10

    def test_record_audit(self):
        instance = BaseTransformer()
        instance._record_audit("TEST", "actor", {"key": "value"})
        assert len(instance._audit_trail) == 1
        entry = instance._audit_trail[0]
        assert entry["action"] == "TEST"
        assert entry["performed_by"] == "actor"
        assert entry["details"] == {"key": "value"}
        assert "timestamp" in entry


# ============================================================================
# TESTS FOR EXCEPTIONS
# ============================================================================

class TestExceptions:
    def test_coretax_webhook_transformer_error(self):
        exc = CoretaxWebhookTransformerError("message")
        assert isinstance(exc, Exception)
        assert str(exc) == "message"

    def test_invalid_signature_error(self):
        exc = InvalidSignatureError("sig")
        assert isinstance(exc, CoretaxWebhookTransformerError)

    def test_webhook_payload_error(self):
        exc = WebhookPayloadError("payload")
        assert isinstance(exc, CoretaxWebhookTransformerError)

    def test_faktur_not_found_error(self):
        exc = FakturNotFoundError("not found")
        assert isinstance(exc, CoretaxWebhookTransformerError)


# ============================================================================
# TESTS FOR CORETAX WEBHOOK SIGNATURE VERIFIER
# ============================================================================

class TestCoretaxWebhookSignatureVerifier:
    def test_construction_with_secret(self):
        instance = CoretaxWebhookSignatureVerifier("my-secret")
        assert instance.webhook_secret == "my-secret"
        assert instance.name == "CoretaxWebhookSignatureVerifier"

    def test_construction_without_secret_uses_env(self):
        with patch.dict(os.environ, {"CORETAX_WEBHOOK_SECRET": "env-secret"}):
            instance = CoretaxWebhookSignatureVerifier()
            assert instance.webhook_secret == "env-secret"

    def test_construction_without_secret_and_no_env_uses_default(self):
        with patch.dict(os.environ, {}, clear=True):
            instance = CoretaxWebhookSignatureVerifier()
            assert instance.webhook_secret == "change-me-in-production"

    def test_verify_correct_signature(self):
        instance = CoretaxWebhookSignatureVerifier("secret")
        payload = b"test-payload"
        expected = hmac.new(b"secret", payload, hashlib.sha256).hexdigest()
        result = instance.verify(payload, expected)
        assert result is True

    def test_verify_wrong_signature(self):
        instance = CoretaxWebhookSignatureVerifier("secret")
        payload = b"test-payload"
        result = instance.verify(payload, "wrong")
        assert result is False

    def test_verify_no_signature_skips(self):
        instance = CoretaxWebhookSignatureVerifier("secret")
        result = instance.verify(b"payload", "")
        assert result is True  # no signature provided, skip

    def test_verify_no_secret_skips(self):
        instance = CoretaxWebhookSignatureVerifier(None)
        result = instance.verify(b"payload", "anything")
        assert result is True

    def test_validate_when_secret_is_default(self):
        instance = CoretaxWebhookSignatureVerifier("change-me-in-production")
        result = instance.validate()
        assert result["is_valid"] is False
        assert "default value" in result["errors"][0]

    def test_validate_when_secret_is_secure(self):
        instance = CoretaxWebhookSignatureVerifier("real-secret")
        result = instance.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_to_dict(self):
        instance = CoretaxWebhookSignatureVerifier("secret")
        d = instance.to_dict()
        assert "has_secret" in d
        assert d["has_secret"] is True
        # Base fields
        assert d["name"] == "CoretaxWebhookSignatureVerifier"

    def test_to_dict_with_default_secret(self):
        instance = CoretaxWebhookSignatureVerifier("change-me-in-production")
        d = instance.to_dict()
        assert d["has_secret"] is False

    def test_from_dict(self):
        data = {
            "webhook_secret": "restored-secret",
            "version": 3,
            "transformer_id": "some-id"
        }
        instance = CoretaxWebhookSignatureVerifier.from_dict(data)
        assert instance.webhook_secret == "restored-secret"
        assert instance._version == 3
        assert instance._transformer_id == "some-id"

    def test_clone(self):
        instance = CoretaxWebhookSignatureVerifier("secret")
        clone = instance.clone()
        assert clone is not instance
        assert clone.webhook_secret == "secret"
        assert clone._version == instance._version + 1
        assert len(clone._audit_trail) == 1

    def test_get_secret_from_config(self):
        with patch.dict(os.environ, {"CORETAX_WEBHOOK_SECRET": "env-test"}):
            instance = CoretaxWebhookSignatureVerifier()
            secret = instance._get_secret_from_config()
            assert secret == "env-test"

        with patch.dict(os.environ, {}, clear=True):
            instance = CoretaxWebhookSignatureVerifier()
            secret = instance._get_secret_from_config()
            assert secret == "change-me-in-production"


# ============================================================================
# TESTS FOR CORETAX WEBHOOK PAYLOAD VALIDATOR
# ============================================================================

class TestCoretaxWebhookPayloadValidator:
    def test_construction(self):
        instance = CoretaxWebhookPayloadValidator()
        assert instance.name == "CoretaxWebhookPayloadValidator"

    def test_validate_faktur_payload_success(self):
        instance = CoretaxWebhookPayloadValidator()
        payload = {
            "faktur_number": "F-001",
            "status": "3",
            "approval_code": "APP-001",
            "tanggal_approval": "2024-01-01",
            "npwp": "1234567890",
            "alasan_penolakan": None,
        }
        result = instance.validate_faktur_payload(payload)
        assert result["faktur_number"] == "F-001"
        assert result["status_code"] == "3"
        assert result["status"] == "approved"
        assert result["approval_code"] == "APP-001"
        assert result["approval_date"] == "2024-01-01"
        assert result["rejection_reason"] is None
        assert result["npwp"] == "1234567890"

    def test_validate_faktur_payload_missing_field(self):
        instance = CoretaxWebhookPayloadValidator()
        payload = {"faktur_number": "F-001"}  # missing status
        with pytest.raises(WebhookPayloadError, match="Missing required field: status"):
            instance.validate_faktur_payload(payload)

    def test_validate_faktur_payload_unknown_status(self):
        instance = CoretaxWebhookPayloadValidator()
        payload = {"faktur_number": "F-001", "status": "99"}
        result = instance.validate_faktur_payload(payload)
        assert result["status"] == "unknown"

    def test_validate_spt_payload_success(self):
        instance = CoretaxWebhookPayloadValidator()
        payload = {
            "spt_number": "SPT-001",
            "status": "approved",
            "tracking_id": "TRK-001",
            "approval_date": "2024-01-01",
            "rejection_reason": None,
            "npwp": "1234567890",
        }
        result = instance.validate_spt_payload(payload)
        assert result["spt_number"] == "SPT-001"
        assert result["status"] == "approved"
        assert result["tracking_id"] == "TRK-001"
        assert result["approval_date"] == "2024-01-01"
        assert result["rejection_reason"] is None
        assert result["npwp"] == "1234567890"

    def test_validate_spt_payload_missing_field(self):
        instance = CoretaxWebhookPayloadValidator()
        payload = {"spt_number": "SPT-001"}  # missing status
        with pytest.raises(WebhookPayloadError, match="Missing required field: status"):
            instance.validate_spt_payload(payload)

    def test_validate_spt_payload_unknown_status(self):
        instance = CoretaxWebhookPayloadValidator()
        payload = {"spt_number": "SPT-001", "status": "unknown"}
        result = instance.validate_spt_payload(payload)
        assert result["status"] == "unknown"

    def test_validate_bupot_payload_success(self):
        instance = CoretaxWebhookPayloadValidator()
        payload = {
            "bupot_number": "BUPOT-001",
            "status": "approved",
            "coretax_id": "C-001",
            "approval_code": "APP-001",
            "npwp": "1234567890",
        }
        result = instance.validate_bupot_payload(payload)
        assert result["bupot_number"] == "BUPOT-001"
        assert result["status"] == "approved"
        assert result["coretax_id"] == "C-001"
        assert result["approval_code"] == "APP-001"
        assert result["npwp"] == "1234567890"

    def test_validate_bupot_payload_missing_field(self):
        instance = CoretaxWebhookPayloadValidator()
        payload = {"bupot_number": "BUPOT-001"}  # missing status
        with pytest.raises(WebhookPayloadError, match="Missing required field: status"):
            instance.validate_bupot_payload(payload)

    def test_validate_bupot_payload_unknown_status(self):
        instance = CoretaxWebhookPayloadValidator()
        payload = {"bupot_number": "BUPOT-001", "status": "unknown"}
        result = instance.validate_bupot_payload(payload)
        assert result["status"] == "unknown"

    def test_validate_emeterai_payload_success(self):
        instance = CoretaxWebhookPayloadValidator()
        payload = {
            "meterai_code": "M-001",
            "status": "active",
            "used_at": "2024-01-01",
            "document_id": "DOC-001",
            "npwp": "1234567890",
        }
        result = instance.validate_emeterai_payload(payload)
        assert result["meterai_code"] == "M-001"
        assert result["status"] == "active"
        assert result["used_at"] == "2024-01-01"
        assert result["used_on_document"] == "DOC-001"
        assert result["npwp"] == "1234567890"

    def test_validate_emeterai_payload_missing_field(self):
        instance = CoretaxWebhookPayloadValidator()
        payload = {"meterai_code": "M-001"}  # missing status
        with pytest.raises(WebhookPayloadError, match="Missing required field: status"):
            instance.validate_emeterai_payload(payload)

    def test_validate_emeterai_payload_unknown_status(self):
        instance = CoretaxWebhookPayloadValidator()
        payload = {"meterai_code": "M-001", "status": "unknown"}
        result = instance.validate_emeterai_payload(payload)
        assert result["status"] == "unknown"

    def test_validate_ntpn_payload_success(self):
        instance = CoretaxWebhookPayloadValidator()
        payload = {
            "ntpn": "NTPN-001",
            "isValid": True,
            "amount": "1000000",
            "payment_date": "2024-01-01",
            "taxpayer_id": "1234567890",
            "tax_type": "ppn",
            "period": "2024-01",
        }
        result = instance.validate_ntpn_payload(payload)
        assert result["ntpn"] == "NTPN-001"
        assert result["is_valid"] is True
        assert result["amount"] == "1000000"
        assert result["payment_date"] == "2024-01-01"
        assert result["taxpayer_id"] == "1234567890"
        assert result["tax_type"] == "ppn"
        assert result["period"] == "2024-01"

    def test_validate_ntpn_payload_missing_field(self):
        instance = CoretaxWebhookPayloadValidator()
        payload = {"ntpn": "NTPN-001"}  # missing isValid
        with pytest.raises(WebhookPayloadError, match="Missing required field: isValid"):
            instance.validate_ntpn_payload(payload)

    def test_validate(self):
        instance = CoretaxWebhookPayloadValidator()
        result = instance.validate()
        assert result == {"is_valid": True, "errors": []}

    def test_to_dict(self):
        instance = CoretaxWebhookPayloadValidator()
        d = instance.to_dict()
        assert d["name"] == "CoretaxWebhookPayloadValidator"
        assert "transformer_id" in d

    def test_from_dict(self):
        data = {"version": 2, "transformer_id": "some-id"}
        instance = CoretaxWebhookPayloadValidator.from_dict(data)
        assert instance._version == 2
        assert instance._transformer_id == "some-id"

    def test_clone(self):
        instance = CoretaxWebhookPayloadValidator()
        clone = instance.clone()
        assert clone is not instance
        assert clone._version == instance._version + 1
        assert len(clone._audit_trail) == 1


# ============================================================================
# TESTS FOR CORETAX WEBHOOK TO TAX COMMAND TRANSFORMER
# ============================================================================

class TestCoretaxWebhookToTaxCommandTransformer:
    def test_construction(self, transformer):
        assert transformer.name == "CoretaxWebhookToTaxCommandTransformer"
        assert transformer._command_bus is not None
        assert transformer._coretax_service is not None
        assert transformer._tax_service is not None
        assert transformer._signature_verifier is not None
        assert transformer._payload_validator is not None

    @pytest.mark.asyncio
    async def test_transform_health_webhook(self, transformer, mock_envelope):
        mock_envelope.event_type = "coretax.health.webhook"
        mock_envelope.payload = {"status": "healthy", "message": "OK"}
        await transformer.transform(mock_envelope)
        transformer._command_bus.dispatch.assert_called_once()
        call_args = transformer._command_bus.dispatch.call_args[0][0]
        assert call_args["type"] == "system.setting.set"
        assert call_args["data"]["key"] == "coretax.api.health_status"
        assert call_args["data"]["value"] == "healthy"
        assert mock_envelope.id in transformer._processed_events

    @pytest.mark.asyncio
    async def test_transform_health_unhealthy_triggers_alert(self, transformer, mock_envelope):
        mock_envelope.event_type = "coretax.health.webhook"
        mock_envelope.payload = {"status": "unhealthy", "message": "API down"}
        with patch("transformers.coretax_webhook_to_tax_command.trigger_alert") as mock_alert:
            await transformer.transform(mock_envelope)
            mock_alert.assert_called_once()
            mock_alert.assert_called_with(
                title="Coretax API Health Alert",
                message="Coretax API status: unhealthy. Message: API down",
                severity="critical",
                source="CoretaxWebhookToTaxCommandTransformer",
            )

    @pytest.mark.asyncio
    async def test_transform_faktur_webhook(self, transformer, mock_envelope):
        mock_envelope.event_type = "coretax.faktur.webhook"
        mock_envelope.payload = {
            "faktur_number": "F-001",
            "status": "3",
            "approval_code": "APP-001",
            "tanggal_approval": "2024-01-01",
            "npwp": "1234567890",
        }
        await transformer.transform(mock_envelope)
        # Should call get_faktur_by_number and dispatch
        transformer._tax_service.get_faktur_by_number.assert_called_once_with("F-001", "1234567890")
        transformer._command_bus.dispatch.assert_called()
        call_args = transformer._command_bus.dispatch.call_args[0][0]
        assert call_args["type"] == "tax.faktur.update_status"
        assert call_args["data"]["faktur_id"] == "fact-123"
        assert call_args["data"]["status"] == "approved"

    @pytest.mark.asyncio
    async def test_transform_faktur_not_found(self, transformer, mock_envelope):
        transformer._tax_service.get_faktur_by_number.return_value = None
        mock_envelope.event_type = "coretax.faktur.webhook"
        mock_envelope.payload = {
            "faktur_number": "F-999",
            "status": "3",
            "npwp": "1234567890",
        }
        with pytest.raises(FakturNotFoundError):
            await transformer.transform(mock_envelope)

    @pytest.mark.asyncio
    async def test_transform_faktur_approved_updates_invoice(self, transformer, mock_envelope):
        # When faktur approved and has reference_id, it should update related invoice
        transformer._tax_service.get_faktur_by_number.return_value = {
            "id": "fact-123",
            "reference_id": "ref-456",
            "npwp": "1234567890",
        }
        mock_envelope.event_type = "coretax.faktur.webhook"
        mock_envelope.payload = {
            "faktur_number": "F-001",
            "status": "3",  # approved
            "approval_code": "APP-001",
            "tanggal_approval": "2024-01-01",
            "npwp": "1234567890",
        }
        await transformer.transform(mock_envelope)
        # Should dispatch both update_status and invoice update
        assert transformer._command_bus.dispatch.call_count == 2
        calls = transformer._command_bus.dispatch.call_args_list
        # Second call is for invoice update
        second_call = calls[1][0][0]
        assert second_call["type"] == "tax.invoice.update_faktur"
        assert second_call["data"]["invoice_id"] == "ref-456"
        assert second_call["data"]["faktur_number"] == "F-001"

    @pytest.mark.asyncio
    async def test_transform_spt_webhook(self, transformer, mock_envelope):
        mock_envelope.event_type = "coretax.spt.webhook"
        mock_envelope.payload = {
            "spt_number": "SPT-001",
            "status": "approved",
            "tracking_id": "TRK-001",
            "approval_date": "2024-01-01",
            "npwp": "1234567890",
        }
        await transformer.transform(mock_envelope)
        transformer._command_bus.dispatch.assert_called_once()
        call_args = transformer._command_bus.dispatch.call_args[0][0]
        assert call_args["type"] == "tax.spt.update_status"
        assert call_args["data"]["spt_number"] == "SPT-001"
        assert call_args["data"]["status"] == "approved"

    @pytest.mark.asyncio
    async def test_transform_bupot_webhook(self, transformer, mock_envelope):
        mock_envelope.event_type = "coretax.bupot.webhook"
        mock_envelope.payload = {
            "bupot_number": "BUPOT-001",
            "status": "approved",
            "coretax_id": "C-001",
            "approval_code": "APP-001",
            "npwp": "1234567890",
        }
        await transformer.transform(mock_envelope)
        transformer._command_bus.dispatch.assert_called_once()
        call_args = transformer._command_bus.dispatch.call_args[0][0]
        assert call_args["type"] == "tax.bupot.update_status"
        assert call_args["data"]["bupot_number"] == "BUPOT-001"
        assert call_args["data"]["status"] == "approved"

    @pytest.mark.asyncio
    async def test_transform_emeterai_webhook(self, transformer, mock_envelope):
        mock_envelope.event_type = "coretax.emeterai.webhook"
        mock_envelope.payload = {
            "meterai_code": "M-001",
            "status": "active",
            "used_at": "2024-01-01",
            "document_id": "DOC-001",
            "npwp": "1234567890",
        }
        await transformer.transform(mock_envelope)
        transformer._command_bus.dispatch.assert_called_once()
        call_args = transformer._command_bus.dispatch.call_args[0][0]
        assert call_args["type"] == "tax.emeterai.update_status"
        assert call_args["data"]["meterai_code"] == "M-001"
        assert call_args["data"]["status"] == "active"

    @pytest.mark.asyncio
    async def test_transform_ntpn_webhook(self, transformer, mock_envelope):
        mock_envelope.event_type = "coretax.ntpn.webhook"
        mock_envelope.payload = {
            "ntpn": "NTPN-001",
            "isValid": True,
            "amount": "1000000",
            "payment_date": "2024-01-01",
            "taxpayer_id": "1234567890",
            "tax_type": "ppn",
            "period": "2024-01",
        }
        await transformer.transform(mock_envelope)
        # Should call record_ntpn_validation and then update spt payment
        transformer._tax_service.record_ntpn_validation.assert_called_once()
        # Also dispatch payment update
        assert transformer._command_bus.dispatch.call_count == 1
        call_args = transformer._command_bus.dispatch.call_args[0][0]
        assert call_args["type"] == "tax.spt.update_payment"
        assert call_args["data"]["ntpn"] == "NTPN-001"

    @pytest.mark.asyncio
    async def test_transform_ntpn_invalid_does_not_update_spt(self, transformer, mock_envelope):
        mock_envelope.event_type = "coretax.ntpn.webhook"
        mock_envelope.payload = {
            "ntpn": "NTPN-001",
            "isValid": False,
            "taxpayer_id": "1234567890",
        }
        await transformer.transform(mock_envelope)
        transformer._tax_service.record_ntpn_validation.assert_called_once()
        # Should NOT dispatch spt payment update
        transformer._command_bus.dispatch.assert_not_called()

    @pytest.mark.asyncio
    async def test_transform_unknown_event_type(self, transformer, mock_envelope):
        mock_envelope.event_type = "unknown.event"
        await transformer.transform(mock_envelope)
        # Should not call any dispatch
        transformer._command_bus.dispatch.assert_not_called()
        assert mock_envelope.id not in transformer._processed_events

    @pytest.mark.asyncio
    async def test_transform_already_processed(self, transformer, mock_envelope):
        mock_envelope.id = "evt-123"
        transformer._processed_events.add("evt-123")
        await transformer.transform(mock_envelope)
        transformer._command_bus.dispatch.assert_not_called()

    @pytest.mark.asyncio
    async def test_transform_invalid_signature_raises(self, transformer, mock_envelope):
        mock_envelope.event_type = "coretax.faktur.webhook"
        mock_envelope.metadata = {
            "signature": "wrong",
            "raw_payload": "payload",
        }
        # Make verify return False
        with patch.object(transformer._signature_verifier, 'verify', return_value=False):
            with pytest.raises(InvalidSignatureError):
                await transformer.transform(mock_envelope)
            # Should also trigger alert
            with patch("transformers.coretax_webhook_to_tax_command.trigger_alert") as mock_alert:
                try:
                    await transformer.transform(mock_envelope)
                except InvalidSignatureError:
                    pass
                mock_alert.assert_called_once()

    @pytest.mark.asyncio
    async def test_transform_general_exception_triggers_alert(self, transformer, mock_envelope):
        mock_envelope.event_type = "coretax.faktur.webhook"
        transformer._tax_service.get_faktur_by_number.side_effect = Exception("DB error")
        with patch("transformers.coretax_webhook_to_tax_command.trigger_alert") as mock_alert:
            with pytest.raises(Exception, match="DB error"):
                await transformer.transform(mock_envelope)
            mock_alert.assert_called_once()
            args, kwargs = mock_alert.call_args
            assert kwargs["title"] == "Coretax Webhook Transformation Failed"

    def test_reset(self, transformer):
        transformer._processed_events.add("evt-1")
        old_version = transformer._version
        transformer.reset()
        assert len(transformer._processed_events) == 0
        assert transformer._version == old_version + 1

    def test_validate(self, transformer):
        result = transformer.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_fails_when_signature_verifier_missing(self, transformer):
        transformer._signature_verifier = None
        result = transformer.validate()
        assert result["is_valid"] is False
        assert "Signature verifier not initialized" in result["errors"]

    def test_validate_fails_when_payload_validator_missing(self, transformer):
        transformer._payload_validator = None
        result = transformer.validate()
        assert result["is_valid"] is False
        assert "Payload validator not initialized" in result["errors"]

    def test_to_dict(self, transformer):
        transformer._processed_events.add("evt-1")
        d = transformer.to_dict()
        assert d["name"] == "CoretaxWebhookToTaxCommandTransformer"
        assert d["processed_events_count"] == 1
        assert "signature_verifier" in d
        assert "payload_validator" in d

    def test_from_dict(self):
        data = {
            "version": 5,
            "transformer_id": "some-id",
        }
        instance = CoretaxWebhookToTaxCommandTransformer.from_dict(data)
        assert instance._version == 5
        assert instance._transformer_id == "some-id"
        assert instance._command_bus is None
        assert instance._coretax_service is None
        assert instance._tax_service is None
        assert instance._signature_verifier is not None
        assert instance._payload_validator is not None
        assert instance._processed_events == set()

    def test_clone(self, transformer):
        clone = transformer.clone()
        assert clone is not transformer
        assert clone._version == transformer._version + 1
        assert clone._command_bus == transformer._command_bus
        assert clone._coretax_service == transformer._coretax_service
        assert clone._tax_service == transformer._tax_service
        assert len(clone._audit_trail) == 1

    def test_snapshot(self, transformer):
        transformer._processed_events.add("evt-1")
        snap = transformer.snapshot()
        assert snap["name"] == transformer.name
        assert snap["version"] == transformer._version
        assert snap["processed_events_count"] == 1

    def test_touch(self, transformer):
        old_version = transformer._version
        result = transformer.touch("admin")
        assert result is transformer
        assert transformer._version == old_version + 1
        assert len(transformer._audit_trail) == 1

    # Test private methods indirectly or directly
    @pytest.mark.asyncio
    async def test_update_related_invoice(self, transformer):
        await transformer._update_related_invoice(UUID("12345678-1234-1234-1234-123456789012"), "F-001")
        transformer._command_bus.dispatch.assert_called_once()
        call_args = transformer._command_bus.dispatch.call_args[0][0]
        assert call_args["type"] == "tax.invoice.update_faktur"

    @pytest.mark.asyncio
    async def test_update_spt_payment_status(self, transformer):
        await transformer._update_spt_payment_status("ppn", "2024-01", "NTPN-001", "1234567890")
        transformer._command_bus.dispatch.assert_called_once()
        call_args = transformer._command_bus.dispatch.call_args[0][0]
        assert call_args["type"] == "tax.spt.update_payment"
        assert call_args["data"]["ntpn"] == "NTPN-001"
        assert call_args["data"]["payment_status"] == "paid"

    def test_parse_date(self, transformer):
        # None
        assert transformer._parse_date(None) is None
        # date object
        d = date(2024, 1, 1)
        assert transformer._parse_date(d) == d
        # ISO string
        assert transformer._parse_date("2024-01-01T12:00:00") == date(2024, 1, 1)
        # YYYY-MM-DD
        assert transformer._parse_date("2024-01-01") == date(2024, 1, 1)
        # Invalid string
        assert transformer._parse_date("invalid") is None


# ============================================================================
# TESTS FOR FACTORY FUNCTIONS
# ============================================================================

@pytest.mark.asyncio
async def test_get_coretax_webhook_transformer_creates_new():
    with patch("transformers.coretax_webhook_to_tax_command._coretax_webhook_transformer", None):
        with patch("transformers.coretax_webhook_to_tax_command.get_container") as mock_container:
            container = MagicMock()
            container.resolve = MagicMock(return_value=AsyncMock())
            mock_container.return_value = container
            transformer = await get_coretax_webhook_transformer()
            assert transformer is not None
            assert transformer._command_bus is not None
            assert transformer._coretax_service is not None
            assert transformer._tax_service is not None


@pytest.mark.asyncio
async def test_get_coretax_webhook_transformer_uses_cached():
    with patch("transformers.coretax_webhook_to_tax_command._coretax_webhook_transformer", None):
        # First call creates
        with patch("transformers.coretax_webhook_to_tax_command.get_container") as mock_container:
            container = MagicMock()
            container.resolve = MagicMock(return_value=AsyncMock())
            mock_container.return_value = container
            transformer1 = await get_coretax_webhook_transformer()
            transformer2 = await get_coretax_webhook_transformer()
            assert transformer1 is transformer2


@pytest.mark.asyncio
async def test_get_coretax_webhook_transformer_fallback_to_mocks():
    with patch("transformers.coretax_webhook_to_tax_command._coretax_webhook_transformer", None):
        with patch("transformers.coretax_webhook_to_tax_command.get_container", side_effect=Exception("Container error")):
            transformer = await get_coretax_webhook_transformer()
            assert transformer is not None
            # Should use mocks
            assert transformer._command_bus is not None
            assert transformer._coretax_service is not None
            assert transformer._tax_service is not None


@pytest.mark.asyncio
async def test_handle_coretax_webhook():
    with patch("transformers.coretax_webhook_to_tax_command.get_coretax_webhook_transformer") as mock_get:
        mock_transformer = AsyncMock()
        mock_get.return_value = mock_transformer
        envelope = MagicMock()
        await handle_coretax_webhook(envelope)
        mock_transformer.transform.assert_called_once_with(envelope)
