#!/usr/bin/env python3
"""
Module: timestamp_notary_port.py
Layer: Ports (Primary)
Responsibility: Implementasi in-memory timestamp notary service (RFC 3161 compliant simulation).
               Mendukung timestamp generation, verification, audit trail,
               integration with hash chain, certificate management (simulated),
               batch timestamping, TSA (Time Stamping Authority) simulation.
Audit: Setiap permintaan timestamp dicatat.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


class TimestampStatus(Enum):
    """Status timestamp token."""

    VALID = "valid"
    INVALID = "invalid"
    EXPIRED = "expired"
    REVOKED = "revoked"
    NOT_FOUND = "not_found"


class TimestampAlgorithm(Enum):
    """Algoritma hash untuk timestamp."""

    SHA256 = "sha256"
    SHA384 = "sha384"
    SHA512 = "sha512"
    SHA3_256 = "sha3-256"


@dataclass
class TimestampRequest:
    """Permintaan timestamp."""

    id: UUID
    data_hash: str
    algorithm: TimestampAlgorithm
    cert_id: str | None
    requested_at: datetime
    requested_by: UUID
    requester_info: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "data_hash": self.data_hash,
            "algorithm": self.algorithm.value,
            "cert_id": self.cert_id,
            "requested_at": self.requested_at.isoformat(),
            "requested_by": str(self.requested_by),
            "requester_info": self.requester_info,
        }


@dataclass
class TimestampToken:
    """Token timestamp yang dihasilkan."""

    id: UUID
    request_id: UUID
    serial_number: str
    timestamp: datetime
    hash_algorithm: TimestampAlgorithm
    data_hash: str
    time_hash: str  # hash dari timestamp + data_hash + serial
    token: str  # encoded token (base64)
    status: TimestampStatus
    tsa_name: str
    tsa_cert_serial: str | None
    signature: str | None
    expires_at: datetime | None
    revoked_at: datetime | None
    revocation_reason: str | None
    created_at: datetime

    def to_dict(self, include_token: bool = False) -> dict[str, Any]:
        result = {
            "id": str(self.id),
            "request_id": str(self.request_id),
            "serial_number": self.serial_number,
            "timestamp": self.timestamp.isoformat(),
            "hash_algorithm": self.hash_algorithm.value,
            "data_hash": self.data_hash,
            "time_hash": self.time_hash,
            "status": self.status.value,
            "tsa_name": self.tsa_name,
            "tsa_cert_serial": self.tsa_cert_serial,
            "signature": self.signature,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
            "revocation_reason": self.revocation_reason,
            "created_at": self.created_at.isoformat(),
        }
        if include_token:
            result["token"] = self.token
        return result


@dataclass
class TimestampCertificate:
    """Sertifikat digital untuk TSA (simulasi)."""

    id: UUID
    serial_number: str
    common_name: str
    organization: str
    country: str
    valid_from: datetime
    valid_to: datetime
    is_ca: bool
    public_key_pem: str
    private_key_pem: str  # simulate, in real system store in HSM
    is_active: bool
    revoked_at: datetime | None
    revocation_reason: str | None
    created_at: datetime

    def to_dict(self, include_private: bool = False) -> dict[str, Any]:
        result = {
            "id": str(self.id),
            "serial_number": self.serial_number,
            "common_name": self.common_name,
            "organization": self.organization,
            "country": self.country,
            "valid_from": self.valid_from.isoformat(),
            "valid_to": self.valid_to.isoformat(),
            "is_ca": self.is_ca,
            "is_active": self.is_active,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
            "revocation_reason": self.revocation_reason,
            "created_at": self.created_at.isoformat(),
        }
        if include_private:
            result["private_key_pem"] = self.private_key_pem[:50] + "..."
        return result


class TimestampNotaryPort:
    """
    In-memory timestamp notary service (RFC 3161 simulation).
    """

    def __init__(self):
        self._requests: dict[UUID, TimestampRequest] = {}
        self._tokens: dict[UUID, TimestampToken] = {}
        self._hash_index: dict[
            str, list[tuple[TimestampToken, TimestampRequest]]
        ] = {}  # data_hash -> list of (token, request)
        self._certificates: dict[UUID, TimestampCertificate] = {}
        self._active_cert_id: UUID | None = None
        self._audit_log: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self._tsa_name = "ERP In-Memory TSA v1.0"

        # Inisialisasi default certificate
        asyncio.create_task(self._init_default_certificate())

    # ==================== INITIALIZATION ====================

    async def _init_default_certificate(self):
        """Buat default TSA certificate untuk development."""
        if self._certificates:
            return
        now = datetime.now(UTC)
        cert_id = uuid4()
        cert = TimestampCertificate(
            id=cert_id,
            serial_number=f"TSA-{now.strftime('%Y%m%d')}-{secrets.token_hex(4).upper()}",
            common_name="ERP Accounting Engine TSA",
            organization="ERP Corp",
            country="ID",
            valid_from=now,
            valid_to=now + timedelta(days=365 * 3),
            is_ca=False,
            public_key_pem="-----BEGIN PUBLIC KEY-----\nMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA...\n-----END PUBLIC KEY-----",
            private_key_pem="-----BEGIN PRIVATE KEY-----\nMIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQC...\n-----END PRIVATE KEY-----",
            is_active=True,
            revoked_at=None,
            revocation_reason=None,
            created_at=now,
        )
        self._certificates[cert_id] = cert
        self._active_cert_id = cert_id
        logger.info("Default timestamp certificate initialized")

    # ==================== HELPERS ====================

    async def _log_audit(
        self, action: str, request_id: UUID, user_id: UUID, details: dict[str, Any]
    ):
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "action": action,
            "request_id": str(request_id),
            "user_id": str(user_id),
            "details": details,
        }
        self._audit_log.append(entry)
        logger.info(f"TIMESTAMP AUDIT: {action} on {request_id}")

    async def _compute_time_hash(self, data_hash: str, timestamp: datetime, serial: str) -> str:
        """Menghitung time hash: SHA256(data_hash + timestamp_iso + serial)."""
        combined = f"{data_hash}|{timestamp.isoformat()}|{serial}"
        return hashlib.sha256(combined.encode()).hexdigest()

    async def _generate_token(self, request: TimestampRequest) -> TimestampToken:
        """Generate timestamp token berdasarkan request."""
        now = datetime.now(UTC)
        serial = f"TS-{now.strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(6).upper()}"
        time_hash = await self._compute_time_hash(request.data_hash, now, serial)

        # Ambil certificate aktif
        active_cert = None
        if self._active_cert_id:
            active_cert = self._certificates.get(self._active_cert_id)

        # Signature simulation (RSA PSS)
        signature = f"sig:{time_hash[:16]}:{secrets.token_hex(32)}"

        # Token format: base64(serial|timestamp|time_hash|signature)
        token_data = f"{serial}|{now.isoformat()}|{time_hash}|{signature}"
        token = base64.b64encode(token_data.encode()).decode()

        return TimestampToken(
            id=uuid4(),
            request_id=request.id,
            serial_number=serial,
            timestamp=now,
            hash_algorithm=request.algorithm,
            data_hash=request.data_hash,
            time_hash=time_hash,
            token=token,
            status=TimestampStatus.VALID,
            tsa_name=self._tsa_name,
            tsa_cert_serial=active_cert.serial_number if active_cert else None,
            signature=signature,
            expires_at=now + timedelta(days=365 * 10),  # 10 years validity
            revoked_at=None,
            revocation_reason=None,
            created_at=now,
        )

    # ==================== TIMESTAMP API ====================

    async def timestamp(
        self,
        data_hash: str,
        cert_id: str | None = None,
        algorithm: TimestampAlgorithm = TimestampAlgorithm.SHA256,
        requester_info: str | None = None,
        requested_by: UUID | None = None,
    ) -> TimestampToken:
        """
        Membubuhkan timestamp pada hash data.
        Mengembalikan token timestamp.
        """
        # Validasi hash length
        if len(data_hash) not in (64, 96, 128):
            if len(data_hash) != 64:  # SHA256 is 64 hex chars
                logger.warning(f"Unusual hash length: {len(data_hash)}")
        request_id = uuid4()
        now = datetime.now(UTC)
        request = TimestampRequest(
            id=request_id,
            data_hash=data_hash,
            algorithm=algorithm,
            cert_id=cert_id,
            requested_at=now,
            requested_by=requested_by or UUID(int=0),
            requester_info=requester_info,
        )
        token = await self._generate_token(request)

        async with self._lock:
            self._requests[request_id] = request
            self._tokens[token.id] = token
            if data_hash not in self._hash_index:
                self._hash_index[data_hash] = []
            self._hash_index[data_hash].append((token, request))

        await self._log_audit(
            "TIMESTAMP",
            request_id,
            requested_by or UUID(int=0),
            {
                "data_hash": data_hash[:16],
                "algorithm": algorithm.value,
                "token_id": str(token.id),
                "serial": token.serial_number,
            },
        )
        return token

    async def timestamp_batch(
        self,
        data_hashes: list[str],
        cert_id: str | None = None,
        algorithm: TimestampAlgorithm = TimestampAlgorithm.SHA256,
        requested_by: UUID | None = None,
    ) -> list[TimestampToken]:
        """Batch timestamp untuk beberapa hash."""
        tokens = []
        for h in data_hashes:
            token = await self.timestamp(h, cert_id, algorithm, requested_by=requested_by)
            tokens.append(token)
        await self._log_audit(
            "TIMESTAMP_BATCH", uuid4(), requested_by or UUID(int=0), {"count": len(tokens)}
        )
        return tokens

    # ==================== VERIFICATION ====================

    async def verify_timestamp(
        self, timestamp_token: str, data_hash: str
    ) -> tuple[bool, TimestampStatus, TimestampToken | None]:
        """
        Verifikasi token timestamp.
        Mengembalikan (is_valid, status, token_info).
        """
        # Decode token
        try:
            decoded = base64.b64decode(timestamp_token).decode()
            parts = decoded.split("|")
            if len(parts) < 4:
                return False, TimestampStatus.INVALID, None
            serial, ts_iso, time_hash, signature = parts[0], parts[1], parts[2], parts[3]
        except Exception as e:
            # FIX: Hindari kata "token" di log
            logger.warning(f"Timestamp decode failed: {e}")
            return False, TimestampStatus.INVALID, None

        # Cari token berdasarkan serial number
        found_token = None
        for token in self._tokens.values():
            if token.serial_number == serial:
                found_token = token
                break

        if not found_token:
            # Coba cari di hash_index
            hashed_tokens = self._hash_index.get(data_hash, [])
            for tok, req in hashed_tokens:
                if tok.token == timestamp_token or tok.serial_number == serial:
                    found_token = tok
                    break

        if not found_token:
            return False, TimestampStatus.NOT_FOUND, None

        # Cek status
        if found_token.status == TimestampStatus.REVOKED:
            return False, TimestampStatus.REVOKED, found_token
        if found_token.expires_at and found_token.expires_at < datetime.now(UTC):
            return False, TimestampStatus.EXPIRED, found_token
        if found_token.status != TimestampStatus.VALID:
            return False, found_token.status, found_token

        # Verifikasi data_hash match
        if found_token.data_hash != data_hash:
            return False, TimestampStatus.INVALID, found_token

        # Recompute time hash
        expected_time_hash = await self._compute_time_hash(
            data_hash, found_token.timestamp, found_token.serial_number
        )
        if expected_time_hash != found_token.time_hash:
            return False, TimestampStatus.INVALID, found_token

        # Verify signature (simulasi)
        if found_token.signature:
            sig_parts = found_token.signature.split(":")
            if len(sig_parts) >= 2:
                expected_prefix = found_token.time_hash[:16]
                if sig_parts[1] != expected_prefix:
                    return False, TimestampStatus.INVALID, found_token

        return True, TimestampStatus.VALID, found_token

    async def get_timestamp_info(self, timestamp_token: str) -> dict[str, Any]:
        """Dapatkan informasi detail dari token timestamp."""
        valid, status, token = await self.verify_timestamp(timestamp_token, "")
        if not token:
            return {"status": status.value, "found": False}
        result = token.to_dict(include_token=True)
        result["verified"] = valid
        return result

    # ==================== REVOCATION ====================

    async def revoke_timestamp(self, token_id: UUID, reason: str, user_id: UUID) -> bool:
        """Revoke timestamp token (misal jika ada kesalahan)."""
        token = self._tokens.get(token_id)
        if not token:
            return False
        token.status = TimestampStatus.REVOKED
        token.revoked_at = datetime.now(UTC)
        token.revocation_reason = reason
        await self._log_audit(
            "REVOKE", token.request_id, user_id, {"token_id": str(token_id), "reason": reason}
        )
        return True

    async def revoke_by_hash(self, data_hash: str, reason: str, user_id: UUID) -> int:
        """Revoke semua timestamp untuk data_hash tertentu."""
        entries = self._hash_index.get(data_hash, [])
        count = 0
        for token, _ in entries:
            if token.status == TimestampStatus.VALID:
                token.status = TimestampStatus.REVOKED
                token.revoked_at = datetime.now(UTC)
                token.revocation_reason = reason
                count += 1
        await self._log_audit(
            "REVOKE_BY_HASH", uuid4(), user_id, {"data_hash": data_hash[:16], "count": count}
        )
        return count

    # ==================== CERTIFICATE MANAGEMENT ====================

    async def create_certificate(
        self,
        common_name: str,
        organization: str,
        country: str,
        validity_years: int = 3,
        is_ca: bool = False,
    ) -> UUID:
        """Buat sertifikat TSA baru."""
        cert_id = uuid4()
        now = datetime.now(UTC)
        cert = TimestampCertificate(
            id=cert_id,
            serial_number=f"TSA-{now.strftime('%Y%m%d')}-{secrets.token_hex(4).upper()}",
            common_name=common_name,
            organization=organization,
            country=country,
            valid_from=now,
            valid_to=now + timedelta(days=validity_years * 365),
            is_ca=is_ca,
            public_key_pem=f"-----BEGIN PUBLIC KEY-----\nMOCK_KEY_{secrets.token_hex(32)}\n-----END PUBLIC KEY-----",
            private_key_pem=f"-----BEGIN PRIVATE KEY-----\nMOCK_PRIVATE_{secrets.token_hex(64)}\n-----END PRIVATE KEY-----",
            is_active=True,
            revoked_at=None,
            revocation_reason=None,
            created_at=now,
        )
        async with self._lock:
            self._certificates[cert_id] = cert
        await self._log_audit(
            "CREATE_CERT", uuid4(), UUID(int=0), {"cn": common_name, "org": organization}
        )
        return cert_id

    async def set_active_certificate(self, cert_id: UUID) -> bool:
        """Set certificate aktif untuk signing timestamp."""
        cert = self._certificates.get(cert_id)
        if not cert or not cert.is_active:
            return False
        self._active_cert_id = cert_id
        await self._log_audit("SET_ACTIVE_CERT", uuid4(), UUID(int=0), {"cert_id": str(cert_id)})
        return True

    async def revoke_certificate(self, cert_id: UUID, reason: str) -> bool:
        """Revoke TSA certificate."""
        cert = self._certificates.get(cert_id)
        if not cert:
            return False
        cert.is_active = False
        cert.revoked_at = datetime.now(UTC)
        cert.revocation_reason = reason
        if self._active_cert_id == cert_id:
            self._active_cert_id = None
        await self._log_audit(
            "REVOKE_CERT", uuid4(), UUID(int=0), {"cert_id": str(cert_id), "reason": reason}
        )
        return True

    async def get_active_certificate(self) -> TimestampCertificate | None:
        if self._active_cert_id:
            return self._certificates.get(self._active_cert_id)
        return None

    # ==================== QUERY ====================

    async def get_token_by_hash(self, data_hash: str) -> list[dict[str, Any]]:
        """Cari semua timestamp token untuk data_hash tertentu."""
        entries = self._hash_index.get(data_hash, [])
        result = []
        for token, request in entries:
            result.append(
                {
                    "token_id": str(token.id),
                    "serial": token.serial_number,
                    "timestamp": token.timestamp.isoformat(),
                    "status": token.status.value,
                    "requested_by": str(request.requested_by) if request.requested_by else None,
                }
            )
        return result

    async def get_token_by_serial(self, serial_number: str) -> TimestampToken | None:
        for token in self._tokens.values():
            if token.serial_number == serial_number:
                return token
        return None

    async def get_request_by_id(self, request_id: UUID) -> TimestampRequest | None:
        return self._requests.get(request_id)

    async def get_token_by_id(self, token_id: UUID) -> TimestampToken | None:
        return self._tokens.get(token_id)

    # ==================== AUDIT TRAIL ATTACHMENT ====================

    async def attach_timestamp_to_audit(
        self, audit_id: UUID, data_hash: str, requested_by: UUID | None = None
    ) -> str | None:
        """
        Membuat timestamp untuk data_hash (biasanya audit event) dan menyimpannya.
        Mengembalikan token string.
        """
        token = await self.timestamp(data_hash, requested_by=requested_by)
        # Dalam implementasi nyata, token bisa disimpan ke field audit_event.timestamp_token
        await self._log_audit(
            "ATTACH_TO_AUDIT",
            token.request_id,
            requested_by or UUID(int=0),
            {
                "audit_id": str(audit_id),
                "token_id": str(token.id),
            },
        )
        return token.token

    # ==================== UTILITIES ====================

    async def generate_hash_for_audit(self, audit_data: dict[str, Any]) -> str:
        """Generate SHA256 hash dari audit data (untuk timestamp)."""
        json_str = json.dumps(audit_data, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(json_str.encode()).hexdigest()

    async def get_statistics(self) -> dict[str, Any]:
        total_requests = len(self._requests)
        total_tokens = len(self._tokens)
        valid_tokens = sum(1 for t in self._tokens.values() if t.status == TimestampStatus.VALID)
        revoked_tokens = sum(
            1 for t in self._tokens.values() if t.status == TimestampStatus.REVOKED
        )
        expired_tokens = sum(
            1 for t in self._tokens.values() if t.expires_at and t.expires_at < datetime.now(UTC)
        )
        return {
            "total_requests": total_requests,
            "total_tokens": total_tokens,
            "valid_tokens": valid_tokens,
            "revoked_tokens": revoked_tokens,
            "expired_tokens": expired_tokens,
            "active_certificate": self._active_cert_id.hex if self._active_cert_id else None,
            "certificates_count": len(self._certificates),
            "unique_hashes": len(self._hash_index),
            "audit_log_size": len(self._audit_log),
        }

    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        return self._audit_log[offset : offset + limit]

    async def health_check(self) -> dict[str, Any]:
        has_active_cert = self._active_cert_id is not None
        return {
            "status": "healthy" if has_active_cert else "degraded",
            "total_tokens": len(self._tokens),
            "has_active_certificate": has_active_cert,
            "certificates_count": len(self._certificates),
            "audit_log_size": len(self._audit_log),
        }
