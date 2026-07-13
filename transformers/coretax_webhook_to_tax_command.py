#!/usr/bin/env python3
"""
Module: coretax_webhook_to_tax_command.py
Layer: Transformers
Responsibility: Mentransformasi webhook dari sistem Coretax DJP menjadi command
               untuk update status faktur pajak, SPT, e-Bupot, dan e-Meterai.

Metode yang ditambahkan:
- BaseTransformer dengan entity dasar: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk CoretaxWebhookSignatureVerifier, CoretaxWebhookPayloadValidator, CoretaxWebhookToTaxCommandTransformer.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from application.commands_cqrs.command_bus_unified import UnifiedCommandBus
from application.service_layer.service_coretax import CoretaxService
from application.service_layer.service_tax import TaxService
from infrastructure.telemetry.alert_manager_router import trigger_alert
from infrastructure.telemetry.structured_json_logging import get_logger

if TYPE_CHECKING:
    from event_gateway.event_gate_singleton import EventEnvelope

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================
HANDLED_EVENT_TYPES = [
    "coretax.faktur.webhook",
    "coretax.spt.webhook",
    "coretax.bupot.webhook",
    "coretax.emeterai.webhook",
    "coretax.ntpn.webhook",
    "coretax.health.webhook",
]

FAKTUR_STATUS_MAP = {
    "1": "draft",
    "2": "submitted",
    "3": "approved",
    "4": "rejected",
    "5": "cancelled",
    "6": "expired",
}
SPT_STATUS_MAP = {
    "draft": "draft",
    "submitted": "submitted",
    "approved": "approved",
    "rejected": "rejected",
    "void": "void",
}
BUPOT_STATUS_MAP = {
    "draft": "draft",
    "submitted": "submitted",
    "approved": "approved",
    "rejected": "rejected",
    "cancelled": "cancelled",
}
EMETERAI_STATUS_MAP = {
    "active": "active",
    "used": "used",
    "expired": "expired",
    "revoked": "revoked",
}


# ============================================================================
# BaseTransformer
# ============================================================================
class BaseTransformer:
    def __init__(self, name: str):
        self.name = name
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._transformer_id = str(uuid4())

    def _take_snapshot(self):
        import datetime
        self._snapshots.append(
            {
                "version": self._version,
                "transformer_id": self._transformer_id,
                "name": self.name,
                "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        import datetime
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
                "version": self._version,
                "transformer_id": self._transformer_id,
                "details": details,
            }
        )

    def validate(self) -> dict[str, Any]:
        return {"is_valid": True, "errors": []}

    def to_dict(self) -> dict[str, Any]:
        return {"transformer_id": self._transformer_id, "name": self.name, "version": self._version}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BaseTransformer:
        instance = cls(data["name"])
        instance._version = data.get("version", 1)
        instance._transformer_id = data.get("transformer_id", str(uuid4()))
        return instance

    def clone(self) -> BaseTransformer:
        new = self.__class__(self.name)
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self._transformer_id})
        return new

    def snapshot(self) -> dict[str, Any]:
        import datetime
        return {
            "version": self._version,
            "transformer_id": self._transformer_id,
            "name": self.name,
            "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> BaseTransformer:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# ============================================================================
# EXCEPTIONS
# ============================================================================
class CoretaxWebhookTransformerError(Exception):
    pass


class InvalidSignatureError(CoretaxWebhookTransformerError):
    pass


class WebhookPayloadError(CoretaxWebhookTransformerError):
    pass


class FakturNotFoundError(CoretaxWebhookTransformerError):
    pass


# ============================================================================
# CoretaxWebhookSignatureVerifier (dengan entity dasar)
# ============================================================================
class CoretaxWebhookSignatureVerifier(BaseTransformer):
    def __init__(self, webhook_secret: str | None = None):
        super().__init__("CoretaxWebhookSignatureVerifier")
        self.webhook_secret = webhook_secret or self._get_secret_from_config()

    def _get_secret_from_config(self) -> str:
        import os
        return os.environ.get("CORETAX_WEBHOOK_SECRET", "change-me-in-production")

    def verify(self, payload_body: bytes, signature: str) -> bool:
        if not signature or not self.webhook_secret:
            logger.warning("No signature or verification key configured, skipping verification")
            return True
        expected = hmac.new(
            self.webhook_secret.encode("utf-8"), payload_body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    def validate(self) -> dict[str, Any]:
        errors = []
        if not self.webhook_secret or self.webhook_secret == "change-me-in-production":
            errors.append("Webhook secret is using default value, please configure in production")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["has_secret"] = bool(
            self.webhook_secret and self.webhook_secret != "change-me-in-production"
        )
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CoretaxWebhookSignatureVerifier:
        instance = cls(webhook_secret=data.get("webhook_secret"))
        instance._version = data.get("version", 1)
        instance._transformer_id = data.get("transformer_id", str(uuid4()))
        return instance

    def clone(self) -> CoretaxWebhookSignatureVerifier:
        new = CoretaxWebhookSignatureVerifier(self.webhook_secret)
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self._transformer_id})
        return new


# ============================================================================
# CoretaxWebhookPayloadValidator (dengan entity dasar)
# ============================================================================
class CoretaxWebhookPayloadValidator(BaseTransformer):
    def __init__(self):
        super().__init__("CoretaxWebhookPayloadValidator")

    def validate_faktur_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        required_fields = ["faktur_number", "status"]
        for field in required_fields:
            if field not in payload:
                raise WebhookPayloadError(f"Missing required field: {field}")
        return {
            "faktur_number": payload["faktur_number"],
            "status_code": str(payload["status"]),
            "status": FAKTUR_STATUS_MAP.get(str(payload["status"]), "unknown"),
            "approval_code": payload.get("approval_code"),
            "approval_date": payload.get("tanggal_approval"),
            "rejection_reason": payload.get("alasan_penolakan"),
            "npwp": payload.get("npwp"),
        }

    def validate_spt_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        required_fields = ["spt_number", "status"]
        for field in required_fields:
            if field not in payload:
                raise WebhookPayloadError(f"Missing required field: {field}")
        return {
            "spt_number": payload["spt_number"],
            "tracking_id": payload.get("tracking_id"),
            "status": SPT_STATUS_MAP.get(payload["status"], "unknown"),
            "approval_date": payload.get("approval_date"),
            "rejection_reason": payload.get("rejection_reason"),
            "npwp": payload.get("npwp"),
        }

    def validate_bupot_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        required_fields = ["bupot_number", "status"]
        for field in required_fields:
            if field not in payload:
                raise WebhookPayloadError(f"Missing required field: {field}")
        return {
            "bupot_number": payload["bupot_number"],
            "coretax_id": payload.get("coretax_id"),
            "status": BUPOT_STATUS_MAP.get(payload["status"], "unknown"),
            "approval_code": payload.get("approval_code"),
            "npwp": payload.get("npwp"),
        }

    def validate_emeterai_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        required_fields = ["meterai_code", "status"]
        for field in required_fields:
            if field not in payload:
                raise WebhookPayloadError(f"Missing required field: {field}")
        return {
            "meterai_code": payload["meterai_code"],
            "status": EMETERAI_STATUS_MAP.get(payload["status"], "unknown"),
            "used_at": payload.get("used_at"),
            "used_on_document": payload.get("document_id"),
            "npwp": payload.get("npwp"),
        }

    def validate_ntpn_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        required_fields = ["ntpn", "isValid"]
        for field in required_fields:
            if field not in payload:
                raise WebhookPayloadError(f"Missing required field: {field}")
        return {
            "ntpn": payload["ntpn"],
            "is_valid": payload["isValid"],
            "amount": payload.get("amount"),
            "payment_date": payload.get("payment_date"),
            "taxpayer_id": payload.get("taxpayer_id"),
            "tax_type": payload.get("tax_type"),
            "period": payload.get("period"),
        }

    def validate(self) -> dict[str, Any]:
        return {"is_valid": True, "errors": []}

    def to_dict(self) -> dict[str, Any]:
        return super().to_dict()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CoretaxWebhookPayloadValidator:
        instance = cls()
        instance._version = data.get("version", 1)
        instance._transformer_id = data.get("transformer_id", str(uuid4()))
        return instance

    def clone(self) -> CoretaxWebhookPayloadValidator:
        new = CoretaxWebhookPayloadValidator()
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self._transformer_id})
        return new


# ============================================================================
# CoretaxWebhookToTaxCommandTransformer (dengan entity dasar)
# ============================================================================
class CoretaxWebhookToTaxCommandTransformer(BaseTransformer):
    def __init__(
        self,
        command_bus: UnifiedCommandBus,
        coretax_service: CoretaxService,
        tax_service: TaxService,
    ):
        super().__init__("CoretaxWebhookToTaxCommandTransformer")
        self._command_bus = command_bus
        self._coretax_service = coretax_service
        self._tax_service = tax_service
        self._signature_verifier = CoretaxWebhookSignatureVerifier()
        self._payload_validator = CoretaxWebhookPayloadValidator()
        self._processed_events: set = set()

    async def transform(self, envelope: EventEnvelope) -> None:
        event_type = envelope.event_type
        event_id = str(envelope.id)
        event_payload = envelope.payload

        if event_id in self._processed_events:
            logger.debug(f"Event {event_id} already processed, skipping")
            return
        if event_type not in HANDLED_EVENT_TYPES:
            logger.debug(f"Event type {event_type} not handled")
            return

        logger.info(f"Transforming webhook {event_type} to tax command")

        signature = envelope.metadata.get("signature", "")
        raw_payload = envelope.metadata.get("raw_payload", "")
        if raw_payload:
            is_valid = self._signature_verifier.verify(raw_payload.encode("utf-8"), signature)
            if not is_valid:
                logger.error(f"Invalid signature for webhook {event_id}")
                await trigger_alert(
                    title="Coretax Webhook Invalid Signature",
                    message=f"Webhook {event_id} has invalid signature",
                    severity="critical",
                    source="CoretaxWebhookToTaxCommandTransformer",
                )
                raise InvalidSignatureError(f"Invalid signature for webhook {event_id}")

        try:
            if event_type == "coretax.faktur.webhook":
                await self._handle_faktur_webhook(event_payload, envelope)
            elif event_type == "coretax.spt.webhook":
                await self._handle_spt_webhook(event_payload, envelope)
            elif event_type == "coretax.bupot.webhook":
                await self._handle_bupot_webhook(event_payload, envelope)
            elif event_type == "coretax.emeterai.webhook":
                await self._handle_emeterai_webhook(event_payload, envelope)
            elif event_type == "coretax.ntpn.webhook":
                await self._handle_ntpn_webhook(event_payload, envelope)
            elif event_type == "coretax.health.webhook":
                await self._handle_health_webhook(event_payload, envelope)
            self._processed_events.add(event_id)
        except Exception as e:
            logger.exception(f"Failed to transform webhook {event_id}: {e}")
            await trigger_alert(
                title="Coretax Webhook Transformation Failed",
                message=f"Event: {event_type}, Error: {str(e)[:200]}",
                severity="error",
                source="CoretaxWebhookToTaxCommandTransformer",
            )
            raise

    async def _handle_faktur_webhook(
        self, payload: dict[str, Any], envelope: EventEnvelope
    ) -> None:
        validated = self._payload_validator.validate_faktur_payload(payload)
        faktur_number = validated["faktur_number"]
        new_status = validated["status"]
        approval_code = validated.get("approval_code")
        approval_date = validated.get("approval_date")
        rejection_reason = validated.get("rejection_reason")
        npwp = validated.get("npwp")
        faktur = await self._tax_service.get_faktur_by_number(faktur_number, npwp)
        if not faktur:
            logger.warning(f"Faktur {faktur_number} not found in system")
            raise FakturNotFoundError(f"Faktur {faktur_number} not found")
        await self._command_bus.dispatch(
            {
                "type": "tax.faktur.update_status",
                "data": {
                    "faktur_id": str(faktur["id"]),
                    "status": new_status,
                    "approval_code": approval_code,
                    "approval_date": approval_date,
                    "rejection_reason": rejection_reason,
                    "updated_by": str(UUID("00000000-0000-0000-0000-000000000000")),
                },
            }
        )
        logger.info(f"Faktur {faktur_number} status updated to {new_status}")
        if new_status == "approved" and faktur.get("reference_id"):
            await self._update_related_invoice(faktur["reference_id"], faktur_number)

    async def _handle_spt_webhook(self, payload: dict[str, Any], envelope: EventEnvelope) -> None:
        validated = self._payload_validator.validate_spt_payload(payload)
        spt_number = validated["spt_number"]
        tracking_id = validated.get("tracking_id")
        new_status = validated["status"]
        approval_date = validated.get("approval_date")
        rejection_reason = validated.get("rejection_reason")
        npwp = validated.get("npwp")
        await self._command_bus.dispatch(
            {
                "type": "tax.spt.update_status",
                "data": {
                    "spt_number": spt_number,
                    "tracking_id": tracking_id,
                    "status": new_status,
                    "approval_date": approval_date,
                    "rejection_reason": rejection_reason,
                    "npwp": npwp,
                    "updated_by": str(UUID("00000000-0000-0000-0000-000000000000")),
                },
            }
        )
        logger.info(f"SPT {spt_number} status updated to {new_status}")

    async def _handle_bupot_webhook(self, payload: dict[str, Any], envelope: EventEnvelope) -> None:
        validated = self._payload_validator.validate_bupot_payload(payload)
        bupot_number = validated["bupot_number"]
        coretax_id = validated.get("coretax_id")
        new_status = validated["status"]
        approval_code = validated.get("approval_code")
        npwp = validated.get("npwp")
        await self._command_bus.dispatch(
            {
                "type": "tax.bupot.update_status",
                "data": {
                    "bupot_number": bupot_number,
                    "coretax_id": coretax_id,
                    "status": new_status,
                    "approval_code": approval_code,
                    "npwp": npwp,
                    "updated_by": str(UUID("00000000-0000-0000-0000-000000000000")),
                },
            }
        )
        logger.info(f"e-Bupot {bupot_number} status updated to {new_status}")

    async def _handle_emeterai_webhook(
        self, payload: dict[str, Any], envelope: EventEnvelope
    ) -> None:
        validated = self._payload_validator.validate_emeterai_payload(payload)
        meterai_code = validated["meterai_code"]
        new_status = validated["status"]
        used_at = validated.get("used_at")
        used_on_document = validated.get("used_on_document")
        npwp = validated.get("npwp")
        await self._command_bus.dispatch(
            {
                "type": "tax.emeterai.update_status",
                "data": {
                    "meterai_code": meterai_code,
                    "status": new_status,
                    "used_at": used_at,
                    "used_on_document": used_on_document,
                    "npwp": npwp,
                    "updated_by": str(UUID("00000000-0000-0000-0000-000000000000")),
                },
            }
        )
        logger.info(f"e-Meterai {meterai_code} status updated to {new_status}")

    async def _handle_ntpn_webhook(self, payload: dict[str, Any], envelope: EventEnvelope) -> None:
        validated = self._payload_validator.validate_ntpn_payload(payload)
        ntpn = validated["ntpn"]
        is_valid = validated["is_valid"]
        amount = validated.get("amount")
        payment_date = validated.get("payment_date")
        taxpayer_id = validated.get("taxpayer_id")
        tax_type = validated.get("tax_type")
        period = validated.get("period")
        await self._tax_service.record_ntpn_validation(
            ntpn=ntpn,
            amount=Decimal(str(amount)) if amount else None,
            payment_date=self._parse_date(payment_date) if payment_date else None,
            npwp=taxpayer_id,
            is_valid=is_valid,
            result=validated,
        )
        logger.info(f"NTPN {ntpn} validation result: {is_valid}")
        if is_valid and tax_type and period:
            await self._update_spt_payment_status(tax_type, period, ntpn, taxpayer_id)

    async def _handle_health_webhook(
        self, payload: dict[str, Any], envelope: EventEnvelope
    ) -> None:
        status = payload.get("status", "unknown")
        message = payload.get("message", "")
        logger.info(f"Coretax health webhook received: status={status}, message={message}")
        await self._command_bus.dispatch(
            {
                "type": "system.setting.set",
                "data": {
                    "key": "coretax.api.health_status",
                    "value": status,
                    "updated_by": str(UUID("00000000-0000-0000-0000-000000000000")),
                },
            }
        )
        if status != "healthy":
            await trigger_alert(
                title="Coretax API Health Alert",
                message=f"Coretax API status: {status}. Message: {message}",
                severity="critical",
                source="CoretaxWebhookToTaxCommandTransformer",
            )

    async def _update_related_invoice(self, reference_id: UUID, faktur_number: str) -> None:
        await self._command_bus.dispatch(
            {
                "type": "tax.invoice.update_faktur",
                "data": {
                    "invoice_id": str(reference_id),
                    "faktur_number": faktur_number,
                    "faktur_status": "approved",
                },
            }
        )

    async def _update_spt_payment_status(
        self, tax_type: str, period: str, ntpn: str, npwp: str
    ) -> None:
        await self._command_bus.dispatch(
            {
                "type": "tax.spt.update_payment",
                "data": {
                    "tax_type": tax_type,
                    "period": period,
                    "npwp": npwp,
                    "ntpn": ntpn,
                    "payment_status": "paid",
                    "payment_date": datetime.now(UTC).isoformat(),
                },
            }
        )

    def _parse_date(self, date_value: Any) -> date | None:
        if date_value is None:
            return None
        if isinstance(date_value, date):
            return date_value
        if isinstance(date_value, str):
            try:
                return datetime.fromisoformat(date_value).date()
            except ValueError:
                try:
                    return datetime.strptime(date_value, "%Y-%m-%d").date()
                except ValueError:
                    return None
        return None

    async def reset(self) -> None:
        self._processed_events.clear()
        self._version += 1
        logger.info("CoretaxWebhookToTaxCommandTransformer reset")

    def validate(self) -> dict[str, Any]:
        errors = []
        if self._signature_verifier is None:
            errors.append("Signature verifier not initialized")
        if self._payload_validator is None:
            errors.append("Payload validator not initialized")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["processed_events_count"] = len(self._processed_events)
        data["signature_verifier"] = self._signature_verifier.to_dict()
        data["payload_validator"] = self._payload_validator.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CoretaxWebhookToTaxCommandTransformer:
        instance = cls.__new__(cls)
        instance._version = data.get("version", 1)
        instance._transformer_id = data.get("transformer_id", str(uuid4()))
        instance._command_bus = None
        instance._coretax_service = None
        instance._tax_service = None
        instance._signature_verifier = CoretaxWebhookSignatureVerifier()
        instance._payload_validator = CoretaxWebhookPayloadValidator()
        instance._processed_events = set()
        return instance

    def clone(self) -> CoretaxWebhookToTaxCommandTransformer:
        new = CoretaxWebhookToTaxCommandTransformer(
            command_bus=self._command_bus,
            coretax_service=self._coretax_service,
            tax_service=self._tax_service,
        )
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self._transformer_id})
        return new

    def snapshot(self) -> dict[str, Any]:
        snap = super().snapshot()
        snap["processed_events_count"] = len(self._processed_events)
        return snap

    def touch(self, touched_by: str) -> CoretaxWebhookToTaxCommandTransformer:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# ============================================================================
# TRANSFORMER FACTORY & EVENT HANDLER
# ============================================================================
_coretax_webhook_transformer: CoretaxWebhookToTaxCommandTransformer | None = None


async def get_coretax_webhook_transformer() -> CoretaxWebhookToTaxCommandTransformer:
    global _coretax_webhook_transformer
    if _coretax_webhook_transformer is None:
        from bootstrap.dependency_container.ioc_container import get_container

        container = get_container()
        command_bus = container.resolve(UnifiedCommandBus)
        coretax_service = container.resolve(CoretaxService)
        tax_service = container.resolve(TaxService)
        _coretax_webhook_transformer = CoretaxWebhookToTaxCommandTransformer(
            command_bus=command_bus,
            coretax_service=coretax_service,
            tax_service=tax_service,
        )
    return _coretax_webhook_transformer


async def handle_coretax_webhook(envelope: EventEnvelope) -> None:
    transformer = await get_coretax_webhook_transformer()
    await transformer.transform(envelope)


__all__ = [
    "CoretaxWebhookToTaxCommandTransformer",
    "CoretaxWebhookTransformerError",
    "FakturNotFoundError",
    "InvalidSignatureError",
    "WebhookPayloadError",
    "get_coretax_webhook_transformer",
    "handle_coretax_webhook",
]
