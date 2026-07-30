from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID

from infrastructure.security.jwt_issuer import JWTIssuer
from infrastructure.security.jwt_validator import JWTValidator


class AppTokenIssuer:
    """
    Adapter yang menyatukan JWTIssuer (pembuatan token) dan JWTValidator
    (verifikasi token) menjadi satu objek yang memenuhi kontrak TokenIssuerPort
    yang dipakai oleh IAMService (create_access_token, create_refresh_token,
    verify_token).
    """

    def __init__(self, config_path: str = "config_files/security_config.yaml"):
        self._issuer = JWTIssuer(config_path=config_path)
        self._validator = JWTValidator(config_path=config_path)

    async def create_access_token(
        self,
        user_id: UUID,
        username: str,
        legal_entity_id: UUID | None,
        roles: list[str],
        permissions: list[str],
        expires_delta: timedelta | None = None,
    ) -> str:
        return await self._issuer.create_access_token(
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
        legal_entity_id: UUID | None,
        roles: list[str],
        permissions: list[str],
        expires_delta: timedelta | None = None,
    ) -> str:
        return await self._issuer.create_refresh_token(
            user_id=user_id,
            username=username,
            legal_entity_id=legal_entity_id,
            roles=roles,
            permissions=permissions,
            expires_delta=expires_delta,
        )

    async def verify_token(self, token: str, token_type: str = "access") -> dict[str, Any]:
        """
        service_iam.py mengakses hasil ini lewat payload["sub"], payload["username"],
        dst. JWTValidator.validate() mengembalikan key "user_id", jadi kita remap
        di sini supaya kontraknya konsisten dengan yang diharapkan IAMService.
        """
        result = await self._validator.validate(token, expected_token_type=token_type)
        return {
            "sub": str(result["user_id"]) if result["user_id"] else None,
            "username": result["username"],
            "legal_entity_id": (
                str(result["legal_entity_id"]) if result["legal_entity_id"] else None
            ),
            "roles": result["roles"],
            "permissions": result["permissions"],
            "exp": result["exp"],
            "iat": result["iat"],
            "jti": result["jti"],
            "token_type": result["token_type"],
        }
