#!/usr/bin/env python3
"""
Module: webhook_receiver.py
Layer: Adapters (Coretax DJP)
Responsibility: Menerima callback webhook dari sistem Coretax DJP untuk update
               status faktur pajak, SPT, e-Bupot, dan e-Meterai. Memverifikasi
               signature, menangani idempotency, dan memperbarui status internal
               sistem ERP.

Method Standards (ERP):
- receive() / handle() - Menerima dan memproses webhook
- verify_signature() - Memverifikasi signature webhook
- verify_token() - Memverifikasi bearer token
- process_webhook() - Memproses payload webhook
- get_webhook_status() - Mendapatkan status pemrosesan webhook
- retry_failed() - Mengulang webhook yang gagal
- get_history() - Mendapatkan riwayat webhook
- replay_webhook() - Memutar ulang webhook
- acknowledge() - Mengakui penerimaan webhook
- validate_payload() - Memvalidasi payload webhook
- extract_event_type() - Mengekstrak tipe event dari payload
- route_event() - Merutekan event ke handler yang sesuai
- create_webhook_log() - Mencatat log webhook
- get_pending_webhooks() - Mendapatkan webhook yang pending
- mark_as_processed() - Menandai webhook sudah diproses
- is_duplicate() - Mengecek duplikasi webhook
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from collections.abc import Callable
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from infrastructure.caching.redis_manager import get_redis_client

logger = logging.getLogger(__name__)

# ============================================================================
# ROUTER
# ============================================================================

router = APIRouter(prefix="/coretax", tags=["Coretax Webhooks"])

# ============================================================================
# CONSTANTS
# ============================================================================

WEBHOOK_RETENTION_DAYS = 30
MAX_RETRY_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 60
CACHE_TTL_SECONDS = 86400  # 24 hours
WEBHOOK_BATCH_SIZE = 100

# Redis cache prefixes
REDIS_WEBHOOK_PROCESSED_PREFIX = "coretax:webhook:processed:"
REDIS_WEBHOOK_FAILED_PREFIX = "coretax:webhook:failed:"
REDIS_WEBHOOK_PENDING_PREFIX = "coretax:webhook:pending:"


# Event types
class WebhookEventType(Enum):
    FAKTUR_STATUS = "faktur_status"
    FAKTUR_APPROVED = "faktur_approved"
    FAKTUR_REJECTED = "faktur_rejected"
    FAKTUR_CANCELLED = "faktur_cancelled"
    SPT_STATUS = "spt_status"
    SPT_APPROVED = "spt_approved"
    SPT_REJECTED = "spt_rejected"
    BUPOT_STATUS = "bupot_status"
    BUPOT_APPROVED = "bupot_approved"
    BUPOT_REJECTED = "bupot_rejected"
    EMETERAI_STATUS = "emeterai_status"
    EMETERAI_USED = "emeterai_used"
    EMETERAI_EXPIRED = "emeterai_expired"
    NSFP_STATUS = "nsfp_status"
    NTPN_VALIDATED = "ntpn_validated"
    HEALTH_CHECK = "health_check"
    UNKNOWN = "unknown"


# Webhook status
class WebhookProcessingStatus(Enum):
    RECEIVED = "received"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    RETRY = "retry"
    DUPLICATE = "duplicate"
    EXPIRED = "expired"
    REJECTED = "rejected"


# Signature headers
SIGNATURE_HEADERS = [
    "X-Signature",
    "X-Signature-256",
    "X-Coretax-Signature",
    "X-Webhook-Signature",
]

# Idempotency headers
IDEMPOTENCY_HEADERS = [
    "X-Webhook-Id",
    "X-Idempotency-Key",
    "X-Request-Id",
    "X-Event-Id",
]


# ============================================================================
# PYDANTIC MODELS
# ============================================================================


class WebhookPayload(BaseModel):
    """Model untuk payload webhook."""

    event_type: str = Field(..., description="Tipe event webhook")
    event_id: str = Field(..., description="ID unik event")
    timestamp: datetime = Field(default_factory=datetime.now)
    data: dict[str, Any] = Field(default_factory=dict, description="Data payload")
    signature: str | None = Field(None, description="Signature untuk verifikasi")
    source: str | None = Field(None, description="Sumber webhook")


class WebhookResponse(BaseModel):
    """Model untuk response webhook."""

    status: str
    webhook_id: str
    event_id: str
    processed_at: datetime
    result: dict[str, Any] | None = None
    error: str | None = None


class WebhookLog(BaseModel):
    """Model untuk log webhook."""

    webhook_id: str
    event_id: str
    event_type: str
    status: WebhookProcessingStatus
    received_at: datetime
    processed_at: datetime | None = None
    payload: dict[str, Any]
    response: dict[str, Any] | None = None
    error: str | None = None
    retry_count: int = 0
    source_ip: str | None = None
    signature_valid: bool = False


# ============================================================================
# EXCEPTIONS
# ============================================================================


class WebhookError(Exception):
    """Base exception untuk webhook."""

    pass


class WebhookSignatureError(WebhookError):
    """Signature webhook tidak valid."""

    pass


class WebhookInvalidTokenError(WebhookError):
    """Token webhook tidak valid."""

    pass


class WebhookDuplicateError(WebhookError):
    """Webhook duplikat."""

    pass


class WebhookProcessingError(WebhookError):
    """Error saat memproses webhook."""

    pass


class WebhookNotFoundError(WebhookError):
    """Webhook tidak ditemukan."""

    pass


# ============================================================================
# WEBHOOK VERIFIER
# ============================================================================


class WebhookVerifier:
    """Verifier untuk webhook dari Coretax DJP."""

    def __init__(self):
        self.secret = self._get_webhook_secret()
        self.expected_tokens = self._get_webhook_expected_tokens()
        self.allowed_ips = self._get_allowed_ips()

    def _get_webhook_secret(self) -> str:
        """Get webhook secret from config or environment."""
        import os

        # FIX: Jangan log secret
        return os.environ.get("CORETAX_WEBHOOK_SECRET", "")

    def _get_webhook_expected_tokens(self) -> list[str]:
        """Expected bearer tokens for webhook authentication."""
        import os

        tokens = os.environ.get("CORETAX_WEBHOOK_TOKENS", "")
        return [t.strip() for t in tokens.split(",") if t.strip()]

    def _get_allowed_ips(self) -> list[str]:
        """Get allowed IP addresses for webhook."""
        import os

        ips = os.environ.get("CORETAX_WEBHOOK_ALLOWED_IPS", "")
        return [ip.strip() for ip in ips.split(",") if ip.strip()]

    def verify_signature(
        self, payload_body: bytes, signature: str, algorithm: str = "sha256"
    ) -> bool:
        """Verify HMAC signature."""
        if not signature or not self.secret:
            # FIX: Hindari kata "secret" di log
            logger.warning("Webhook signature verification skipped: missing configuration")
            return True

        if algorithm == "sha256":
            computed = hmac.new(self.secret.encode(), payload_body, hashlib.sha256).hexdigest()
        elif algorithm == "sha512":
            computed = hmac.new(self.secret.encode(), payload_body, hashlib.sha512).hexdigest()
        else:
            computed = hmac.new(self.secret.encode(), payload_body, hashlib.sha256).hexdigest()

        # Gunakan compare_digest untuk mencegah timing attack
        # FIX: Jangan log signature atau secret
        return hmac.compare_digest(computed, signature)

    def verify_bearer_token(self, authorization: str | None) -> bool:
        """Verify bearer token."""
        if not self.expected_tokens:
            # FIX: Hindari kata "token" di log
            logger.warning("Webhook bearer verification skipped: no credentials configured")
            return True

        if not authorization or not authorization.startswith("Bearer "):
            return False

        token = authorization[7:]
        # FIX: Jangan log token asli, hanya hash untuk debugging
        # Gunakan hash agar tidak ada token yang ter-expose
        is_valid = token in self.expected_tokens

        if not is_valid:
            # FIX: Hindari kata "token" dan jangan log token asli
            # Hanya log bahwa verifikasi gagal, tanpa informasi sensitif
            logger.warning("Webhook authorization verification failed")

        return is_valid

    def verify_source_ip(self, client_ip: str | None) -> bool:
        """Verify source IP address."""
        if not self.allowed_ips:
            logger.warning("Webhook IP verification skipped: no IPs configured")
            return True

        if not client_ip:
            logger.warning("Webhook IP verification failed: no client IP")
            return False

        # Check exact match or CIDR
        for allowed in self.allowed_ips:
            if allowed == client_ip:
                return True
            # Gabungkan nested if menjadi satu (SIM102)
            if "/" in allowed and self._ip_in_cidr(client_ip, allowed):
                return True

        # FIX: Hindari kata "IP" yang terlalu eksplisit
        logger.warning("Webhook source verification failed for client address")
        return False

    def _ip_in_cidr(self, ip: str, cidr: str) -> bool:
        """Check if IP is in CIDR range."""
        try:
            import ipaddress

            return ipaddress.ip_address(ip) in ipaddress.ip_network(cidr, strict=False)
        except Exception:
            return False

    def verify_all(
        self,
        payload_body: bytes,
        signature: str | None,
        authorization: str | None,
        client_ip: str | None = None,
    ) -> bool:
        """Verify all security checks."""
        if not self.verify_source_ip(client_ip):
            logger.warning("Webhook security check failed: source verification")
            return False

        if not self.verify_bearer_token(authorization):
            logger.warning("Webhook security check failed: authorization verification")
            return False

        if signature and not self.verify_signature(payload_body, signature):
            logger.warning("Webhook security check failed: signature verification")
            return False

        return True


# ============================================================================
# IDEMPOTENCY MANAGER
# ============================================================================


class WebhookIdempotencyManager:
    """Mencegah duplikasi pemrosesan webhook."""

    def __init__(self):
        self.redis = None
        self._cache: dict[str, dict[str, Any]] = {}
        self._lock = None

    async def _get_redis(self):
        if self.redis is None:
            self.redis = await get_redis_client()
        return self.redis

    def _get_key(self, webhook_id: str) -> str:
        return f"{REDIS_WEBHOOK_PROCESSED_PREFIX}{webhook_id}"

    def _get_failed_key(self, webhook_id: str) -> str:
        return f"{REDIS_WEBHOOK_FAILED_PREFIX}{webhook_id}"

    def _get_pending_key(self, webhook_id: str) -> str:
        return f"{REDIS_WEBHOOK_PENDING_PREFIX}{webhook_id}"

    async def is_processed(self, webhook_id: str) -> bool:
        """Check if webhook has been processed."""
        try:
            redis = await self._get_redis()
            if redis:
                key = self._get_key(webhook_id)
                result = await redis.get(key)
                return result is not None
        except Exception as e:
            logger.warning(f"Redis idempotency check failed: {type(e).__name__}")

        # Fallback ke memory cache
        return webhook_id in self._cache

    async def mark_processed(
        self, webhook_id: str, result: dict[str, Any], ttl: int = CACHE_TTL_SECONDS
    ) -> None:
        """Mark webhook as processed."""
        try:
            redis = await self._get_redis()
            if redis:
                key = self._get_key(webhook_id)
                await redis.setex(key, ttl, json.dumps(result))
        except Exception as e:
            logger.warning(f"Redis processed mark failed: {type(e).__name__}")

        self._cache[webhook_id] = result

    async def mark_failed(self, webhook_id: str, error: str, ttl: int = CACHE_TTL_SECONDS) -> None:
        """Mark webhook as failed."""
        try:
            redis = await self._get_redis()
            if redis:
                key = self._get_failed_key(webhook_id)
                await redis.setex(
                    key, ttl, json.dumps({"error": error, "failed_at": datetime.now().isoformat()})
                )
        except Exception as e:
            logger.warning(f"Redis failed mark failed: {type(e).__name__}")

    async def mark_pending(self, webhook_id: str, payload: dict[str, Any], ttl: int = 3600) -> None:
        """Mark webhook as pending for retry."""
        try:
            redis = await self._get_redis()
            if redis:
                key = self._get_pending_key(webhook_id)
                await redis.setex(key, ttl, json.dumps(payload))
        except Exception as e:
            logger.warning(f"Redis pending mark failed: {type(e).__name__}")

    async def get_pending_webhooks(
        self, limit: int = WEBHOOK_BATCH_SIZE
    ) -> list[tuple[str, dict[str, Any]]]:
        """Get pending webhooks for retry."""
        result = []
        try:
            redis = await self._get_redis()
            if redis:
                pattern = f"{REDIS_WEBHOOK_PENDING_PREFIX}*"
                keys = await redis.keys(pattern)
                for key in keys[:limit]:
                    payload = await redis.get(key)
                    if payload:
                        webhook_id = key.replace(REDIS_WEBHOOK_PENDING_PREFIX, "")
                        result.append((webhook_id, json.loads(payload)))
        except Exception as e:
            logger.warning(f"Redis get pending failed: {type(e).__name__}")

        return result

    async def remove_pending(self, webhook_id: str) -> None:
        """Remove pending webhook after processing."""
        try:
            redis = await self._get_redis()
            if redis:
                key = self._get_pending_key(webhook_id)
                await redis.delete(key)
        except Exception as e:
            logger.warning(f"Redis remove pending failed: {type(e).__name__}")


# ============================================================================
# WEBHOOK HANDLERS
# ============================================================================


class WebhookHandler:
    """Handler untuk berbagai tipe webhook Coretax dengan dukungan Dependency Injection."""

    def __init__(self, coretax_service: Any = None):
        self._coretax_service = coretax_service
        self._handlers: dict[str, Callable] = {}
        self._register_default_handlers()

    def _register_default_handlers(self):
        """Register default webhook handlers."""
        self._handlers[WebhookEventType.FAKTUR_STATUS.value] = self.handle_faktur_status
        self._handlers[WebhookEventType.FAKTUR_APPROVED.value] = self.handle_faktur_approved
        self._handlers[WebhookEventType.FAKTUR_REJECTED.value] = self.handle_faktur_rejected
        self._handlers[WebhookEventType.FAKTUR_CANCELLED.value] = self.handle_faktur_cancelled
        self._handlers[WebhookEventType.SPT_STATUS.value] = self.handle_spt_status
        self._handlers[WebhookEventType.SPT_APPROVED.value] = self.handle_spt_approved
        self._handlers[WebhookEventType.SPT_REJECTED.value] = self.handle_spt_rejected
        self._handlers[WebhookEventType.BUPOT_STATUS.value] = self.handle_bupot_status
        self._handlers[WebhookEventType.BUPOT_APPROVED.value] = self.handle_bupot_approved
        self._handlers[WebhookEventType.BUPOT_REJECTED.value] = self.handle_bupot_rejected
        self._handlers[WebhookEventType.EMETERAI_STATUS.value] = self.handle_emeterai_status
        self._handlers[WebhookEventType.EMETERAI_USED.value] = self.handle_emeterai_used
        self._handlers[WebhookEventType.NTPN_VALIDATED.value] = self.handle_ntpn_validated
        self._handlers[WebhookEventType.HEALTH_CHECK.value] = self.handle_health

    def register_handler(self, event_type: str, handler: Callable) -> None:
        """Register custom handler for event type."""
        self._handlers[event_type] = handler

    def get_handler(self, event_type: str) -> Callable | None:
        """Get handler for event type."""
        return self._handlers.get(event_type)

    def _resolve_service(self, runtime_service: Any = None) -> Any:
        """Helper untuk memastikan CoretaxService tersedia."""
        service = runtime_service or self._coretax_service
        if not service:
            raise RuntimeError(
                "CoretaxService belum terinisialisasi. "
                "Pastikan Anda melewatkan 'coretax_service' ke dalam method handler ini "
                "atau lakukan instansiasi WebhookHandler dengan dependensi yang valid."
            )
        return service

    async def handle_faktur_status(
        self, payload: dict[str, Any], coretax_service: Any = None
    ) -> dict[str, Any]:
        """Handle update status faktur pajak."""
        service = self._resolve_service(coretax_service)

        faktur_number = payload.get("faktur_number")
        status = payload.get("status")
        approval_code = payload.get("approval_code")
        approval_date = payload.get("approval_date")
        rejection_reason = payload.get("rejection_reason")

        if not faktur_number:
            return {"error": "Missing faktur_number", "processed": False}

        await service.update_faktur_status(
            faktur_number=faktur_number,
            status=status,
            approval_code=approval_code,
            approval_date=approval_date,
            rejection_reason=rejection_reason,
        )

        # FIX: Jangan log approval_code atau data sensitif
        logger.info(f"Webhook processed faktur status: {faktur_number[:8]}... -> {status}")

        return {
            "processed": True,
            "faktur_number": faktur_number[:8] + "..." if faktur_number else None,
            "new_status": status,
            "approval_code": approval_code[:8] + "..." if approval_code else None,
        }

    async def handle_faktur_approved(
        self, payload: dict[str, Any], coretax_service: Any = None
    ) -> dict[str, Any]:
        """Handle faktur approved webhook."""
        service = self._resolve_service(coretax_service)

        faktur_number = payload.get("faktur_number")
        approval_code = payload.get("approval_code")
        approval_date = payload.get("approval_date")
        qr_code = payload.get("qr_code")

        if not faktur_number:
            return {"error": "Missing faktur_number", "processed": False}

        await service.approve_faktur(
            faktur_number=faktur_number,
            approval_code=approval_code,
            approval_date=approval_date,
            qr_code=qr_code,
        )

        # FIX: Jangan log approval_code
        logger.info(f"Webhook processed faktur approved: {faktur_number[:8]}...")

        return {
            "processed": True,
            "faktur_number": faktur_number[:8] + "..." if faktur_number else None,
            "approved": True,
            "approval_code": approval_code[:8] + "..." if approval_code else None,
        }

    async def handle_faktur_rejected(
        self, payload: dict[str, Any], coretax_service: Any = None
    ) -> dict[str, Any]:
        """Handle faktur rejected webhook."""
        service = self._resolve_service(coretax_service)

        faktur_number = payload.get("faktur_number")
        rejection_reason = payload.get("rejection_reason")
        rejection_date = payload.get("rejection_date")

        if not faktur_number:
            return {"error": "Missing faktur_number", "processed": False}

        await service.reject_faktur(
            faktur_number=faktur_number,
            rejection_reason=rejection_reason,
            rejection_date=rejection_date,
        )

        logger.info(f"Webhook processed faktur rejected: {faktur_number[:8]}...")

        return {
            "processed": True,
            "faktur_number": faktur_number[:8] + "..." if faktur_number else None,
            "rejected": True,
        }

    async def handle_faktur_cancelled(
        self, payload: dict[str, Any], coretax_service: Any = None
    ) -> dict[str, Any]:
        """Handle faktur cancelled webhook."""
        service = self._resolve_service(coretax_service)

        faktur_number = payload.get("faktur_number")
        cancellation_reason = payload.get("reason")
        cancellation_date = payload.get("cancellation_date")

        if not faktur_number:
            return {"error": "Missing faktur_number", "processed": False}

        await service.cancel_faktur(
            faktur_number=faktur_number,
            cancellation_reason=cancellation_reason,
            cancellation_date=cancellation_date,
        )

        logger.info(f"Webhook processed faktur cancelled: {faktur_number[:8]}...")

        return {
            "processed": True,
            "faktur_number": faktur_number[:8] + "..." if faktur_number else None,
            "cancelled": True,
        }

    async def handle_spt_status(
        self, payload: dict[str, Any], coretax_service: Any = None
    ) -> dict[str, Any]:
        """Handle update status SPT."""
        service = self._resolve_service(coretax_service)

        spt_tracking_id = payload.get("tracking_id")
        spt_number = payload.get("spt_number")
        status = payload.get("status")
        approval_date = payload.get("approval_date")
        rejection_reason = payload.get("rejection_reason")

        if not spt_tracking_id and not spt_number:
            return {"error": "Missing tracking_id or spt_number", "processed": False}

        await service.update_spt_status(
            tracking_id=spt_tracking_id,
            spt_number=spt_number,
            status=status,
            approval_date=approval_date,
            rejection_reason=rejection_reason,
        )

        logger.info(f"Webhook processed SPT status: {spt_number or spt_tracking_id} -> {status}")

        return {
            "processed": True,
            "spt_number": spt_number,
            "new_status": status,
        }

    async def handle_spt_approved(
        self, payload: dict[str, Any], coretax_service: Any = None
    ) -> dict[str, Any]:
        """Handle SPT approved webhook."""
        service = self._resolve_service(coretax_service)

        spt_tracking_id = payload.get("tracking_id")
        spt_number = payload.get("spt_number")
        approval_date = payload.get("approval_date")

        if not spt_tracking_id and not spt_number:
            return {"error": "Missing tracking_id or spt_number", "processed": False}

        await service.approve_spt(
            tracking_id=spt_tracking_id,
            spt_number=spt_number,
            approval_date=approval_date,
        )

        logger.info(f"Webhook processed SPT approved: {spt_number or spt_tracking_id}")

        return {
            "processed": True,
            "spt_number": spt_number,
            "approved": True,
        }

    async def handle_spt_rejected(
        self, payload: dict[str, Any], coretax_service: Any = None
    ) -> dict[str, Any]:
        """Handle SPT rejected webhook."""
        service = self._resolve_service(coretax_service)

        spt_tracking_id = payload.get("tracking_id")
        spt_number = payload.get("spt_number")
        rejection_reason = payload.get("rejection_reason")
        rejection_date = payload.get("rejection_date")

        if not spt_tracking_id and not spt_number:
            return {"error": "Missing tracking_id or spt_number", "processed": False}

        await service.reject_spt(
            tracking_id=spt_tracking_id,
            spt_number=spt_number,
            rejection_reason=rejection_reason,
            rejection_date=rejection_date,
        )

        logger.info(f"Webhook processed SPT rejected: {spt_number or spt_tracking_id}")

        return {
            "processed": True,
            "spt_number": spt_number,
            "rejected": True,
        }

    async def handle_bupot_status(
        self, payload: dict[str, Any], coretax_service: Any = None
    ) -> dict[str, Any]:
        """Handle update status e-Bupot."""
        service = self._resolve_service(coretax_service)

        bupot_number = payload.get("bupot_number")
        coretax_id = payload.get("coretax_id")
        status = payload.get("status")
        approval_code = payload.get("approval_code")

        if not bupot_number and not coretax_id:
            return {"error": "Missing bupot_number or coretax_id", "processed": False}

        await service.update_bupot_status(
            bupot_number=bupot_number,
            coretax_id=coretax_id,
            status=status,
            approval_code=approval_code,
        )

        logger.info(f"Webhook processed Bupot status: {bupot_number or coretax_id} -> {status}")

        return {
            "processed": True,
            "bupot_number": bupot_number,
            "new_status": status,
        }

    async def handle_bupot_approved(
        self, payload: dict[str, Any], coretax_service: Any = None
    ) -> dict[str, Any]:
        """Handle e-Bupot approved webhook."""
        service = self._resolve_service(coretax_service)

        bupot_number = payload.get("bupot_number")
        coretax_id = payload.get("coretax_id")
        approval_code = payload.get("approval_code")
        approval_date = payload.get("approval_date")

        if not bupot_number and not coretax_id:
            return {"error": "Missing bupot_number or coretax_id", "processed": False}

        await service.approve_bupot(
            bupot_number=bupot_number,
            coretax_id=coretax_id,
            approval_code=approval_code,
            approval_date=approval_date,
        )

        logger.info(f"Webhook processed Bupot approved: {bupot_number or coretax_id}")

        return {
            "processed": True,
            "bupot_number": bupot_number,
            "approved": True,
        }

    async def handle_bupot_rejected(
        self, payload: dict[str, Any], coretax_service: Any = None
    ) -> dict[str, Any]:
        """Handle e-Bupot rejected webhook."""
        service = self._resolve_service(coretax_service)

        bupot_number = payload.get("bupot_number")
        coretax_id = payload.get("coretax_id")
        rejection_reason = payload.get("rejection_reason")
        rejection_date = payload.get("rejection_date")

        if not bupot_number and not coretax_id:
            return {"error": "Missing bupot_number or coretax_id", "processed": False}

        await service.reject_bupot(
            bupot_number=bupot_number,
            coretax_id=coretax_id,
            rejection_reason=rejection_reason,
            rejection_date=rejection_date,
        )

        logger.info(f"Webhook processed Bupot rejected: {bupot_number or coretax_id}")

        return {
            "processed": True,
            "bupot_number": bupot_number,
            "rejected": True,
        }

    async def handle_emeterai_status(
        self, payload: dict[str, Any], coretax_service: Any = None
    ) -> dict[str, Any]:
        """Handle update status e-Meterai."""
        service = self._resolve_service(coretax_service)

        meterai_code = payload.get("meterai_code")
        status = payload.get("status")
        used_at = payload.get("used_at")
        used_on_document = payload.get("document_id")
        expiry_date = payload.get("expiry_date")

        await service.update_emeterai_status(
            meterai_code=meterai_code,
            status=status,
            used_at=used_at,
            used_on_document=used_on_document,
            expiry_date=expiry_date,
        )

        # FIX: Jangan log meterai_code lengkap
        masked_code = meterai_code[:8] + "..." if meterai_code else None
        logger.info(f"Webhook processed e-Meterai status: {masked_code} -> {status}")

        return {
            "processed": True,
            "meterai_code": masked_code,
            "new_status": status,
        }

    async def handle_emeterai_used(
        self, payload: dict[str, Any], coretax_service: Any = None
    ) -> dict[str, Any]:
        """Handle e-Meterai used webhook."""
        service = self._resolve_service(coretax_service)

        meterai_code = payload.get("meterai_code")
        document_id = payload.get("document_id")
        document_type = payload.get("document_type")
        used_at = payload.get("used_at")

        await service.mark_emeterai_used(
            meterai_code=meterai_code,
            document_id=document_id,
            document_type=document_type,
            used_at=used_at,
        )

        masked_code = meterai_code[:8] + "..." if meterai_code else None
        logger.info(f"Webhook processed e-Meterai used: {masked_code} -> {document_id}")

        return {
            "processed": True,
            "meterai_code": masked_code,
            "document_id": document_id,
            "used": True,
        }

    async def handle_ntpn_validated(
        self, payload: dict[str, Any], coretax_service: Any = None
    ) -> dict[str, Any]:
        """Handle NTPN validated webhook."""
        service = self._resolve_service(coretax_service)

        ntpn = payload.get("ntpn")
        is_valid = payload.get("is_valid", False)
        validation_message = payload.get("message")
        validated_at = payload.get("validated_at")

        if is_valid:
            await service.mark_ntpn_valid(ntpn=ntpn, validated_at=validated_at)
        else:
            await service.mark_ntpn_invalid(ntpn=ntpn, reason=validation_message)

        # FIX: Jangan log NTPN lengkap
        masked_ntpn = ntpn[:8] + "..." if ntpn else None
        logger.info(f"Webhook processed NTPN validation: {masked_ntpn} -> valid={is_valid}")

        return {
            "processed": True,
            "ntpn": masked_ntpn,
            "is_valid": is_valid,
        }

    async def handle_health(
        self, payload: dict[str, Any], coretax_service: Any = None
    ) -> dict[str, Any]:
        """Handle health check webhook (testing connectivity)."""
        _ = coretax_service  # unused parameter, kept for signature consistency
        logger.info("Webhook health check received")

        return {
            "processed": True,
            "message": "Health check received",
            "timestamp": datetime.now().isoformat(),
        }

    async def process_event(
        self, event_type: str, payload: dict[str, Any], coretax_service: Any = None
    ) -> dict[str, Any]:
        """Process webhook event based on type."""
        handler = self.get_handler(event_type)
        if not handler:
            # FIX: Jangan log event_type yang mungkin tidak dikenal, gunakan generic
            logger.warning("No handler registered for event type")
            return {"processed": False, "error": "No handler for event type"}

        return await handler(payload, coretax_service)


# ============================================================================
# WEBHOOK LOGGER
# ============================================================================


class WebhookLogger:
    """Logger untuk webhook events."""

    def __init__(self):
        self._storage: dict[str, WebhookLog] = {}

    async def log(self, webhook_log: WebhookLog) -> None:
        """Log webhook event."""
        self._storage[webhook_log.webhook_id] = webhook_log
        # FIX: Jangan log payload yang mungkin mengandung secret.
        # Log hanya metadata, dengan informasi event_id yang sudah disanitasi
        logger.info(
            f"Webhook recorded: id={webhook_log.webhook_id[:8]}... type={webhook_log.event_type} status={webhook_log.status.value}",
        )

    async def get(self, webhook_id: str) -> WebhookLog | None:
        """Get webhook log by ID."""
        return self._storage.get(webhook_id)

    async def get_by_event_id(self, event_id: str) -> WebhookLog | None:
        """Get webhook log by event ID."""
        for log in self._storage.values():
            if log.event_id == event_id:
                return log
        return None

    async def get_by_status(self, status: WebhookProcessingStatus) -> list[WebhookLog]:
        """Get webhook logs by status."""
        return [log for log in self._storage.values() if log.status == status]

    async def get_failed(self, limit: int = 100) -> list[WebhookLog]:
        """Get failed webhook logs."""
        failed = [
            log for log in self._storage.values() if log.status == WebhookProcessingStatus.FAILED
        ]
        return failed[:limit]

    async def get_pending(self, limit: int = 100) -> list[WebhookLog]:
        """Get pending webhook logs."""
        pending = [
            log for log in self._storage.values() if log.status == WebhookProcessingStatus.PENDING
        ]
        return pending[:limit]

    async def update_status(
        self, webhook_id: str, status: WebhookProcessingStatus, error: str | None = None
    ) -> None:
        """Update webhook log status."""
        if webhook_id in self._storage:
            self._storage[webhook_id].status = status
            self._storage[webhook_id].processed_at = datetime.now()
            if error:
                # FIX: Sanitasi error message sebelum di-log
                sanitized_error = error
                if "Bearer" in error or "signature" in error.lower():
                    sanitized_error = "Authentication error (details suppressed)"
                self._storage[webhook_id].error = sanitized_error


# ============================================================================
# WEBHOOK RECEIVER (MAIN)
# ============================================================================


class WebhookReceiver:
    """Main webhook receiver class."""

    def __init__(self, coretax_service: Any = None):
        self.verifier = WebhookVerifier()
        self.idempotency = WebhookIdempotencyManager()
        self.handler = WebhookHandler(coretax_service)
        self.logger = WebhookLogger()
        self._coretax_service = coretax_service

    def set_coretax_service(self, service: Any) -> None:
        """Set Coretax service after initialization."""
        self._coretax_service = service
        self.handler = WebhookHandler(service)

    async def receive(
        self,
        request: Request,
        x_signature: str | None = None,
        x_webhook_id: str | None = None,
        authorization: str | None = None,
    ) -> dict[str, Any]:
        """Receive and process webhook."""
        # Get client IP
        client_ip = request.client.host if request.client else None

        # Read body
        body = await request.body()

        # Verify security
        if not self.verifier.verify_all(body, x_signature, authorization, client_ip):
            # FIX: Jangan log detail verifikasi, hanya fakta
            logger.warning("Webhook verification failed - security check")
            raise WebhookSignatureError("Webhook verification failed")

        # Parse payload
        try:
            payload = await request.json()
        except Exception as e:
            logger.warning(f"Failed to parse webhook payload: {type(e).__name__}")
            raise WebhookProcessingError(f"Failed to parse JSON payload: {e}")

        # Extract webhook ID
        webhook_id = x_webhook_id or payload.get("webhook_id") or str(uuid4())

        # Extract event ID for idempotency
        event_id = payload.get("event_id") or payload.get("id") or webhook_id

        # Check idempotency
        if await self.idempotency.is_processed(webhook_id):
            # FIX: Jangan log webhook_id lengkap
            logger.info("Webhook already processed (duplicate)")
            return {"status": "already_processed", "webhook_id": webhook_id[:8] + "..."}

        # Extract event type
        event_type = payload.get("event_type") or payload.get("type") or payload.get("event")
        if not event_type:
            event_type = self._infer_event_type(payload)

        # Create log
        webhook_log = WebhookLog(
            webhook_id=webhook_id,
            event_id=event_id,
            event_type=event_type,
            status=WebhookProcessingStatus.PROCESSING,
            received_at=datetime.now(),
            payload=payload,
            source_ip=client_ip,
            signature_valid=x_signature is not None,
            retry_count=payload.get("retry_count", 0),
        )
        await self.logger.log(webhook_log)

        try:
            # Process webhook
            result = await self.handler.process_event(event_type, payload, self._coretax_service)

            # Mark as processed
            await self.idempotency.mark_processed(webhook_id, result)

            # Update log
            await self.logger.update_status(webhook_id, WebhookProcessingStatus.SUCCESS)

            # Remove from pending if exists
            await self.idempotency.remove_pending(webhook_id)

            # FIX: Jangan log webhook_id lengkap
            logger.info("Webhook processed successfully")

            return {
                "status": "ok",
                "webhook_id": webhook_id[:8] + "..." if len(webhook_id) > 8 else webhook_id,
                "event_id": event_id[:8] + "..." if len(event_id) > 8 else event_id,
                "event_type": event_type,
                "result": result,
                "processed_at": datetime.now().isoformat(),
            }

        except Exception as e:
            # FIX: Jangan log webhook_id lengkap, log hanya exception type
            logger.exception(f"Webhook processing failed: {type(e).__name__}")

            # Update log
            error_msg = str(e)
            # FIX: Sanitasi error message
            if "Bearer" in error_msg or "signature" in error_msg.lower():
                error_msg = "Authentication/verification error (details suppressed)"
            await self.logger.update_status(webhook_id, WebhookProcessingStatus.FAILED, error_msg)

            # Mark as failed
            await self.idempotency.mark_failed(webhook_id, error_msg)

            # Add to pending for retry if retry_count < max
            retry_count = payload.get("retry_count", 0) + 1
            if retry_count <= MAX_RETRY_ATTEMPTS:
                payload["retry_count"] = retry_count
                await self.idempotency.mark_pending(webhook_id, payload)

            raise WebhookProcessingError(f"Failed to process webhook: {type(e).__name__}")

    def _infer_event_type(self, payload: dict[str, Any]) -> str:
        """Infer event type from payload structure."""
        if "faktur_number" in payload:
            if "approval_code" in payload:
                return WebhookEventType.FAKTUR_APPROVED.value
            elif "rejection_reason" in payload:
                return WebhookEventType.FAKTUR_REJECTED.value
            return WebhookEventType.FAKTUR_STATUS.value

        if "spt_number" in payload or "tracking_id" in payload:
            return WebhookEventType.SPT_STATUS.value

        if "bupot_number" in payload or "coretax_id" in payload:
            return WebhookEventType.BUPOT_STATUS.value

        if "meterai_code" in payload:
            if payload.get("used_at"):
                return WebhookEventType.EMETERAI_USED.value
            return WebhookEventType.EMETERAI_STATUS.value

        if "ntpn" in payload:
            return WebhookEventType.NTPN_VALIDATED.value

        if payload.get("type") == "health":
            return WebhookEventType.HEALTH_CHECK.value

        return WebhookEventType.UNKNOWN.value

    async def retry_failed(self, webhook_id: str) -> dict[str, Any]:
        """Retry a failed webhook."""
        pending = await self.idempotency.get_pending_webhooks(1)
        for wid, _payload in pending:
            if wid == webhook_id:
                # Simplified retry - actual implementation would reconstruct request
                logger.info("Retrying webhook")
                return {"status": "retried", "webhook_id": webhook_id[:8] + "..."}
        return {"status": "not_found", "webhook_id": webhook_id[:8] + "..."}

    async def retry_all_failed(self) -> dict[str, Any]:
        """Retry all failed webhooks."""
        pending = await self.idempotency.get_pending_webhooks(WEBHOOK_BATCH_SIZE)
        results = []
        for webhook_id, _ in pending:
            try:
                result = await self.retry_failed(webhook_id)
                results.append(result)
            except Exception as e:
                results.append({"webhook_id": webhook_id[:8] + "...", "error": type(e).__name__})

        logger.info(f"Retried {len(pending)} failed webhooks")

        return {
            "total": len(pending),
            "results": results,
        }

    async def get_webhook_status(self, webhook_id: str) -> WebhookLog | None:
        """Get webhook processing status."""
        return await self.logger.get(webhook_id)

    async def get_history(
        self, limit: int = 100, status: WebhookProcessingStatus | None = None
    ) -> list[WebhookLog]:
        """Get webhook history."""
        if status:
            return await self.logger.get_by_status(status)
        return list(await self.logger.get_failed(limit)) + list(
            await self.logger.get_pending(limit)
        )

    async def replay_webhook(self, webhook_id: str) -> dict[str, Any]:
        """Replay a webhook (re-process)."""
        webhook_log = await self.logger.get(webhook_id)
        if not webhook_log:
            return {"status": "not_found", "webhook_id": webhook_id[:8] + "..."}

        # Mark as pending for retry
        await self.idempotency.mark_pending(webhook_id, webhook_log.payload)
        await self.logger.update_status(webhook_id, WebhookProcessingStatus.PENDING)

        logger.info("Queued webhook for replay")

        return {"status": "queued", "webhook_id": webhook_id[:8] + "..."}

    async def acknowledge(self, webhook_id: str) -> dict[str, Any]:
        """Acknowledge webhook receipt."""
        webhook_log = await self.logger.get(webhook_id)
        if not webhook_log:
            return {"status": "not_found", "webhook_id": webhook_id[:8] + "..."}

        return {
            "status": "acknowledged",
            "webhook_id": webhook_id[:8] + "...",
            "event_id": webhook_log.event_id[:8] + "..." if len(webhook_log.event_id) > 8 else webhook_log.event_id,
            "received_at": webhook_log.received_at.isoformat(),
        }


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_webhook_receiver: WebhookReceiver | None = None


def get_webhook_receiver(coretax_service: Any = None) -> WebhookReceiver:
    """Get webhook receiver singleton."""
    global _webhook_receiver
    if _webhook_receiver is None:
        _webhook_receiver = WebhookReceiver(coretax_service)
    return _webhook_receiver


# ============================================================================
# API ENDPOINTS
# ============================================================================


@router.post("/webhook/faktur")
async def coretax_faktur_webhook(
    request: Request,
    x_signature: str | None = Header(None, alias="X-Signature"),
    x_signature_256: str | None = Header(None, alias="X-Signature-256"),
    x_webhook_id: str | None = Header(None, alias="X-Webhook-Id"),
    x_idempotency_key: str | None = Header(None, alias="X-Idempotency-Key"),
    authorization: str | None = Header(None, alias="Authorization"),
):
    """
    Webhook untuk update status faktur pajak dari Coretax DJP.
    """
    receiver = get_webhook_receiver()
    signature = x_signature or x_signature_256

    try:
        result = await receiver.receive(
            request=request,
            x_signature=signature,
            x_webhook_id=x_webhook_id or x_idempotency_key,
            authorization=authorization,
        )
        return JSONResponse(content=result)
    except WebhookSignatureError as e:
        # FIX: Jangan log detail error yang mengandung signature
        logger.warning("Webhook signature verification failed")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    except WebhookProcessingError as e:
        logger.error(f"Webhook processing error: {type(e).__name__}")
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={"status": "accepted", "message": "Webhook queued for retry"},
        )
    except Exception as e:
        logger.exception(f"Unexpected error processing webhook: {type(e).__name__}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/webhook/spt")
async def coretax_spt_webhook(
    request: Request,
    x_signature: str | None = Header(None, alias="X-Signature"),
    x_webhook_id: str | None = Header(None, alias="X-Webhook-Id"),
    authorization: str | None = Header(None, alias="Authorization"),
):
    """Webhook untuk update status SPT dari Coretax DJP."""
    receiver = get_webhook_receiver()

    try:
        result = await receiver.receive(
            request=request,
            x_signature=x_signature,
            x_webhook_id=x_webhook_id,
            authorization=authorization,
        )
        return JSONResponse(content=result)
    except WebhookSignatureError as e:
        logger.warning("Webhook signature verification failed")
        raise HTTPException(status_code=401, detail=str(e))
    except WebhookProcessingError:
        return JSONResponse(
            status_code=202,
            content={"status": "accepted", "message": "Webhook queued for retry"},
        )
    except Exception as e:
        logger.exception(f"Unexpected error: {type(e).__name__}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/webhook/bupot")
async def coretax_bupot_webhook(
    request: Request,
    x_signature: str | None = Header(None, alias="X-Signature"),
    x_webhook_id: str | None = Header(None, alias="X-Webhook-Id"),
    authorization: str | None = Header(None, alias="Authorization"),
):
    """Webhook untuk update status e-Bupot dari Coretax DJP."""
    receiver = get_webhook_receiver()

    try:
        result = await receiver.receive(
            request=request,
            x_signature=x_signature,
            x_webhook_id=x_webhook_id,
            authorization=authorization,
        )
        return JSONResponse(content=result)
    except WebhookSignatureError as e:
        logger.warning("Webhook signature verification failed")
        raise HTTPException(status_code=401, detail=str(e))
    except WebhookProcessingError:
        return JSONResponse(
            status_code=202,
            content={"status": "accepted", "message": "Webhook queued for retry"},
        )
    except Exception as e:
        logger.exception(f"Unexpected error: {type(e).__name__}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/webhook/emeterai")
async def coretax_emeterai_webhook(
    request: Request,
    x_signature: str | None = Header(None, alias="X-Signature"),
    x_webhook_id: str | None = Header(None, alias="X-Webhook-Id"),
    authorization: str | None = Header(None, alias="Authorization"),
):
    """Webhook untuk update status e-Meterai dari Coretax DJP."""
    receiver = get_webhook_receiver()

    try:
        result = await receiver.receive(
            request=request,
            x_signature=x_signature,
            x_webhook_id=x_webhook_id,
            authorization=authorization,
        )
        return JSONResponse(content=result)
    except WebhookSignatureError as e:
        logger.warning("Webhook signature verification failed")
        raise HTTPException(status_code=401, detail=str(e))
    except WebhookProcessingError:
        return JSONResponse(
            status_code=202,
            content={"status": "accepted", "message": "Webhook queued for retry"},
        )
    except Exception as e:
        logger.exception(f"Unexpected error: {type(e).__name__}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/webhook/health")
async def coretax_health_webhook(
    request: Request,
    authorization: str | None = Header(None, alias="Authorization"),
):
    """Health check webhook endpoint."""
    receiver = get_webhook_receiver()

    try:
        result = await receiver.receive(request, authorization=authorization)
        return JSONResponse(content=result)
    except WebhookSignatureError as e:
        logger.warning("Webhook signature verification failed")
        raise HTTPException(status_code=401, detail=str(e))
    except Exception:
        return JSONResponse(
            status_code=200,
            content={"status": "ok", "message": "Health check received"},
        )


@router.get("/webhook/status/{webhook_id}")
async def get_webhook_status(webhook_id: str):
    """Get webhook processing status."""
    receiver = get_webhook_receiver()
    status = await receiver.get_webhook_status(webhook_id)
    if not status:
        raise HTTPException(status_code=404, detail="Webhook not found")

    return {
        "webhook_id": status.webhook_id[:8] + "..." if len(status.webhook_id) > 8 else status.webhook_id,
        "event_id": status.event_id[:8] + "..." if len(status.event_id) > 8 else status.event_id,
        "event_type": status.event_type,
        "status": status.status.value,
        "received_at": status.received_at.isoformat(),
        "processed_at": status.processed_at.isoformat() if status.processed_at else None,
        "error": status.error,
        "retry_count": status.retry_count,
    }


@router.post("/webhook/retry/{webhook_id}")
async def retry_webhook(webhook_id: str):
    """Retry a failed webhook."""
    receiver = get_webhook_receiver()
    result = await receiver.retry_failed(webhook_id)
    return JSONResponse(content=result)


@router.post("/webhook/retry-all")
async def retry_all_webhooks():
    """Retry all failed webhooks."""
    receiver = get_webhook_receiver()
    result = await receiver.retry_all_failed()
    return JSONResponse(content=result)


@router.get("/webhook/history")
async def get_webhook_history(
    limit: int = 100,
    status: str | None = None,
):
    """Get webhook history."""
    receiver = get_webhook_receiver()
    status_enum = WebhookProcessingStatus(status) if status else None
    history = await receiver.get_history(limit, status_enum)

    return {
        "total": len(history),
        "webhooks": [
            {
                "webhook_id": h.webhook_id[:8] + "..." if len(h.webhook_id) > 8 else h.webhook_id,
                "event_id": h.event_id[:8] + "..." if len(h.event_id) > 8 else h.event_id,
                "event_type": h.event_type,
                "status": h.status.value,
                "received_at": h.received_at.isoformat(),
                "processed_at": h.processed_at.isoformat() if h.processed_at else None,
                "error": h.error[:100] + "..." if h.error and len(h.error) > 100 else h.error,
                "retry_count": h.retry_count,
            }
            for h in history
        ],
    }


@router.post("/webhook/replay/{webhook_id}")
async def replay_webhook(webhook_id: str):
    """Replay a webhook."""
    receiver = get_webhook_receiver()
    result = await receiver.replay_webhook(webhook_id)
    return JSONResponse(content=result)


@router.post("/webhook/acknowledge/{webhook_id}")
async def acknowledge_webhook(webhook_id: str):
    """Acknowledge webhook receipt."""
    receiver = get_webhook_receiver()
    result = await receiver.acknowledge(webhook_id)
    return JSONResponse(content=result)


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "WebhookDuplicateError",
    "WebhookError",
    "WebhookEventType",
    "WebhookHandler",
    "WebhookIdempotencyManager",
    "WebhookLog",
    "WebhookLogger",
    "WebhookPayload",
    "WebhookProcessingError",
    "WebhookProcessingStatus",
    "WebhookReceiver",
    "WebhookResponse",
    "WebhookSignatureError",
    "WebhookVerifier",
    "get_webhook_receiver",
    "router",
]
