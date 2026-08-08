# create_missing_files.ps1
# Jalankan dari root E:\full_erp_accounting_engine

# ============================================================
# 1. ports/primary/token_issuer_port.py
# ============================================================
@'
#!/usr/bin/env python3
"""
Module: token_issuer_port.py
Layer: Ports (Primary)
Responsibility:
    - Mendefinisikan antarmuka (port) untuk penerbitan dan verifikasi token
      otentikasi (JWT).
    - Dikonsumsi oleh application layer (mis. IAMService) tanpa bergantung
      pada implementasi konkret (RS256/JWT, library jose, dll).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import timedelta
from typing import Any
from uuid import UUID


class TokenIssuerPort(ABC):
    """Port abstrak untuk penerbitan dan verifikasi token akses/refresh."""

    @abstractmethod
    async def create_access_token(
        self,
        user_id: UUID,
        username: str,
        legal_entity_id: UUID | None = None,
        roles: list[str] | None = None,
        permissions: list[str] | None = None,
        expires_delta: timedelta | None = None,
    ) -> str:
        """Buat access token baru untuk user."""
        ...

    @abstractmethod
    async def create_refresh_token(
        self,
        user_id: UUID,
        username: str,
        legal_entity_id: UUID | None = None,
        roles: list[str] | None = None,
        permissions: list[str] | None = None,
        expires_delta: timedelta | None = None,
    ) -> str:
        """Buat refresh token baru untuk user."""
        ...

    @abstractmethod
    async def verify_token(self, token: str, token_type: str = "access") -> dict[str, Any]:
        """
        Verifikasi token dan kembalikan klaimnya sebagai dict.

        Wajib menyertakan key "sub" (user_id sebagai string) untuk
        kompatibilitas dengan pemanggil yang membaca payload["sub"] secara
        langsung. Harus raise exception jika token invalid/expired/revoked.
        """
        ...

    @abstractmethod
    async def revoke_token(self, jti: str) -> None:
        """Revoke token berdasarkan JWT ID (jti)."""
        ...

    @abstractmethod
    async def is_revoked(self, jti: str) -> bool:
        """Cek apakah token dengan jti tertentu sudah di-revoke."""
        ...


__all__ = ["TokenIssuerPort"]
'@ | Set-Content -Path ".\ports\primary\token_issuer_port.py" -Encoding utf8

Write-Host "Created: ports/primary/token_issuer_port.py"

# ============================================================
# 2. infrastructure/security/jwt_token_service.py
# ============================================================
@'
#!/usr/bin/env python3
"""
Module: jwt_token_service.py
Layer: Infrastructure (Security)
Responsibility:
    - Implementasi TokenIssuerPort. Facade yang menyatukan JWTIssuer
      (pembuatan token) dan JWTValidator (verifikasi token) di balik satu
      kontrak yang dikonsumsi application layer (IAMService dkk).
    - Tidak melakukan signing/verifying sendiri — delegasi penuh ke
      JWTIssuer dan JWTValidator yang sudah ada dan teruji.
Dependencies:
- infrastructure.security.jwt_issuer (JWTIssuer, get_jwt_issuer)
- infrastructure.security.jwt_validator (JWTValidator, get_jwt_validator)
- ports.primary.token_issuer_port (TokenIssuerPort)
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID

from infrastructure.security.jwt_issuer import JWTIssuer, get_jwt_issuer
from infrastructure.security.jwt_validator import JWTValidator, get_jwt_validator
from infrastructure.telemetry.structured_json_logging import get_logger
from ports.primary.token_issuer_port import TokenIssuerPort

logger = get_logger(__name__)


class JWTTokenService(TokenIssuerPort):
    """
    Facade TokenIssuerPort di atas JWTIssuer (create) dan JWTValidator (verify).

    JWTIssuer/JWTValidator di-resolve lazy (async) saat method pertama kali
    dipanggil, karena constructor keduanya memuat RSA key dari disk dan
    sebaiknya tidak dilakukan di __init__ non-async milik service ini —
    konsisten dengan pola register_singleton(JWTTokenService, JWTTokenService)
    di service_registry yang menginstansiasi tanpa argumen.
    """

    def __init__(self) -> None:
        self._issuer: JWTIssuer | None = None
        self._validator: JWTValidator | None = None

    async def _get_issuer(self) -> JWTIssuer:
        if self._issuer is None:
            self._issuer = await get_jwt_issuer()
            logger.info("JWTTokenService: JWTIssuer resolved")
        return self._issuer

    async def _get_validator(self) -> JWTValidator:
        if self._validator is None:
            self._validator = await get_jwt_validator()
            logger.info("JWTTokenService: JWTValidator resolved")
        return self._validator

    async def create_access_token(
        self,
        user_id: UUID,
        username: str,
        legal_entity_id: UUID | None = None,
        roles: list[str] | None = None,
        permissions: list[str] | None = None,
        expires_delta: timedelta | None = None,
    ) -> str:
        issuer = await self._get_issuer()
        return await issuer.create_access_token(
            user_id=user_id,
            username=username,
            legal_entity_id=legal_entity_id,
            roles=roles,
            permissions=permissions,
            expires_delta=expires_delta,
        )

    async def create_refresh_token(
        self,
        user_id: UUID,
        username: str,
        legal_entity_id: UUID | None = None,
        roles: list[str] | None = None,
        permissions: list[str] | None = None,
        expires_delta: timedelta | None = None,
    ) -> str:
        issuer = await self._get_issuer()
        return await issuer.create_refresh_token(
            user_id=user_id,
            username=username,
            legal_entity_id=legal_entity_id,
            roles=roles,
            permissions=permissions,
            expires_delta=expires_delta,
        )

    async def verify_token(self, token: str, token_type: str = "access") -> dict[str, Any]:
        validator = await self._get_validator()
        # JWTValidator.validate() melakukan verifikasi signature, expiry,
        # issuer/audience, dan status revocation sekaligus.
        claims = await validator.validate(token, expected_token_type=token_type)

        # IAMService membaca payload["sub"] langsung (konvensi klaim JWT
        # mentah), sedangkan JWTValidator.validate() mengembalikan dict
        # yang sudah ditransformasi (key "user_id"). Petakan kembali di
        # sini supaya kontrak TokenIssuerPort konsisten untuk pemanggil.
        user_id = claims.get("user_id")
        legal_entity_id = claims.get("legal_entity_id")
        return {
            "sub": str(user_id) if user_id else None,
            "username": claims.get("username"),
            "legal_entity_id": str(legal_entity_id) if legal_entity_id else None,
            "roles": claims.get("roles", []),
            "permissions": claims.get("permissions", []),
            "exp": claims.get("exp"),
            "iat": claims.get("iat"),
            "jti": claims.get("jti"),
            "token_type": claims.get("token_type"),
        }

    async def revoke_token(self, jti: str) -> None:
        issuer = await self._get_issuer()
        await issuer.revoke_token(jti)

    async def is_revoked(self, jti: str) -> bool:
        issuer = await self._get_issuer()
        return await issuer.is_revoked(jti)


__all__ = ["JWTTokenService"]
'@ | Set-Content -Path ".\infrastructure\security\jwt_token_service.py" -Encoding utf8

Write-Host "Created: infrastructure/security/jwt_token_service.py"

# ============================================================
# 3. infrastructure/caching/redis_cache.py
# ============================================================
@'
#!/usr/bin/env python3
"""
Module: redis_cache.py
Layer: Infrastructure (Caching)
Responsibility:
    - Implementasi CachePort. Adapter tipis di atas RedisManager (singleton)
      yang sudah menangani connection pooling, health check, dan retry.
    - Reuse RedisManager singleton yang sama dengan yang dipakai
      JWTValidator — tidak membuka connection pool Redis baru.
Dependencies:
- infrastructure.caching.redis_manager (RedisManager, get_redis_manager)
- ports.primary.cache_port (CachePort)
"""

from __future__ import annotations

from typing import Any

from infrastructure.caching.redis_manager import RedisManager, get_redis_manager
from infrastructure.telemetry.structured_json_logging import get_logger
from ports.primary.cache_port import CachePort

logger = get_logger(__name__)


class RedisCache(CachePort):
    """
    Adapter CachePort di atas RedisManager singleton.

    Selain method dari CachePort (get/set/delete/exists), kelas ini juga
    menyediakan `setex` bergaya redis-py karena beberapa pemanggil (mis.
    IAMService, untuk token blacklist) memanggil `setex` langsung tanpa
    lewat kontrak CachePort.
    """

    def __init__(self) -> None:
        self._manager: RedisManager | None = None

    async def _get_manager(self) -> RedisManager:
        if self._manager is None:
            self._manager = await get_redis_manager()
            logger.info("RedisCache attached to RedisManager singleton")
        return self._manager

    async def get(self, key: str) -> Any | None:
        manager = await self._get_manager()
        return await manager.get(key)

    async def set(self, key: str, value: Any, ttl: int = 3600) -> None:
        manager = await self._get_manager()
        await manager.set(key, value, ttl_seconds=ttl)

    async def delete(self, key: str) -> None:
        manager = await self._get_manager()
        await manager.delete(None, key)

    async def exists(self, key: str) -> bool:
        manager = await self._get_manager()
        return await manager.exists(key)

    async def setex(self, key: str, ttl_seconds: int, value: Any) -> None:
        """Kompatibilitas gaya redis-py: SET dengan TTL wajib."""
        manager = await self._get_manager()
        await manager.set(key, value, ttl_seconds=ttl_seconds)


__all__ = ["RedisCache"]
'@ | Set-Content -Path ".\infrastructure\caching\redis_cache.py" -Encoding utf8

Write-Host "Created: infrastructure/caching/redis_cache.py"
Write-Host ""
Write-Host "Semua 3 file berhasil dibuat. Lanjut verifikasi import:"
