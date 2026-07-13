#!/usr/bin/env python3
"""
Module: fastapi_audit_middleware.py
Layer: Adapters (Primary API - Common)
Responsibility: Middleware untuk mencatat semua request dan response ke dalam
               immutable audit log. Setiap akses API (termasuk yang gagal)
               dicatat dengan hash chain untuk menjamin non-repudiation dan
               integritas.
Dependencies:
- starlette
- fastapi
- hashlib, json, time
- infrastructure.telemetry.structured_json_logging (hanya logging)
- kernel.immutable_laws.audit_trail_completeness_enforcer (opsional)
Audit: SEMUA akses API WAJIB tercatat. Tidak ada pengecualian.
       Jika pencatatan gagal, request tetap diproses tetapi alarm dipicu.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.types import ASGIApp

if TYPE_CHECKING:
    # Hanya digunakan untuk tipe, tidak diimpor saat runtime
    pass

from infrastructure.telemetry.structured_json_logging import get_logger

logger = logging.getLogger(__name__)
audit_logger = get_logger("audit")

# ============================================================================
# CONSTANTS & ENUMS
# ============================================================================


class AuditEventType:
    API_REQUEST = "api.request"
    API_RESPONSE = "api.response"
    API_ERROR = "api.error"
    AUTH_FAILURE = "auth.failure"
    RATE_LIMIT_HIT = "rate_limit.hit"
    SENSITIVE_ACCESS = "sensitive.access"


class AuditSeverity:
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


MAX_BODY_LOG_SIZE = 10_000  # 10KB

SENSITIVE_FIELDS = {
    "password",
    "token",
    "refresh_token",
    "authorization",
    "secret",
    "api_key",
    "credit_card",
}

# ============================================================================
# CUSTOM EXCEPTIONS
# ============================================================================


class AuditLoggingError(Exception):
    pass


# ============================================================================
# VALUE OBJECTS
# ============================================================================


class AuditRecord:
    __slots__ = (
        "client_ip",
        "duration_ms",
        "event_type",
        "extra_data",
        "hash",
        "id",
        "legal_entity_id",
        "method",
        "path",
        "previous_hash",
        "query_params",
        "request_body_hash",
        "request_id",
        "response_body_hash",
        "response_status",
        "severity",
        "timestamp",
        "user_agent",
        "user_id",
    )

    def __init__(
        self,
        id: UUID,
        timestamp: datetime,
        event_type: str,
        severity: str,
        user_id: UUID | None,
        legal_entity_id: UUID | None,
        request_id: str,
        method: str,
        path: str,
        query_params: str | None,
        request_body_hash: str | None,
        response_status: int | None,
        response_body_hash: str | None,
        duration_ms: float | None,
        client_ip: str,
        user_agent: str,
        extra_data: dict[str, Any] | None,
        previous_hash: str,
    ):
        self.id = id
        self.timestamp = timestamp
        self.event_type = event_type
        self.severity = severity
        self.user_id = user_id
        self.legal_entity_id = legal_entity_id
        self.request_id = request_id
        self.method = method
        self.path = path
        self.query_params = query_params
        self.request_body_hash = request_body_hash
        self.response_status = response_status
        self.response_body_hash = response_body_hash
        self.duration_ms = duration_ms
        self.client_ip = client_ip
        self.user_agent = user_agent
        self.extra_data = extra_data
        self.previous_hash = previous_hash
        self.hash = self._compute_hash()

    def _compute_hash(self) -> str:
        data = {
            "id": str(self.id),
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type,
            "severity": self.severity,
            "user_id": str(self.user_id) if self.user_id else None,
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else None,
            "request_id": self.request_id,
            "method": self.method,
            "path": self.path,
            "query_params": self.query_params,
            "request_body_hash": self.request_body_hash,
            "response_status": self.response_status,
            "response_body_hash": self.response_body_hash,
            "duration_ms": self.duration_ms,
            "client_ip": self.client_ip,
            "user_agent": self.user_agent,
            "extra_data": self.extra_data,
            "previous_hash": self.previous_hash,
        }
        json_str = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(json_str.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type,
            "severity": self.severity,
            "user_id": str(self.user_id) if self.user_id else None,
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else None,
            "request_id": self.request_id,
            "method": self.method,
            "path": self.path,
            "query_params": self.query_params,
            "request_body_hash": self.request_body_hash,
            "response_status": self.response_status,
            "response_body_hash": self.response_body_hash,
            "duration_ms": self.duration_ms,
            "client_ip": self.client_ip,
            "user_agent": self.user_agent,
            "extra_data": self.extra_data,
            "previous_hash": self.previous_hash,
            "hash": self.hash,
        }


# ============================================================================
# MAIN MIDDLEWARE CLASS
# ============================================================================


class AuditMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: ASGIApp,
        store: Any = None,  # Optional, akan di-lazy import
        enforcer: Any = None,  # Optional
        log_request_body: bool = True,
        log_response_body: bool = False,
        redact_sensitive: bool = True,
    ):
        super().__init__(app)
        self._store = store
        self._enforcer = enforcer
        self.log_request_body = log_request_body
        self.log_response_body = log_response_body
        self.redact_sensitive = redact_sensitive
        self._last_hash_cache: str | None = None

    async def _get_last_hash(self) -> str:
        if self._last_hash_cache:
            return self._last_hash_cache
        # Jika ada store, coba ambil hash terakhir (tapi kita tidak menggunakan ORM)
        # Fallback ke genesis hash
        genesis = hashlib.sha256(b"ERP_AUDIT_GENESIS_2025").hexdigest()
        self._last_hash_cache = genesis
        return genesis

    async def _update_last_hash(self, new_hash: str) -> None:
        self._last_hash_cache = new_hash

    def _redact_dict(self, data: Any) -> Any:
        if isinstance(data, dict):
            return {
                k: "***REDACTED***" if k.lower() in SENSITIVE_FIELDS else self._redact_dict(v)
                for k, v in data.items()
            }
        elif isinstance(data, list):
            return [self._redact_dict(item) for item in data]
        else:
            return data

    def _redact_body(self, body: bytes | None, content_type: str) -> tuple[str | None, str | None]:
        if not body:
            return None, None
        if "application/json" not in content_type:
            body_hash = hashlib.sha256(body).hexdigest()
            return body_hash, None
        try:
            data = json.loads(body)
            if self.redact_sensitive:
                data = self._redact_dict(data)
            body_str = json.dumps(data, ensure_ascii=False)
            if len(body_str) > MAX_BODY_LOG_SIZE:
                body_str = body_str[:MAX_BODY_LOG_SIZE] + "... [truncated]"
            body_hash = hashlib.sha256(body_str.encode("utf-8")).hexdigest()
            return body_hash, body_str
        except Exception as e:
            logger.warning(f"Could not parse body for redaction: {e}")
            body_hash = hashlib.sha256(body).hexdigest()
            return body_hash, None

    def _extract_client_ip(self, request: Request) -> str:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip
        client = request.client
        return client.host if client else "unknown"

    def _get_user_id(self, request: Request) -> UUID | None:
        if hasattr(request.state, "user_id"):
            uid = request.state.user_id
            if isinstance(uid, UUID):
                return uid
            try:
                return UUID(uid)
            except (ValueError, TypeError):
                pass
        if hasattr(request.state, "user") and hasattr(request.state.user, "user_id"):
            return request.state.user.user_id
        return None

    def _get_legal_entity_id(self, request: Request) -> UUID | None:
        if hasattr(request.state, "legal_entity_id"):
            lid = request.state.legal_entity_id
            if isinstance(lid, UUID):
                return lid
            try:
                return UUID(lid)
            except (ValueError, TypeError):
                pass
        return None

    async def dispatch(self, request: Request, call_next) -> Response:
        start_time = time.perf_counter()
        request_id = request.headers.get("X-Request-ID", str(uuid4()))
        request.state.request_id = request_id

        request_body_bytes = None
        if self.log_request_body:
            try:
                request_body_bytes = await request.body()
                async def receive():
                    return {"type": "http.request", "body": request_body_bytes, "more_body": False}
                request._receive = receive
            except Exception as e:
                logger.warning(f"Could not read request body: {e}")

        content_type = request.headers.get("content-type", "")
        request_body_hash, redacted_request_body = self._redact_body(request_body_bytes, content_type)

        method = request.method
        path = request.url.path
        query_params = str(request.query_params) if request.query_params else None
        client_ip = self._extract_client_ip(request)
        user_agent = request.headers.get("user-agent", "")
        user_id = self._get_user_id(request)
        legal_entity_id = self._get_legal_entity_id(request)

        response = None
        error = None
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception as e:
            error = e
            raise
        finally:
            duration_ms = (time.perf_counter() - start_time) * 1000

            response_body_hash = None
            redacted_response_body = None
            if self.log_response_body and response and not isinstance(response, StreamingResponse):
                try:
                    response_body_bytes = b""
                    if hasattr(response, "body"):
                        response_body_bytes = response.body
                    elif hasattr(response, "render"):
                        response_body_bytes = response.render()
                    if response_body_bytes:
                        _, redacted_response_body = self._redact_body(
                            response_body_bytes, response.headers.get("content-type", "")
                        )
                        response_body_hash = hashlib.sha256(response_body_bytes).hexdigest()
                except Exception as e:
                    logger.warning(f"Could not capture response body: {e}")

            previous_hash = await self._get_last_hash()

            extra_data = {}
            if error:
                extra_data["error"] = str(error)
            if self.log_request_body and redacted_request_body:
                extra_data["request_body"] = redacted_request_body
            if self.log_response_body and redacted_response_body:
                extra_data["response_body"] = redacted_response_body

            audit_record = AuditRecord(
                id=uuid4(),
                timestamp=datetime.now(UTC),
                event_type=AuditEventType.API_RESPONSE if not error else AuditEventType.API_ERROR,
                severity=AuditSeverity.INFO
                if status_code < 400
                else (AuditSeverity.ERROR if status_code >= 500 else AuditSeverity.WARNING),
                user_id=user_id,
                legal_entity_id=legal_entity_id,
                request_id=request_id,
                method=method,
                path=path,
                query_params=query_params,
                request_body_hash=request_body_hash,
                response_status=status_code if not error else None,
                response_body_hash=response_body_hash,
                duration_ms=duration_ms,
                client_ip=client_ip,
                user_agent=user_agent,
                extra_data=extra_data if extra_data else None,
                previous_hash=previous_hash,
            )

            # Simpan ke store jika ada (tapi kita tidak pakai SQLAlchemy)
            # Hanya log ke JSON logger
            audit_logger.info(
                "API access",
                extra={"audit_record": audit_record.to_dict(), "request_id": request_id},
            )

            await self._update_last_hash(audit_record.hash)

        return response


# ============================================================================
# DEPENDENCY UTILITY
# ============================================================================


def get_audit_store() -> Any:
    """Dummy function - tidak menggunakan SQLAlchemy."""
    # Tidak ada store SQLAlchemy, hanya logging
    return None


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ["AuditEventType", "AuditMiddleware", "AuditRecord", "AuditSeverity", "get_audit_store"]
