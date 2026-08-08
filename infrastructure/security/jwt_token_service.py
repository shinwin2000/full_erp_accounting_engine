#!/usr/bin/env python3
"""
Module: jwt_token_service.py
Layer: Infrastructure (Security)
Responsibility:
    - Implementasi TokenIssuerPort. Facade yang menyatukan JWTIssuer
      (pembuatan token) dan JWTValidator (verifikasi token) di balik satu
      kontrak yang dikonsumsi application layer (IAMService dkk).
    - Tidak melakukan signing/verifying sendiri â€” delegasi penuh ke
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
    sebaiknya tidak dilakukan di __init__ non-async milik service ini â€”
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
