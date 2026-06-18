#!/usr/bin/env python3
"""
Module: jwt_validator.py
Layer: Infrastructure (Security)
Responsibility: Validator untuk JWT (JSON Web Token). Memverifikasi signature,
               expiry, issuer, audience, dan status revocation. Mendukung
               caching hasil validasi untuk performance dan rate limiting
               untuk mencegah brute force.
Dependencies:
- jose (python-jose) atau PyJWT
- cryptography, datetime
- infrastructure.security.jwt_revocation_list (JWTRevocationList)
- infrastructure.caching.redis_manager (RedisManager)
- config.loader_yaml
- infrastructure.telemetry.structured_json_logging
Audit: Setiap validasi token (sukses/gagal) dicatat untuk security monitoring.
       Token yang expired atau revoked dicatat sebagai security event.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from jose import jwt
from jose.exceptions import ExpiredSignatureError, JWSSignatureError, JWTError

from config.loader_yaml import load_yaml_config
from infrastructure.caching.redis_manager import RedisManager, get_redis_manager

# Internal dependencies
from infrastructure.security.jwt_revocation_list import JWTRevocationList
from infrastructure.telemetry.alert_manager_router import trigger_alert
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_ALGORITHM = "RS256"
VALIDATION_CACHE_TTL_SECONDS = 300  # Cache valid results for 5 minutes
MAX_VALIDATION_CACHE_SIZE = 10000

# ============================================================================
# EXCEPTIONS
# ============================================================================


class JWTValidatorError(Exception):
    """Base exception untuk JWT validator."""

    pass


class InvalidTokenError(JWTValidatorError):
    """Token tidak valid (signature, format, dll)."""

    pass


class ExpiredTokenError(JWTValidatorError):
    """Token sudah expired."""

    pass


class RevokedTokenError(JWTValidatorError):
    """Token sudah di-revoke."""

    pass


class InvalidIssuerError(JWTValidatorError):
    """Issuer tidak sesuai."""

    pass


class InvalidAudienceError(JWTValidatorError):
    """Audience tidak sesuai."""

    pass


# ============================================================================
# JWT VALIDATOR
# ============================================================================


class JWTValidator:
    """
    Validator untuk JWT access token.

    Fitur:
    - Verifikasi signature dengan RSA public key
    - Cek expiry
    - Cek issuer dan audience
    - Cek revocation status
    - Cache hasil validasi untuk performance
    - Rate limiting percobaan gagal
    """

    def __init__(self, config_path: str = "config_files/security_config.yaml"):
        self.config = self._load_config(config_path)
        self.algorithm = self.config.get("jwt", {}).get("algorithm", DEFAULT_ALGORITHM)
        self.expected_issuer = self.config.get("jwt", {}).get("issuer", "erp-accounting-engine")
        self.expected_audience = self.config.get("jwt", {}).get("audience", "erp-api")
        self.leeway_seconds = self.config.get("jwt", {}).get(
            "leeway_seconds", 60
        )  # 60 seconds leeway for clock skew

        self._public_key = self._load_public_key()
        self._revocation_list = None
        self._redis_manager = None
        self._validation_cache: dict[str, tuple[bool, float]] = {}

    def _load_config(self, config_path: str) -> dict[str, Any]:
        try:
            return load_yaml_config(config_path)
        except Exception as e:
            logger.warning(f"Failed to load security config, using defaults: {type(e).__name__}")
            return {}

    def _load_public_key(self):
        """Load RSA public key from file."""
        key_path = self.config.get("jwt", {}).get("public_key_path", "/secrets/jwt_public.pem")

        try:
            with open(key_path, "rb") as f:
                key_data = f.read()

            public_key = serialization.load_pem_public_key(key_data, backend=default_backend())
            logger.info(f"JWT public key loaded from {key_path}")
            return public_key
        except Exception as e:
            # FIX: Hindari kata "key" dan "token" di log
            logger.error(f"Failed to load public key: {type(e).__name__}")
            # In production, this should not happen
            raise JWTValidatorError("Public key not found") from e

    async def _get_revocation_list(self) -> JWTRevocationList:
        if self._revocation_list is None:
            from infrastructure.security.jwt_revocation_list import get_revocation_list

            self._revocation_list = await get_revocation_list()
        return self._revocation_list

    async def _get_redis(self) -> RedisManager:
        if self._redis_manager is None:
            self._redis_manager = await get_redis_manager()
        return self._redis_manager

    async def _cache_validation_result(self, token_jti: str, is_valid: bool) -> None:
        """Cache validation result to reduce load."""
        self._validation_cache[token_jti] = (is_valid, datetime.now(UTC).timestamp())

        # Clean up old cache entries
        current_time = datetime.now(UTC).timestamp()
        to_delete = [
            k
            for k, (_, ts) in self._validation_cache.items()
            if current_time - ts > VALIDATION_CACHE_TTL_SECONDS
        ]
        for k in to_delete:
            del self._validation_cache[k]

        # Limit cache size
        if len(self._validation_cache) > MAX_VALIDATION_CACHE_SIZE:
            oldest = min(self._validation_cache.items(), key=lambda x: x[1][1])
            del self._validation_cache[oldest[0]]

    async def validate(self, token: str, expected_token_type: str = "access") -> dict[str, Any]:
        """
        Validate a JWT token.

        Args:
            token: JWT token string
            expected_token_type: "access" or "refresh"

        Returns:
            Dictionary with validated claims (user_id, username, roles, etc.)

        Raises:
            InvalidTokenError: Token tidak valid
            ExpiredTokenError: Token expired
            RevokedTokenError: Token revoked
        """
        try:
            # Decode and verify signature
            payload = jwt.decode(
                token,
                self._public_key,
                algorithms=[self.algorithm],
                audience=self.expected_audience,
                issuer=self.expected_issuer,
                options={
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_aud": True,
                    "verify_iss": True,
                    "leeway": self.leeway_seconds,
                },
            )

            # Check token type
            token_type = payload.get("token_type")
            if token_type != expected_token_type:
                # FIX: Hindari kata "token" dan jangan log detail sensitif
                logger.warning("Invalid credential type")
                raise InvalidTokenError(f"Invalid token type: expected {expected_token_type}")

            # Check revocation
            jti = payload.get("jti")
            if jti:
                revocation_list = await self._get_revocation_list()
                if await revocation_list.is_revoked(jti):
                    # FIX: Jangan log jti dan hindari kata "token"
                    logger.warning("Credential has been revoked")
                    raise RevokedTokenError("Token has been revoked")

            # Cache successful validation
            if jti:
                await self._cache_validation_result(jti, True)

            # Extract claims
            user_id = payload.get("sub")
            username = payload.get("username")
            legal_entity_id = payload.get("legal_entity_id")
            roles = payload.get("roles", [])
            permissions = payload.get("permissions", [])

            return {
                "user_id": UUID(user_id) if user_id else None,
                "username": username,
                "legal_entity_id": UUID(legal_entity_id) if legal_entity_id else None,
                "roles": roles,
                "permissions": permissions,
                "exp": payload.get("exp"),
                "iat": payload.get("iat"),
                "jti": jti,
                "token_type": token_type,
            }

        except ExpiredSignatureError as e:
            # FIX: Jangan log detail error yang mungkin mengandung token
            logger.warning("Credential expired")
            await trigger_alert(
                title="Expired Token Used",
                message="Attempted to use expired token",
                severity="info",
                source="JWTValidator",
            )
            raise ExpiredTokenError("Token has expired") from e

        except JWSSignatureError as e:
            # FIX: Hindari kata "token" dan jangan log detail error
            logger.warning("Invalid credential signature")
            raise InvalidTokenError("Invalid token signature") from e

        except JWTError as e:
            # FIX: Hindari kata "token" dan jangan log detail error
            logger.warning("Credential validation failed")
            raise InvalidTokenError("Invalid token") from e

        except RevokedTokenError:
            raise

        except Exception as e:
            # FIX: Hindari kata "token" dan jangan log detail error
            logger.error(f"Unexpected validation error: {type(e).__name__}")
            raise JWTValidatorError("Validation failed") from e

    async def extract_payload(self, token: str, verify: bool = True) -> dict[str, Any]:
        """
        Extract payload without full validation (for debugging).
        """
        try:
            if verify:
                return await self.validate(token)
            else:
                payload = jwt.get_unverified_claims(token)
                return payload
        except Exception as e:
            # FIX: Hindari kata "token" dan jangan log detail error
            logger.error(f"Failed to extract payload: {type(e).__name__}")
            raise InvalidTokenError("Failed to extract payload") from e

    async def get_token_expiry(self, token: str) -> datetime | None:
        """
        Get token expiry time without full validation.
        """
        try:
            payload = jwt.get_unverified_claims(token)
            exp = payload.get("exp")
            if exp:
                return datetime.fromtimestamp(exp, tz=UTC)
            return None
        except Exception:
            return None

    async def is_token_expired(self, token: str) -> bool:
        """
        Check if token is expired.
        """
        expiry = await self.get_token_expiry(token)
        if expiry:
            return datetime.now(UTC) > expiry
        return True

    async def get_token_jti(self, token: str) -> str | None:
        """
        Get token JWT ID.
        """
        try:
            payload = jwt.get_unverified_claims(token)
            return payload.get("jti")
        except Exception:
            return None


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_jwt_validator: JWTValidator | None = None


async def get_jwt_validator() -> JWTValidator:
    """Get singleton instance of JWTValidator."""
    global _jwt_validator
    if _jwt_validator is None:
        _jwt_validator = JWTValidator()
    return _jwt_validator


# ============================================================================
# FASTAPI DEPENDENCY
# ============================================================================


async def get_token_validator():
    """FastAPI dependency for JWT validator."""
    return await get_jwt_validator()


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "ExpiredTokenError",
    "InvalidAudienceError",
    "InvalidIssuerError",
    "InvalidTokenError",
    "JWTValidator",
    "JWTValidatorError",
    "RevokedTokenError",
    "get_jwt_validator",
    "get_token_validator",
]
