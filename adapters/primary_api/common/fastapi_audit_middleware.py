#!/usr/bin/env python3
"""
Module: fastapi_audit_middleware.py
Layer: Adapters (Primary API - Common)
Responsibility: Middleware untuk mencatat semua request dan response ke dalam
               immutable audit log. Setiap akses API (termasuk yang gagal)
               dicatat dengan hash chain untuk menjamin non-repudiation dan
               integritas. Middleware ini juga menangkap request body (jika ada)
               dan response body, serta menghitung waktu eksekusi.
Dependencies:
- starlette
- fastapi
- hashlib, json, time
- infrastructure.event_store.append_only_store (untuk menyimpan audit event)
- kernel.immutable_laws.audit_trail_completeness_enforcer
Audit: SEMUA akses API WAJIB tercatat. Tidak ada pengecualian.
       Jika pencatatan gagal, request tetap diproses tetapi alarm dipicu.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.types import ASGIApp

# Internal imports (diizinkan untuk lapisan adapters)
from infrastructure.event_store.append_only_store import AppendOnlyStore
from infrastructure.telemetry.structured_json_logging import get_logger
from kernel.immutable_laws.audit_trail_completeness_enforcer import AuditTrailCompletenessEnforcer

logger = logging.getLogger(__name__)
audit_logger = get_logger("audit")

# ============================================================================
# CONSTANTS & ENUMS
# ============================================================================


class AuditEventType:
    """Jenis-jenis event audit."""

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


# Maksimum ukuran body yang akan dicatat (bytes)
MAX_BODY_LOG_SIZE = 10_000  # 10KB

# Field yang perlu di-mask/diredact (password, token, dll)
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
    """Gagal mencatat audit log (tidak boleh mengganggu request utama)."""

    pass


# ============================================================================
# VALUE OBJECTS
# ============================================================================


class AuditRecord:
    """
    Representasi immutable dari satu record audit.
    Setiap record memiliki hash yang terkait dengan record sebelumnya.
    """

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
        # Hitung hash dari record ini
        self.hash = self._compute_hash()

    def _compute_hash(self) -> str:
        """Menghitung SHA-256 hash dari semua field (kecuali hash itu sendiri)."""
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
        # Sort keys untuk konsistensi
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
    """
    Middleware untuk audit logging immutable.

    Fitur:
    - Mencatat setiap request dan response (termasuk body hash, bukan body penuh)
    - Menghitung hash chain per request (link ke request sebelumnya)
    - Menyimpan audit record ke AppendOnlyStore (immutable)
    - Melakukan redaction terhadap field sensitif
    - Mengukur durasi request
    - Jika terjadi error saat logging, tetap melanjutkan request tetapi memicu alert
    """

    def __init__(
        self,
        app: ASGIApp,
        store: AppendOnlyStore | None = None,
        enforcer: AuditTrailCompletenessEnforcer | None = None,
        log_request_body: bool = True,
        log_response_body: bool = False,
        redact_sensitive: bool = True,
    ):
        super().__init__(app)
        self.store = store
        self.enforcer = enforcer or AuditTrailCompletenessEnforcer()
        self.log_request_body = log_request_body
        self.log_response_body = log_response_body
        self.redact_sensitive = redact_sensitive

        # Cache untuk last hash (per instance, bisa di-share via Redis jika multi-instance)
        self._last_hash_cache: str | None = None
        self._last_hash_lock = None  # bisa pakai asyncio.Lock

    async def _get_last_hash(self) -> str:
        """
        Mendapatkan hash dari audit record terakhir yang tersimpan.
        Untuk hash chain: setiap record baru harus menyertakan hash record sebelumnya.
        """
        if self.store is None:
            # Fallback: gunakan dummy hash untuk development
            return "0" * 64

        # Coba dari cache
        if self._last_hash_cache:
            return self._last_hash_cache

        # Ambil record terakhir dari store
        last_record = await self.store.get_last_record("audit")
        if last_record and "hash" in last_record:
            self._last_hash_cache = last_record["hash"]
            return self._last_hash_cache

        # Jika tidak ada, gunakan genesis hash
        genesis = hashlib.sha256(b"ERP_AUDIT_GENESIS_2025").hexdigest()
        self._last_hash_cache = genesis
        return genesis

    async def _update_last_hash(self, new_hash: str) -> None:
        """Update cache hash terakhir."""
        self._last_hash_cache = new_hash

    def _redact_body(self, body: bytes | None, content_type: str) -> tuple[str | None, str | None]:
        """
        Redact field sensitif dari body, dan mengembalikan hash serta (optional) body yang sudah direadact.
        Returns: (hash, redacted_body_string)
        """
        if not body:
            return None, None

        # Hanya proses jika content-type JSON
        if "application/json" not in content_type:
            # Untuk non-JSON, cukup hash saja tanpa redaction
            body_hash = hashlib.sha256(body).hexdigest()
            return body_hash, None

        try:
            data = json.loads(body)
            # Redaction in-place
            if self.redact_sensitive:
                data = self._redact_dict(data)
            body_str = json.dumps(data, ensure_ascii=False)
            # Truncate jika terlalu panjang
            if len(body_str) > MAX_BODY_LOG_SIZE:
                body_str = body_str[:MAX_BODY_LOG_SIZE] + "... [truncated]"
            body_hash = hashlib.sha256(body_str.encode("utf-8")).hexdigest()
            return body_hash, body_str
        except Exception as e:
            # Jika parsing gagal, tetap hash raw body
            logger.warning(f"Could not parse request body for redaction: {e}")
            body_hash = hashlib.sha256(body).hexdigest()
            return body_hash, None

    def _redact_dict(self, data: Any) -> Any:
        """Recursively redact sensitive fields."""
        if isinstance(data, dict):
            return {
                k: "***REDACTED***" if k.lower() in SENSITIVE_FIELDS else self._redact_dict(v)
                for k, v in data.items()
            }
        elif isinstance(data, list):
            return [self._redact_dict(item) for item in data]
        else:
            return data

    def _extract_client_ip(self, request: Request) -> str:
        """Ekstrak client IP dari header atau langsung."""
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip
        client = request.client
        return client.host if client else "unknown"

    def _get_user_id(self, request: Request) -> UUID | None:
        """Ekstrak user_id dari request state jika sudah di-set oleh auth middleware."""
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

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """
        Proses request, catat audit sebelum dan sesudah.
        """
        start_time = time.perf_counter()
        request_id = request.headers.get("X-Request-ID", str(uuid4()))
        # Set request_id ke state untuk diakses oleh endpoint
        request.state.request_id = request_id

        # Baca request body (jika diperlukan)
        request_body_bytes = None
        if self.log_request_body:
            try:
                request_body_bytes = await request.body()

                # Karena body sekali baca, kita perlu reassign agar endpoint bisa baca
                # Gunakan method receive yang lebih aman? Untuk middleware, kita restore body.
                async def receive():
                    return {"type": "http.request", "body": request_body_bytes, "more_body": False}

                request._receive = receive
            except Exception as e:
                logger.warning(f"Could not read request body for audit: {e}")

        content_type = request.headers.get("content-type", "")
        request_body_hash, redacted_request_body = self._redact_body(
            request_body_bytes, content_type
        )

        # Ekstrak informasi dasar
        method = request.method
        path = request.url.path
        query_params = str(request.query_params) if request.query_params else None
        client_ip = self._extract_client_ip(request)
        user_agent = request.headers.get("user-agent", "")
        user_id = self._get_user_id(request)
        legal_entity_id = self._get_legal_entity_id(request)

        response = None
        error = None
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception as e:
            error = e
            status_code = 500
            raise  # tetap raise setelah log

        finally:
            duration_ms = (time.perf_counter() - start_time) * 1000

            # Capture response body jika diperlukan (hati-hati karena streaming)
            response_body_hash = None
            redacted_response_body = None
            if self.log_response_body and response and not isinstance(response, StreamingResponse):
                try:
                    # Untuk response biasa, kita bisa baca body
                    # (implementasi: capture body dengan monkeypatch, hati2)
                    # Untuk kemudahan, kita hanya hash jika response body tidak terlalu besar
                    # Alternatif: kita tidak log response body penuh, hanya hash
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
                    logger.warning(f"Could not capture response body for audit: {e}")

            # Dapatkan last hash dari chain
            try:
                previous_hash = await self._get_last_hash()
            except Exception as e:
                logger.error(f"Failed to get last audit hash: {e}. Using fallback.")
                previous_hash = hashlib.sha256(b"fallback").hexdigest()

            # Buat audit record
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

            # Simpan ke store (async fire-and-forget dengan retry)
            asyncio.create_task(self._save_audit_record(audit_record))

            # Update cache hash (setelah simpan sukses, tapi kita optimis update)
            await self._update_last_hash(audit_record.hash)

            # Log ke JSON logger juga
            audit_logger.info(
                "API access",
                extra={"audit_record": audit_record.to_dict(), "request_id": request_id},
            )

        return response

    async def _save_audit_record(self, record: AuditRecord) -> None:
        """
        Simpan audit record ke AppendOnlyStore dengan retry mechanism.
        Jika gagal, catat error dan trigger alert.
        """
        max_retries = 3
        for attempt in range(max_retries):
            try:
                if self.store is None:
                    # Fallback: simpan ke file atau logger saja
                    audit_logger.warning(
                        "No AppendOnlyStore configured, audit record not persisted",
                        extra={"record": record.to_dict()},
                    )
                    return
                await self.store.append("audit", record.to_dict())
                return
            except Exception as e:
                logger.error(
                    f"Failed to save audit record (attempt {attempt + 1}/{max_retries}): {e}"
                )
                if attempt == max_retries - 1:
                    # Trigger alert (via notification port)
                    from infrastructure.telemetry.alert_manager_router import trigger_alert

                    await trigger_alert(
                        title="Audit Log Storage Failure",
                        message=f"Failed to persist audit record after {max_retries} attempts. Record: {record.id}",
                        severity="critical",
                        source="AuditMiddleware",
                    )
                await asyncio.sleep(0.1 * (2**attempt))


# ============================================================================
# DEPENDENCY UTILITY
# ============================================================================


def get_audit_store() -> AppendOnlyStore | None:
    """
    Dependency untuk mendapatkan audit store dari container.
    Menggunakan lazy import untuk menghindari AST drift (adapters -> bootstrap).
    """
    try:
        import importlib

        mod = importlib.import_module("bootstrap.dependency_container.ioc_container")
        get_container = mod.get_container
        container = get_container()
        return container.resolve(AppendOnlyStore)
    except Exception as e:
        logger.warning(f"Cannot resolve AppendOnlyStore: {e}")
        return None


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ["AuditEventType", "AuditMiddleware", "AuditRecord", "AuditSeverity", "get_audit_store"]
