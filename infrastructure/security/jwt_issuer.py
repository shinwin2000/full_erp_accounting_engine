#!/usr/bin/env python3
"""
Module: jwt_issuer.py
Layer: Infrastructure (Security)
Responsibility: Issuer untuk JWT (JSON Web Token). Bertanggung jawab untuk
               membuat access token dan refresh token dengan signing menggunakan
               RSA private key. Mendukung claims standar (sub, exp, iat, jti)
               dan custom claims (roles, permissions, legal_entity_id).
               Juga mendukung token versioning untuk revocation.
Dependencies:
- jose (python-jose) atau PyJWT
- cryptography, uuid, datetime
- infrastructure.security.jwt_revocation_list (JWTRevocationList)
- config.loader_yaml
- infrastructure.telemetry.structured_json_logging
Audit: Setiap token yang di-issuer dicatat (metadata, bukan token itu sendiri).
       Token dibuat dengan expiry time yang sesuai dengan security policy.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt

from config.loader_yaml import load_yaml_config

# Internal dependencies
from infrastructure.security.jwt_revocation_list import JWTRevocationList
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_ALGORITHM = "RS256"
DEFAULT_ACCESS_TOKEN_EXPIRE_MINUTES = 15
DEFAULT_REFRESH_TOKEN_EXPIRE_DAYS = 7

TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_REFRESH = "refresh"

# ============================================================================
# EXCEPTIONS
# ============================================================================


class JWTIssuerError(Exception):
    """Base exception untuk JWT issuer."""

    pass


class PrivateKeyNotFoundError(JWTIssuerError):
    """Private key tidak ditemukan."""

    pass


class TokenGenerationError(JWTIssuerError):
    """Gagal generate token."""

    pass


# ============================================================================
# JWT ISSUER
# ============================================================================


class JWTIssuer:
    """
    Issuer untuk JWT access dan refresh token.

    Fitur:
    - Generate access token dengan expiry pendek
    - Generate refresh token dengan expiry panjang
    - Support token versioning untuk revocation
    - Signing dengan RSA private key
    - Custom claims untuk RBAC
    """

    def __init__(self, config_path: str = "config_files/security_config.yaml"):
        self.config = self._load_config(config_path)
        self.algorithm = self.config.get("jwt", {}).get("algorithm", DEFAULT_ALGORITHM)
        self.access_expire_minutes = self.config.get("jwt", {}).get(
            "access_token_expire_minutes", DEFAULT_ACCESS_TOKEN_EXPIRE_MINUTES
        )
        self.refresh_expire_days = self.config.get("jwt", {}).get(
            "refresh_token_expire_days", DEFAULT_REFRESH_TOKEN_EXPIRE_DAYS
        )
        self.issuer = self.config.get("jwt", {}).get("issuer", "erp-accounting-engine")
        self.audience = self.config.get("jwt", {}).get("audience", "erp-api")

        self._private_key = self._load_private_key()
        self._public_key = self._load_public_key()
        self._revocation_list = None

    def _load_config(self, config_path: str) -> dict[str, Any]:
        try:
            return load_yaml_config(config_path)
        except Exception as e:
            logger.warning(f"Security config load failed: {type(e).__name__}")
            return {}

    def _load_private_key(self) -> bytes:
        """Load RSA private key (raw PEM bytes) from file or environment."""
        key_path = self.config.get("jwt", {}).get("private_key_path", "/secrets/jwt_private.pem")

        try:
            with open(key_path, "rb") as f:
                key_data = f.read()
            logger.info("Signing material initialized")
            return key_data
        except Exception as e:
            logger.error("Failed to initialize signing material")
            raise PrivateKeyNotFoundError("Private key not found") from e

    def _load_public_key(self) -> rsa.RSAPublicKey | None:
        """Load RSA public key from file (optional, for verification)."""
        key_path = self.config.get("jwt", {}).get("public_key_path", "/secrets/jwt_public.pem")

        try:
            with open(key_path, "rb") as f:
                key_data = f.read()

            public_key = serialization.load_pem_public_key(key_data, backend=default_backend())
            logger.info("Verification material initialized")
            return public_key
        except Exception as e:
            logger.warning(f"Verification material unavailable: {type(e).__name__}")
            return None

    async def _get_revocation_list(self) -> JWTRevocationList:
        if self._revocation_list is None:
            from infrastructure.security.jwt_revocation_list import get_revocation_list

            self._revocation_list = await get_revocation_list()
        return self._revocation_list

    def _generate_jti(self) -> str:
        """Generate unique JWT ID."""
        return str(uuid.uuid4())

    def _create_token_payload(
        self,
        user_id: UUID,
        username: str,
        legal_entity_id: UUID | None,
        roles: list[str],
        permissions: list[str],
        token_type: str,
        expires_delta: timedelta,
        jti: str | None = None,
    ) -> dict[str, Any]:
        """
        Create token payload with standard and custom claims.
        """
        now = datetime.now(UTC)
        expire = now + expires_delta

        payload = {
            "iss": self.issuer,
            "aud": self.audience,
            "sub": str(user_id),
            "username": username,
            "token_type": token_type,
            "iat": now,
            "exp": expire,
            "jti": jti or self._generate_jti(),
            "roles": roles,
            "permissions": permissions,
        }

        if legal_entity_id:
            payload["legal_entity_id"] = str(legal_entity_id)

        return payload

    async def create_access_token(
        self,
        user_id: UUID,
        username: str,
        legal_entity_id: UUID | None = None,
        roles: list[str] | None = None,
        permissions: list[str] | None = None,
        expires_delta: timedelta | None = None,
    ) -> str:
        """
        Create an access token.
        """
        expires = expires_delta or timedelta(minutes=self.access_expire_minutes)

        payload = self._create_token_payload(
            user_id=user_id,
            username=username,
            legal_entity_id=legal_entity_id,
            roles=roles or [],
            permissions=permissions or [],
            token_type=TOKEN_TYPE_ACCESS,
            expires_delta=expires,
        )

        try:
            token = jwt.encode(payload, self._private_key, algorithm=self.algorithm)
            logger.debug(f"Access assertion prepared (expires in {self.access_expire_minutes}m)")
            return token
        except Exception as e:
            logger.error(f"Failed to prepare access assertion: {type(e).__name__}")
            raise TokenGenerationError("Failed to create access token") from e

    async def create_refresh_token(
        self,
        user_id: UUID,
        username: str,
        legal_entity_id: UUID | None = None,
        roles: list[str] | None = None,
        permissions: list[str] | None = None,
        expires_delta: timedelta | None = None,
    ) -> str:
        """
        Create a refresh token.
        """
        expires = expires_delta or timedelta(days=self.refresh_expire_days)

        payload = self._create_token_payload(
            user_id=user_id,
            username=username,
            legal_entity_id=legal_entity_id,
            roles=roles or [],
            permissions=permissions or [],
            token_type=TOKEN_TYPE_REFRESH,
            expires_delta=expires,
        )

        try:
            token = jwt.encode(payload, self._private_key, algorithm=self.algorithm)
            logger.debug(f"Refresh assertion prepared (expires in {self.refresh_expire_days}d)")
            return token
        except Exception as e:
            logger.error(f"Failed to prepare refresh assertion: {type(e).__name__}")
            raise TokenGenerationError("Failed to create refresh token") from e

    async def create_token_pair(
        self,
        user_id: UUID,
        username: str,
        legal_entity_id: UUID | None = None,
        roles: list[str] | None = None,
        permissions: list[str] | None = None,
    ) -> dict[str, str]:
        """
        Create both access and refresh token pair.
        """
        access_token = await self.create_access_token(
            user_id=user_id,
            username=username,
            legal_entity_id=legal_entity_id,
            roles=roles,
            permissions=permissions,
        )

        refresh_token = await self.create_refresh_token(
            user_id=user_id,
            username=username,
            legal_entity_id=legal_entity_id,
            roles=roles,
            permissions=permissions,
        )

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "Bearer",
            "expires_in": self.access_expire_minutes * 60,
        }

    async def revoke_token(self, jti: str) -> None:
        """
        Revoke a token by its JWT ID.
        """
        revocation_list = await self._get_revocation_list()
        await revocation_list.revoke(jti)
        logger.info("Revocation recorded")

    async def is_revoked(self, jti: str) -> bool:
        """
        Check if a token has been revoked.
        """
        revocation_list = await self._get_revocation_list()
        return await revocation_list.is_revoked(jti)

    def get_public_key_pem(self) -> str:
        """
        Get public key in PEM format (for distribution to services).
        """
        if self._public_key:
            return self._public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            ).decode("utf-8")

        # Derive from private key
        return (
            self._private_key.public_key()
            .public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            .decode("utf-8")
        )


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_jwt_issuer: JWTIssuer | None = None


async def get_jwt_issuer() -> JWTIssuer:
    """Get singleton instance of JWTIssuer."""
    global _jwt_issuer
    if _jwt_issuer is None:
        _jwt_issuer = JWTIssuer()
    return _jwt_issuer


# ============================================================================
# FASTAPI DEPENDENCY
# ============================================================================


async def get_token_issuer():
    """FastAPI dependency for JWT issuer."""
    return await get_jwt_issuer()


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "TOKEN_TYPE_ACCESS",
    "TOKEN_TYPE_REFRESH",
    "JWTIssuer",
    "JWTIssuerError",
    "PrivateKeyNotFoundError",
    "TokenGenerationError",
    "get_jwt_issuer",
    "get_token_issuer",
]
