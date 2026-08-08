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
