#!/usr/bin/env python3
"""
Module: timestamp_notary_impl.py
Layer: Adapters (Secondary)
Responsibility: Implementasi lengkap dari TimestampNotaryPort
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

# Import port dan tipe yang diperlukan
from ports.primary.timestamp_notary_port import (
    TimestampNotaryPort,
    TimestampRequest,
    TimestampToken,
)

logger = logging.getLogger(__name__)


class TimestampNotaryImpl(TimestampNotaryPort):
    """
    Implementasi konkret TimestampNotaryPort dengan penyimpanan in-memory.
    Inisialisasi dilakukan secara async melalui metode initialize().
    """

    def __init__(self):
        self._tokens: dict[str, TimestampToken] = {}          # key: serial_number
        self._requests: dict[UUID, TimestampRequest] = {}
        self._certificates: dict[UUID, dict[str, Any]] = {}
        self._audit_log: list[dict[str, Any]] = []
        self._active_cert_id: UUID | None = None
        self._lock = asyncio.Lock()
        self._initialized = False
        # Jangan panggil async di constructor!

    async def initialize(self) -> None:
        """Inisialisasi sertifikat default secara async."""
        if self._initialized:
            return
        async with self._lock:
            if self._initialized:
                return
            if not self._certificates:
                cert_id = uuid.uuid4()
                self._certificates[cert_id] = {
                    "id": cert_id,
                    "name": "Default Timestamp Certificate",
                    "details": {"type": "self-signed"},
                    "created_at": datetime.now(UTC),
                    "is_active": True,
                    "revoked": False,
                    "revoked_at": None,
                    "revocation_reason": None,
                }
                self._active_cert_id = cert_id
                await self._log_audit("certificate_created", f"Default certificate {cert_id} created", "system")
            self._initialized = True

    async def _ensure_initialized(self) -> None:
        """Pastikan inisialisasi sudah dilakukan."""
        if not self._initialized:
            await self.initialize()

    async def _log_audit(self, action: str, message: str, user_id: str = "system") -> None:
        """Catat audit log."""
        entry = {
            "id": str(uuid.uuid4()),
            "action": action,
            "message": message,
            "user_id": user_id,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self._audit_log.append(entry)
        logger.debug(f"Audit: {action} - {message}")

    async def _compute_time_hash(self, data_hash: str, timestamp: datetime, serial: str) -> str:
        """Hitung hash gabungan untuk token timestamp."""
        combined = f"{data_hash}:{timestamp.isoformat()}:{serial}"
        return hashlib.sha256(combined.encode()).hexdigest()

    async def _generate_token(self, request: TimestampRequest) -> TimestampToken:
        """Generate timestamp token dari request."""
        token_id = uuid.uuid4()
        serial = f"TS-{token_id.hex[:8].upper()}"
        token = TimestampToken(
            id=token_id,
            request_id=request.id,
            data_hash=request.data_hash,
            timestamp=datetime.now(UTC),
            serial_number=serial,
            token_data=b"timestamp_token_placeholder",
            time_hash=await self._compute_time_hash(
                request.data_hash,
                datetime.now(UTC),
                serial
            ),
            created_at=datetime.now(UTC),
            revoked=False,
            revoked_at=None,
            revocation_reason=None,
        )
        self._tokens[serial] = token
        self._requests[request.id] = request
        await self._log_audit("token_generated", f"Token {serial} generated for request {request.id}", "system")
        return token

    # ==================== METODE PORT ====================

    async def timestamp(self, data_hash: str, metadata: dict[str, Any] | None = None) -> TimestampToken:
        """Timestamp a data hash."""
        await self._ensure_initialized()
        request_id = uuid.uuid4()
        request = TimestampRequest(
            id=request_id,
            data_hash=data_hash,
            metadata=metadata or {},
            requested_at=datetime.now(UTC),
            status="pending",
        )
        async with self._lock:
            self._requests[request_id] = request
            await self._log_audit("timestamp_request", f"Request {request_id} for hash {data_hash[:8]}...", "system")
            token = await self._generate_token(request)
            request.status = "completed"
            self._requests[request_id] = request
            return token

    async def timestamp_batch(self, data_hashes: list[str], metadata: dict[str, Any] | None = None) -> list[TimestampToken]:
        """Timestamp multiple data hashes."""
        tasks = [self.timestamp(h, metadata) for h in data_hashes]
        return await asyncio.gather(*tasks)

    async def verify_timestamp(self, data_hash: str, timestamp_token: str) -> bool:
        """Verify a timestamp token against data."""
        try:
            token = await self.get_token_by_serial(timestamp_token)
            if not token:
                return False
            if token.revoked:
                return False
            if token.data_hash != data_hash:
                return False
            # Verifikasi time_hash
            computed = await self._compute_time_hash(
                token.data_hash,
                token.timestamp,
                token.serial_number
            )
            return computed == token.time_hash
        except Exception as e:
            logger.error(f"Verification failed: {e}")
            return False

    async def get_timestamp_info(self, timestamp_token: str) -> dict[str, Any]:
        """Get information about a timestamp token."""
        token = await self.get_token_by_serial(timestamp_token)
        if not token:
            return {"error": "Token not found"}
        return {
            "token_id": str(token.id),
            "request_id": str(token.request_id),
            "data_hash": token.data_hash,
            "timestamp": token.timestamp.isoformat(),
            "serial_number": token.serial_number,
            "time_hash": token.time_hash,
            "created_at": token.created_at.isoformat(),
            "revoked": token.revoked,
            "revoked_at": token.revoked_at.isoformat() if token.revoked_at else None,
            "revocation_reason": token.revocation_reason,
        }

    async def revoke_timestamp(self, token_id: UUID, reason: str, user_id: UUID) -> bool:
        """Revoke a timestamp token by ID."""
        async with self._lock:
            for token in self._tokens.values():
                if token.id == token_id:
                    token.revoked = True
                    token.revoked_at = datetime.now(UTC)
                    token.revocation_reason = reason
                    await self._log_audit(
                        "token_revoked",
                        f"Token {token.serial_number} revoked by {user_id}: {reason}",
                        str(user_id)
                    )
                    return True
            return False

    async def revoke_by_hash(self, data_hash: str, reason: str, user_id: UUID) -> int:
        """Revoke all tokens for a data hash."""
        count = 0
        async with self._lock:
            for token in self._tokens.values():
                if token.data_hash == data_hash and not token.revoked:
                    token.revoked = True
                    token.revoked_at = datetime.now(UTC)
                    token.revocation_reason = reason
                    count += 1
            if count > 0:
                await self._log_audit(
                    "tokens_revoked_by_hash",
                    f"{count} tokens revoked for hash {data_hash[:8]}... by {user_id}: {reason}",
                    str(user_id)
                )
            return count

    async def create_certificate(self, name: str, details: dict[str, Any]) -> UUID:
        """Create a new timestamp certificate."""
        cert_id = uuid.uuid4()
        async with self._lock:
            self._certificates[cert_id] = {
                "id": cert_id,
                "name": name,
                "details": details,
                "created_at": datetime.now(UTC),
                "is_active": False,
                "revoked": False,
                "revoked_at": None,
                "revocation_reason": None,
            }
            await self._log_audit("certificate_created", f"Certificate {name} ({cert_id}) created", "system")
            return cert_id

    async def set_active_certificate(self, cert_id: UUID) -> bool:
        """Set a certificate as active."""
        async with self._lock:
            if cert_id not in self._certificates:
                return False
            cert = self._certificates[cert_id]
            if cert["revoked"]:
                return False
            for c in self._certificates.values():
                c["is_active"] = False
            cert["is_active"] = True
            self._active_cert_id = cert_id
            await self._log_audit("certificate_activated", f"Certificate {cert_id} set as active", "system")
            return True

    async def revoke_certificate(self, cert_id: UUID, reason: str) -> bool:
        """Revoke a certificate."""
        async with self._lock:
            if cert_id not in self._certificates:
                return False
            cert = self._certificates[cert_id]
            cert["revoked"] = True
            cert["revoked_at"] = datetime.now(UTC)
            cert["revocation_reason"] = reason
            if self._active_cert_id == cert_id:
                self._active_cert_id = None
            await self._log_audit("certificate_revoked", f"Certificate {cert_id} revoked: {reason}", "system")
            return True

    async def get_active_certificate(self) -> dict | None:
        """Get the active certificate."""
        if self._active_cert_id and self._active_cert_id in self._certificates:
            return self._certificates[self._active_cert_id]
        return None

    async def get_token_by_hash(self, data_hash: str) -> list[dict[str, Any]]:
        """Get all tokens for a data hash."""
        results = []
        for token in self._tokens.values():
            if token.data_hash == data_hash:
                results.append({
                    "token_id": str(token.id),
                    "serial_number": token.serial_number,
                    "timestamp": token.timestamp.isoformat(),
                    "revoked": token.revoked,
                })
        return results

    async def get_token_by_serial(self, serial_number: str) -> TimestampToken | None:
        """Get a token by serial number."""
        return self._tokens.get(serial_number)

    async def get_request_by_id(self, request_id: UUID) -> TimestampRequest | None:
        """Get a request by ID."""
        return self._requests.get(request_id)

    async def get_token_by_id(self, token_id: UUID) -> TimestampToken | None:
        """Get a token by ID."""
        for token in self._tokens.values():
            if token.id == token_id:
                return token
        return None

    async def attach_timestamp_to_audit(self, audit_event_id: UUID, data_hash: str) -> str:
        """Attach a timestamp to an audit event."""
        token = await self.timestamp(data_hash, {"audit_event_id": str(audit_event_id)})
        return token.serial_number

    async def generate_hash_for_audit(self, audit_data: dict[str, Any]) -> str:
        """Generate a hash for audit data."""
        data_str = json.dumps(audit_data, sort_keys=True, default=str)
        return hashlib.sha256(data_str.encode()).hexdigest()

    async def get_statistics(self) -> dict[str, Any]:
        """Get statistics about timestamp service."""
        total_tokens = len(self._tokens)
        revoked = sum(1 for t in self._tokens.values() if t.revoked)
        return {
            "total_tokens": total_tokens,
            "revoked_tokens": revoked,
            "certificates": len(self._certificates),
            "active_certificate": self._active_cert_id is not None,
            "audit_log_entries": len(self._audit_log),
        }

    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """Get audit log entries."""
        return self._audit_log[offset:offset+limit]

    async def health_check(self) -> dict[str, Any]:
        """Check the health of the timestamp service."""
        try:
            await self._ensure_initialized()
            test_hash = hashlib.sha256(b"health_check").hexdigest()
            token = await self.timestamp(test_hash, {"health": "check"})
            if token:
                return {"status": "healthy", "timestamp_service": "ok"}
            return {"status": "degraded", "error": "Could not create timestamp"}
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}


# ============================================================================
# ALIAS UNTUK KOMPATIBILITAS DENGAN ADAPTER REGISTRY
# ============================================================================

RFC3161TimestampAdapter = TimestampNotaryImpl

__all__ = [
    "RFC3161TimestampAdapter",
    "TimestampNotaryImpl",
]