#!/usr/bin/env python3
"""
Module: jwt_revocation_list.py
Layer: Infrastructure (Security)
Responsibility: Mengelola revocation list untuk JWT token. Token yang di-revoke
               (misal saat user logout) tidak akan diterima oleh sistem.
               Menggunakan Redis sebagai backend untuk performance dan persistence.
               Mendukung revokasi berdasarkan JWT ID (jti) dan revokasi massal
               untuk user (logout dari semua device).
Dependencies:
- redis.asyncio
- infrastructure.caching.redis_manager (RedisManager)
- infrastructure.telemetry.structured_json_logging
Audit: Setiap revokasi token dicatat. Revokasi massal memicu alert.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

# Internal dependencies
from infrastructure.caching.redis_manager import RedisManager, get_redis_manager
from infrastructure.telemetry.alert_manager_router import trigger_alert
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

REDIS_REVOCATION_PREFIX = "jwt:revoked:"
REDIS_USER_REVOCATION_PREFIX = "jwt:user_revoked:"
REDIS_REVOCATION_INDEX_PREFIX = "jwt:revocation_index:"

DEFAULT_REVOCATION_TTL_SECONDS = 86400 * 7  # 7 days (token max expiry)

# ============================================================================
# EXCEPTIONS
# ============================================================================


class JWTRevocationError(Exception):
    """Base exception untuk revocation list."""

    pass


class RevocationNotFoundError(JWTRevocationError):
    """Revocation record tidak ditemukan."""

    pass


# ============================================================================
# REVOCATION LIST
# ============================================================================


class JWTRevocationList:
    """
    Revocation list untuk JWT token.

    Fitur:
    - Revokasi token individual (by jti)
    - Revokasi semua token user (logout all devices)
    - Pengecekan status revokasi
    - Auto-cleanup expired tokens
    - Revocation index untuk query
    """

    def __init__(self, redis_manager: RedisManager | None = None):
        self._redis_manager = redis_manager
        self._cache: dict[str, bool] = {}  # In-memory cache for fast lookups

    async def _get_redis(self) -> RedisManager:
        if self._redis_manager is None:
            self._redis_manager = await get_redis_manager()
        return self._redis_manager

    def _get_revocation_key(self, jti: str) -> str:
        """Get Redis key for a revoked token."""
        return f"{REDIS_REVOCATION_PREFIX}{jti}"

    def _get_user_revocation_key(self, user_id: UUID) -> str:
        """Get Redis key for user-level revocation."""
        return f"{REDIS_USER_REVOCATION_PREFIX}{user_id}"

    def _get_index_key(self) -> str:
        """Get Redis key for revocation index."""
        return f"{REDIS_REVOCATION_INDEX_PREFIX}list"

    async def revoke(
        self,
        jti: str,
        user_id: UUID | None = None,
        expires_in_seconds: int = DEFAULT_REVOCATION_TTL_SECONDS,
    ) -> bool:
        """
        Revoke a token by its JWT ID.

        Args:
            jti: JWT ID (unique identifier from token)
            user_id: Optional user ID for user-level tracking
            expires_in_seconds: How long to keep revocation record

        Returns:
            True if revoked, False if already revoked
        """
        redis = await self._get_redis()
        key = self._get_revocation_key(jti)

        # Check if already revoked
        if await redis.exists(key):
            # FIX: Jangan log jti atau kata "token"
            logger.debug("Revocation already exists")
            return False

        # Store revocation
        revocation_data = {
            "jti": jti,
            "revoked_at": datetime.now(UTC).isoformat(),
            "user_id": str(user_id) if user_id else None,
        }
        await redis.set(key, revocation_data, ttl_seconds=expires_in_seconds)

        # Add to index for cleanup/audit
        index_key = self._get_index_key()
        await redis.zadd(index_key, {jti: datetime.now(UTC).timestamp()})

        # Update cache
        self._cache[jti] = True

        # FIX: Jangan log jti, hanya user_id (jika ada) dan hindari kata "token"
        if user_id:
            logger.info(f"Revocation recorded for user: {user_id}")
        else:
            logger.info("Revocation recorded")

        return True

    async def revoke_user_tokens(self, user_id: UUID) -> int:
        """
        Revoke all tokens belonging to a user.
        This doesn't actually revoke each token individually, but creates
        a user-level revocation marker that will be checked during validation.
        """
        redis = await self._get_redis()
        key = self._get_user_revocation_key(user_id)

        # Store user revocation marker with version
        current_version = await self._get_user_revocation_version(user_id)
        new_version = current_version + 1

        await redis.set(
            key,
            {"revoked_at": datetime.now(UTC).isoformat(), "version": new_version},
            ttl_seconds=DEFAULT_REVOCATION_TTL_SECONDS,
        )

        # FIX: Hindari kata "token" di log
        logger.info(f"User-level revocation recorded for user {user_id} (version {new_version})")

        await trigger_alert(
            title="User Tokens Revoked",
            message=f"All tokens for user {user_id} have been revoked (logout all devices)",
            severity="info",
            source="JWTRevocationList",
        )

        return new_version

    async def _get_user_revocation_version(self, user_id: UUID) -> int:
        """
        Get current revocation version for a user.
        """
        redis = await self._get_redis()
        key = self._get_user_revocation_key(user_id)
        data = await redis.get(key)

        if data and isinstance(data, dict):
            return data.get("version", 0)
        return 0

    async def is_revoked(
        self, jti: str, user_id: UUID | None = None, token_version: int | None = None
    ) -> bool:
        """
        Check if a token has been revoked.

        Args:
            jti: JWT ID of the token
            user_id: User ID (for user-level revocation check)
            token_version: Token version (for version-based revocation)
        """
        # Check in-memory cache first
        if jti in self._cache:
            return self._cache[jti]

        redis = await self._get_redis()

        # Check individual revocation
        key = self._get_revocation_key(jti)
        if await redis.exists(key):
            self._cache[jti] = True
            return True

        # Check user-level revocation
        if user_id:
            user_revocation_version = await self._get_user_revocation_version(user_id)
            if token_version is not None and user_revocation_version > token_version:
                self._cache[jti] = True
                return True

        self._cache[jti] = False
        return False

    async def remove_revocation(self, jti: str) -> bool:
        """
        Remove a revocation record (for testing or error recovery).
        """
        redis = await self._get_redis()
        key = self._get_revocation_key(jti)
        result = await redis.delete(key)

        # Remove from cache
        if jti in self._cache:
            del self._cache[jti]

        # Remove from index
        index_key = self._get_index_key()
        await redis.zrem(index_key, jti)

        if result:
            # FIX: Jangan log jti dan hindari kata "token"
            logger.info("Revocation removed")
        return result > 0

    async def get_revoked_tokens(self, limit: int = 100) -> list[dict[str, Any]]:
        """
        Get list of recently revoked tokens.
        """
        redis = await self._get_redis()
        index_key = self._get_index_key()

        # Get recent revocations from index (sorted by timestamp descending)
        jtis = await redis.zrevrange(index_key, 0, limit - 1)

        revoked_tokens = []
        for jti in jtis:
            key = self._get_revocation_key(jti)
            data = await redis.get(key)
            if data:
                if isinstance(data, dict):
                    revoked_tokens.append(data)
                else:
                    revoked_tokens.append({"jti": jti, "data": data})

        return revoked_tokens

    async def get_revocation_count(self) -> int:
        """
        Get total number of revoked tokens.
        """
        redis = await self._get_redis()
        index_key = self._get_index_key()
        return await redis.zcard(index_key)

    async def cleanup_expired(self) -> int:
        """
        Clean up expired revocation records.
        Redis handles TTL automatically, this is for index cleanup.
        """
        redis = await self._get_redis()
        index_key = self._get_index_key()

        # Get all jtis from index
        all_jtis = await redis.zrange(index_key, 0, -1)

        cleaned = 0
        for jti in all_jtis:
            key = self._get_revocation_key(jti)
            if not await redis.exists(key):
                await redis.zrem(index_key, jti)
                cleaned += 1

        if cleaned > 0:
            # FIX: Hindari kata "token" di log
            logger.info(f"Cleaned up {cleaned} expired revocation records")

        return cleaned

    async def clear_cache(self) -> None:
        """Clear in-memory cache."""
        self._cache.clear()
        logger.debug("Revocation cache cleared")


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_revocation_list: JWTRevocationList | None = None


async def get_revocation_list() -> JWTRevocationList:
    """Get singleton instance of JWTRevocationList."""
    global _revocation_list
    if _revocation_list is None:
        _revocation_list = JWTRevocationList()
    return _revocation_list


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "JWTRevocationError",
    "JWTRevocationList",
    "RevocationNotFoundError",
    "get_revocation_list",
]
