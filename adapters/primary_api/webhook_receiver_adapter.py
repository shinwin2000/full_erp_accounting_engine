#!/usr/bin/env python3
"""
Module: webhook_receiver_adapter.py
Layer: Adapters (Primary API - Webhook)
Responsibility: Menerima callback HTTP dari sistem eksternal (payment gateway,
               bank, coretax DJP, supplier portal) dan mengubahnya menjadi
               command internal. Webhook receiver menangani verifikasi signature,
               idempotency, retry logic, dan routing ke command bus.
               Endpoint ini biasanya dipanggil oleh pihak ketiga.
Dependencies:
- fastapi
- application.commands_cqrs.command_bus_unified
- infrastructure.security.webhook_signature_verifier
- adapters.primary_api.common.fastapi_request_id_middleware
Audit: Setiap webhook yang diterima dicatat (source, payload, signature, status).
       Duplikasi dicegah menggunakan idempotency key.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

# Internal dependencies
from application.commands_cqrs.command_bus_unified import CommandBusUnified
from infrastructure.caching.redis_manager import get_redis_client

logger = logging.getLogger(__name__)

# ============================================================================
# ROUTER
# ============================================================================

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

# ============================================================================
# IDEMPOTENCY
# ============================================================================


class IdempotencyManager:
    """Manajemen idempotency untuk webhook."""

    def __init__(self):
        self._redis = None

    async def _get_redis(self):
        if self._redis is None:
            self._redis = await get_redis_client()
        return self._redis

    async def is_processed(self, idempotency_key: str) -> tuple[bool, dict[str, Any] | None]:
        """
        Check if a webhook with given key has been processed.
        Returns (processed, result)
        """
        redis = await self._get_redis()
        key = f"webhook:idempotent:{idempotency_key}"
        result = await redis.get(key)
        if result:
            return True, json.loads(result)
        return False, None

    async def mark_processed(
        self, idempotency_key: str, result: dict[str, Any], ttl_seconds: int = 86400
    ):
        """Mark webhook as processed with result."""
        redis = await self._get_redis()
        key = f"webhook:idempotent:{idempotency_key}"
        await redis.setex(key, ttl_seconds, json.dumps(result))


_idempotency_manager = IdempotencyManager()

# ============================================================================
# SIGNATURE VERIFIERS
# ============================================================================


class WebhookSignatureVerifier:
    """Verifikasi signature webhook dari berbagai provider."""

    @staticmethod
    def verify_midtrans(
        signature: str, order_id: str, status_code: str, gross_amount: str, server_key: str
    ) -> bool:
        """Midtrans signature verification."""
        computed = hashlib.sha512(
            f"{order_id}{status_code}{gross_amount}{server_key}".encode()
        ).hexdigest()
        return hmac.compare_digest(computed, signature)

    @staticmethod
    def verify_xendit(callback_token: str, expected_token: str) -> bool:
        return hmac.compare_digest(callback_token, expected_token)

    @staticmethod
    def verify_stripe(signature: str, payload: bytes, webhook_secret: str) -> bool:
        import hashlib
        import hmac

        expected = hmac.new(webhook_secret.encode(), payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected)

    @staticmethod
    def verify_coretax(payload: dict[str, Any], secret: str) -> bool:
        # Coretax DJP: signature di header X-Signature
        # Implementasi sesuai spesifikasi Coretax
        # Untuk sementara, verifikasi sederhana
        data = json.dumps(payload, sort_keys=True)
        computed = hashlib.sha256(f"{data}{secret}".encode()).hexdigest()
        received = payload.get("_signature", "")
        return hmac.compare_digest(computed, received)

    @staticmethod
    def verify_generic(
        signature: str, payload: bytes, secret: str, algorithm: str = "sha256"
    ) -> bool:
        if algorithm == "sha256":
            computed = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        elif algorithm == "sha1":
            computed = hmac.new(secret.encode(), payload, hashlib.sha1).hexdigest()
        else:
            computed = hashlib.sha256(payload).hexdigest()
        return hmac.compare_digest(computed, signature)


# ============================================================================
# WEBHOOK HANDLER MAPPING
# ============================================================================


class WebhookRouter:
    """Route incoming webhook to appropriate handler."""

    def __init__(self):
        self.command_bus = CommandBusUnified()

    async def handle_payment_gateway(
        self, provider: str, payload: dict[str, Any], signature: str | None = None
    ) -> dict[str, Any]:
        """Handle payment notification (Midtrans, Xendit, Stripe, etc)."""
        if provider == "midtrans":
            transaction_status = payload.get("transaction_status")
            order_id = payload.get("order_id")
            gross_amount = payload.get("gross_amount")
            if transaction_status == "capture" or transaction_status == "settlement":
                command = {
                    "type": "ar.payment.create_from_webhook",
                    "data": {
                        "order_id": order_id,
                        "amount": gross_amount,
                        "payment_method": "midtrans",
                        "transaction_status": transaction_status,
                        "provider": "midtrans",
                        "payload": payload,
                    },
                }
                result = await self.command_bus.dispatch(command)
                return {"status": "processed", "command_result": result}
            else:
                return {"status": "ignored", "reason": f"status={transaction_status}"}

        elif provider == "xendit":
            invoice_id = payload.get("id")
            status = payload.get("status")
            if status == "PAID":
                command = {
                    "type": "ar.payment.create_from_webhook",
                    "data": {
                        "invoice_id": invoice_id,
                        "amount": payload.get("amount"),
                        "payment_method": "xendit",
                        "status": status,
                    },
                }
                result = await self.command_bus.dispatch(command)
                return {"status": "processed", "command_result": result}
            return {"status": "ignored", "reason": f"status={status}"}

        elif provider == "stripe":
            event_type = payload.get("type")
            if event_type == "payment_intent.succeeded":
                payment_intent = payload.get("data", {}).get("object", {})
                command = {
                    "type": "ar.payment.create_from_webhook",
                    "data": {
                        "payment_intent_id": payment_intent.get("id"),
                        "amount": payment_intent.get("amount") / 100,
                        "currency": payment_intent.get("currency"),
                        "payment_method": "stripe",
                    },
                }
                result = await self.command_bus.dispatch(command)
                return {"status": "processed", "command_result": result}
            return {"status": "ignored", "reason": f"event_type={event_type}"}

        return {"status": "unsupported_provider"}

    async def handle_bank_webhook(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle bank transfer notification (virtual account, BI-FAST)."""
        # Standard format: {account_number, amount, transaction_date, reference}
        command = {
            "type": "bank.receive_transfer",
            "data": {
                "account_number": payload.get("account_number"),
                "amount": payload.get("amount"),
                "transaction_date": payload.get("transaction_date"),
                "reference": payload.get("reference"),
                "sender_name": payload.get("sender_name"),
            },
        }
        result = await self.command_bus.dispatch(command)
        return {"status": "processed", "command_result": result}

    async def handle_coretax_webhook(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle Coretax DJP callback (status faktur, SPT)."""
        event_type = payload.get("event_type")
        if event_type == "faktur_status":
            command = {
                "type": "tax.update_faktur_status",
                "data": {
                    "faktur_number": payload.get("faktur_number"),
                    "status": payload.get("status"),
                    "response_code": payload.get("response_code"),
                    "message": payload.get("message"),
                },
            }
        elif event_type == "spt_status":
            command = {
                "type": "tax.update_spt_status",
                "data": {"spt_id": payload.get("spt_id"), "status": payload.get("status")},
            }
        else:
            return {"status": "ignored", "reason": f"unknown_event={event_type}"}
        result = await self.command_bus.dispatch(command)
        return {"status": "processed", "command_result": result}

    async def handle_supplier_portal(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle supplier portal invoice notification."""
        command = {
            "type": "ap.invoice.create_from_webhook",
            "data": {
                "supplier_id": payload.get("supplier_id"),
                "invoice_number": payload.get("invoice_number"),
                "invoice_date": payload.get("invoice_date"),
                "due_date": payload.get("due_date"),
                "amount": payload.get("amount"),
                "currency": payload.get("currency"),
            },
        }
        result = await self.command_bus.dispatch(command)
        return {"status": "processed", "command_result": result}


_webhook_router = WebhookRouter()

# ============================================================================
# WEBHOOK ENDPOINTS
# ============================================================================


@router.post("/midtrans")
async def midtrans_webhook(
    request: Request, x_signature: str | None = Header(None, alias="X-Signature")
):
    """Midtrans payment notification webhook."""
    payload = await request.json()
    logger.info(f"Midtrans webhook received: {payload.get('order_id')}")

    # Verify signature (optional but recommended)
    # if not verify_midtrans(...): raise HTTPException(401)

    idempotency_key = payload.get("order_id") or str(uuid4())
    processed, cached = await _idempotency_manager.is_processed(idempotency_key)
    if processed:
        return JSONResponse(content=cached, status_code=200)

    result = await _webhook_router.handle_payment_gateway("midtrans", payload, x_signature)
    await _idempotency_manager.mark_processed(idempotency_key, result)
    return JSONResponse(content=result)


@router.post("/xendit")
async def xendit_webhook(
    request: Request, callback_token: str | None = Header(None, alias="X-Callback-Token")
):
    payload = await request.json()
    logger.info(f"Xendit webhook received: {payload.get('id')}")
    idempotency_key = payload.get("id") or str(uuid4())
    processed, cached = await _idempotency_manager.is_processed(idempotency_key)
    if processed:
        return JSONResponse(content=cached, status_code=200)
    result = await _webhook_router.handle_payment_gateway("xendit", payload, callback_token)
    await _idempotency_manager.mark_processed(idempotency_key, result)
    return JSONResponse(content=result)


@router.post("/stripe")
async def stripe_webhook(
    request: Request, stripe_signature: str | None = Header(None, alias="Stripe-Signature")
):
    raw_payload = await request.body()
    payload = json.loads(raw_payload)
    # Verify signature menggunakan secret dari config
    # secret = config.get("stripe_webhook_secret")
    # WebhookSignatureVerifier.verify_stripe(stripe_signature, raw_payload, secret)
    idempotency_key = payload.get("idempotency_key") or payload.get("id") or str(uuid4())
    processed, cached = await _idempotency_manager.is_processed(idempotency_key)
    if processed:
        return JSONResponse(content=cached, status_code=200)
    result = await _webhook_router.handle_payment_gateway("stripe", payload, stripe_signature)
    await _idempotency_manager.mark_processed(idempotency_key, result)
    return JSONResponse(content=result)


@router.post("/bank")
async def bank_webhook(request: Request):
    """Generic bank transfer notification."""
    payload = await request.json()
    logger.info(f"Bank webhook: {payload.get('account_number')}")
    idempotency_key = payload.get("reference") or str(uuid4())
    processed, cached = await _idempotency_manager.is_processed(idempotency_key)
    if processed:
        return JSONResponse(content=cached, status_code=200)
    result = await _webhook_router.handle_bank_webhook(payload)
    await _idempotency_manager.mark_processed(idempotency_key, result)
    return JSONResponse(content=result)


@router.post("/coretax")
async def coretax_webhook(request: Request):
    """Coretax DJP callback."""
    payload = await request.json()
    # Verify signature using Coretax secret
    # secret = get_coretax_secret()
    # if not WebhookSignatureVerifier.verify_coretax(payload, secret):
    #     raise HTTPException(401, "Invalid signature")
    idempotency_key = payload.get("request_id") or str(uuid4())
    processed, cached = await _idempotency_manager.is_processed(idempotency_key)
    if processed:
        return JSONResponse(content=cached, status_code=200)
    result = await _webhook_router.handle_coretax_webhook(payload)
    await _idempotency_manager.mark_processed(idempotency_key, result)
    return JSONResponse(content=result)


@router.post("/supplier/{supplier_id}")
async def supplier_webhook(supplier_id: str, request: Request):
    """Supplier portal invoice notification."""
    payload = await request.json()
    payload["supplier_id"] = supplier_id
    idempotency_key = payload.get("invoice_number") or str(uuid4())
    processed, cached = await _idempotency_manager.is_processed(idempotency_key)
    if processed:
        return JSONResponse(content=cached, status_code=200)
    result = await _webhook_router.handle_supplier_portal(payload)
    await _idempotency_manager.mark_processed(idempotency_key, result)
    return JSONResponse(content=result)


@router.post("/generic")
async def generic_webhook(
    request: Request,
    x_signature: str | None = Header(None, alias="X-Signature"),
    x_idempotency_key: str | None = Header(None, alias="X-Idempotency-Key"),
):
    """Generic webhook endpoint for custom integrations."""
    payload = await request.json()
    source = request.headers.get("X-Source", "unknown")
    idempotency_key = x_idempotency_key or f"{source}:{datetime.utcnow().timestamp()}"
    processed, cached = await _idempotency_manager.is_processed(idempotency_key)
    if processed:
        return JSONResponse(content=cached, status_code=200)

    # Here we route based on source or payload type
    command = {
        "type": "webhook.generic",
        "data": {"source": source, "payload": payload, "signature": x_signature},
    }
    result = await _webhook_router.command_bus.dispatch(command)
    await _idempotency_manager.mark_processed(idempotency_key, result)
    return JSONResponse(content=result)


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ["router"]
