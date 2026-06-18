#!/usr/bin/env python3
"""
Module: event_source_authenticator.py
Layer: Event Gateway
Responsibility: Memverifikasi keaslian dan integritas sumber event.

Metode yang ditambahkan:
- Untuk AuthenticatedSource: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk EventSourceAuthenticator: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)


class AuthMethod(Enum):
    HMAC_SHA256 = "hmac_sha256"
    API_KEY = "api_key"
    JWT = "jwt"
    IP_WHITELIST = "ip_whitelist"
    SERVICE_NAME = "service_name"

    def display_name(self) -> str:
        names = {
            AuthMethod.HMAC_SHA256: "HMAC-SHA256",
            AuthMethod.API_KEY: "API Key",
            AuthMethod.JWT: "JWT",
            AuthMethod.IP_WHITELIST: "IP Whitelist",
            AuthMethod.SERVICE_NAME: "Service Name",
        }
        return names.get(self, self.value)


class EventAuthenticationError(Exception):
    pass


@dataclass(kw_only=True)
class AuthenticatedSource:
    source_id: str
    method: AuthMethod
    roles: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    # Fields untuk audit dan versioning
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _version: int = 1
    _id: str = field(default_factory=lambda: str(uuid4()), repr=False)

    def __post_init__(self):
        self._take_snapshot()
        self._validate()

    def _validate(self):
        if not self.source_id:
            raise ValueError("source_id is required")
        if not isinstance(self.method, AuthMethod):
            raise ValueError("method must be AuthMethod enum")

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "auth_id": self._id,
                "source_id": self.source_id,
                "method": self.method.value,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "auth_id": self._id,
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except ValueError as e:
            errors.append(str(e))
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self._id,
            "source_id": self.source_id,
            "method": self.method.value,
            "roles": self.roles,
            "permissions": self.permissions,
            "metadata": self.metadata,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AuthenticatedSource:
        instance = cls(
            source_id=data["source_id"],
            method=AuthMethod(data["method"]),
            roles=data.get("roles", []),
            permissions=data.get("permissions", []),
            metadata=data.get("metadata", {}),
        )
        instance._id = data.get("id", str(uuid4()))
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> AuthenticatedSource:
        new = AuthenticatedSource(
            source_id=self.source_id,
            method=self.method,
            roles=self.roles.copy(),
            permissions=self.permissions.copy(),
            metadata=self.metadata.copy(),
        )
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self._id})
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "id": self._id,
            "source_id": self.source_id,
            "method": self.method.value,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> AuthenticatedSource:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


class EventSourceAuthenticator:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.api_keys: dict[str, str] = config.get("api_keys", {})
        self.hmac_secrets: dict[str, str] = config.get("hmac_secrets", {})
        self.jwt_public_keys: dict[str, str] = config.get("jwt_public_keys", {})
        self.ip_whitelist: dict[str, list[str]] = config.get("ip_whitelist", {})
        self.service_whitelist: list[str] = config.get("service_whitelist", [])
        self.enable_timestamp_check = config.get("enable_timestamp_check", True)
        self.max_skew_seconds = config.get("max_skew_seconds", 300)
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._take_snapshot()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "details": details,
            }
        )

    def authenticate(
        self, event: dict[str, Any], source_metadata: dict[str, Any] | None = None
    ) -> AuthenticatedSource:
        source_metadata = source_metadata or {}
        auth_header = event.get("headers", {}).get("Authorization", "")
        source_name = event.get("source", "")

        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            return self._authenticate_jwt(token, source_metadata)
        if auth_header.startswith("HMAC "):
            hmac_part = auth_header[5:]
            return self._authenticate_hmac(event, hmac_part, source_metadata)
        api_key = event.get("headers", {}).get("X-API-Key") or event.get("api_key")
        if api_key:
            return self._authenticate_api_key(api_key, source_metadata)
        if source_name:
            return self._authenticate_service_name(source_name, source_metadata)
        ip_address = source_metadata.get("ip_address")
        if ip_address:
            return self._authenticate_ip(ip_address, source_metadata)
        raise EventAuthenticationError("No authentication method available")

    def _authenticate_api_key(self, api_key: str, metadata: dict[str, Any]) -> AuthenticatedSource:
        for source_id, valid_key in self.api_keys.items():
            if hmac.compare_digest(api_key, valid_key):
                self._record_audit("AUTH_API_KEY_SUCCESS", "system", {"source_id": source_id})
                logger.info(f"API Key auth success for {source_id}")
                return AuthenticatedSource(
                    source_id=source_id,
                    method=AuthMethod.API_KEY,
                    metadata={"ip": metadata.get("ip_address")},
                )
        self._record_audit("AUTH_API_KEY_FAILURE", "system", {})
        raise EventAuthenticationError("Invalid API Key")

    def _authenticate_hmac(
        self, event: dict[str, Any], signature_b64: str, metadata: dict[str, Any]
    ) -> AuthenticatedSource:
        try:
            signature = base64.b64decode(signature_b64)
        except Exception:
            raise EventAuthenticationError("Invalid HMAC signature format")
        source_id = event.get("source")
        if not source_id or source_id not in self.hmac_secrets:
            raise EventAuthenticationError("Unknown source for HMAC")
        secret = self.hmac_secrets[source_id].encode("utf-8")
        timestamp = event.get("timestamp", int(time.time()))
        method = event.get("method", "POST")
        path = event.get("path", "/")
        body = json.dumps(event.get("body", {}), sort_keys=True)
        message = f"{timestamp}{method}{path}{body}".encode()
        expected = hmac.new(secret, message, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, signature):
            raise EventAuthenticationError("HMAC signature mismatch")
        if self.enable_timestamp_check:
            now = int(time.time())
            if abs(now - timestamp) > self.max_skew_seconds:
                raise EventAuthenticationError("Timestamp too old")
        self._record_audit("AUTH_HMAC_SUCCESS", "system", {"source_id": source_id})
        return AuthenticatedSource(
            source_id=source_id, method=AuthMethod.HMAC_SHA256, metadata={"timestamp": timestamp}
        )

    def _authenticate_jwt(self, token: str, metadata: dict[str, Any]) -> AuthenticatedSource:
        import jwt

        for source_id, pubkey_pem in self.jwt_public_keys.items():
            try:
                payload = jwt.decode(
                    token, pubkey_pem, algorithms=["RS256", "ES256"], options={"verify_exp": True}
                )
                self._record_audit("AUTH_JWT_SUCCESS", "system", {"source_id": source_id})
                return AuthenticatedSource(
                    source_id=payload.get("sub", source_id),
                    method=AuthMethod.JWT,
                    roles=payload.get("roles", []),
                    permissions=payload.get("perms", []),
                    metadata={"jwt_payload": payload},
                )
            except jwt.InvalidTokenError:
                continue
        self._record_audit("AUTH_JWT_FAILURE", "system", {})
        raise EventAuthenticationError("Invalid JWT")

    def _authenticate_service_name(
        self, source_name: str, metadata: dict[str, Any]
    ) -> AuthenticatedSource:
        if source_name in self.service_whitelist:
            self._record_audit("AUTH_SERVICE_SUCCESS", "system", {"source_name": source_name})
            return AuthenticatedSource(
                source_id=source_name,
                method=AuthMethod.SERVICE_NAME,
                metadata={"service": source_name},
            )
        self._record_audit("AUTH_SERVICE_FAILURE", "system", {"source_name": source_name})
        raise EventAuthenticationError(f"Service name {source_name} not allowed")

    def _authenticate_ip(self, ip_address: str, metadata: dict[str, Any]) -> AuthenticatedSource:
        for source_id, ip_cidrs in self.ip_whitelist.items():
            for cidr in ip_cidrs:
                if ipaddress.ip_address(ip_address) in ipaddress.ip_network(cidr):
                    self._record_audit(
                        "AUTH_IP_SUCCESS", "system", {"source_id": source_id, "ip": ip_address}
                    )
                    return AuthenticatedSource(
                        source_id=source_id,
                        method=AuthMethod.IP_WHITELIST,
                        metadata={"ip": ip_address, "cidr": cidr},
                    )
        self._record_audit("AUTH_IP_FAILURE", "system", {"ip": ip_address})
        raise EventAuthenticationError(f"IP {ip_address} not allowed")

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if self.max_skew_seconds <= 0:
            errors.append("max_skew_seconds must be positive")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "api_keys_count": len(self.api_keys),
            "hmac_secrets_count": len(self.hmac_secrets),
            "jwt_keys_count": len(self.jwt_public_keys),
            "ip_whitelist_count": len(self.ip_whitelist),
            "service_whitelist": self.service_whitelist,
            "enable_timestamp_check": self.enable_timestamp_check,
            "max_skew_seconds": self.max_skew_seconds,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EventSourceAuthenticator:
        config = {
            "api_keys": data.get("api_keys", {}),
            "hmac_secrets": data.get("hmac_secrets", {}),
            "jwt_public_keys": data.get("jwt_public_keys", {}),
            "ip_whitelist": data.get("ip_whitelist", {}),
            "service_whitelist": data.get("service_whitelist", []),
            "enable_timestamp_check": data.get("enable_timestamp_check", True),
            "max_skew_seconds": data.get("max_skew_seconds", 300),
        }
        instance = cls(config)
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> EventSourceAuthenticator:
        config = {
            "api_keys": self.api_keys.copy(),
            "hmac_secrets": self.hmac_secrets.copy(),
            "jwt_public_keys": self.jwt_public_keys.copy(),
            "ip_whitelist": {k: v.copy() for k, v in self.ip_whitelist.items()},
            "service_whitelist": self.service_whitelist.copy(),
            "enable_timestamp_check": self.enable_timestamp_check,
            "max_skew_seconds": self.max_skew_seconds,
        }
        new = EventSourceAuthenticator(config)
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> EventSourceAuthenticator:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self

    def reset_stats(self) -> None:
        self._version += 1
        self._audit_trail = []
        self._snapshots = []
        self._record_audit("RESET_STATS", "system", {})


__all__ = [
    "AuthMethod",
    "AuthenticatedSource",
    "EventAuthenticationError",
    "EventSourceAuthenticator",
]
