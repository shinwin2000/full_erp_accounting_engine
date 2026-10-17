"""
core/session.py
================
Menyimpan state autentikasi (token, user, legal entity aktif) selama
aplikasi berjalan. Singleton sederhana yang diakses dari seluruh UI.

FIX V2 (2026-10-14):
    - Hapus duplikat `import json`
    - Tambah logging di apply_login_response & get() agar traceable
    - Pastikan `access_token`, `refresh_token`, `legal_entity_id`
      benar-benar tersimpan setelah login
"""
from __future__ import annotations

import base64
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("erp_frontend.session")

TOKEN_CACHE_FILE = Path.home() / ".sovereign_erp" / "session.json"


@dataclass
class Session:
    access_token: str | None = None
    refresh_token: str | None = None
    token_expires_at: float = 0.0
    user: dict[str, Any] = field(default_factory=dict)
    legal_entity_id: str | None = None
    legal_entities: list[dict[str, Any]] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------
    @property
    def is_authenticated(self) -> bool:
        return bool(self.access_token)

    @property
    def is_token_expiring(self) -> bool:
        """True jika token akan kadaluarsa dalam < 60 detik."""
        if not self.access_token:
            return True
        return time.time() > (self.token_expires_at - 60)

    @property
    def display_name(self) -> str:
        return self.user.get("full_name") or self.user.get("username") or "-"

    def can(self, permission: str) -> bool:
        """Dipakai UI untuk menonaktifkan tombol yang pasti ditolak server."""
        if not permission:
            return True
        perms: list[str] = []
        try:
            seg = (self.access_token or "").split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4)))
            perms = list(claims.get("permissions") or [])
        except Exception:
            return True
        if not perms:
            return True
        res, _, act = permission.partition(":")
        return any(p in ("*:*", permission, f"{res}:*", f"*:{act}") for p in perms)

    def has_permission(self, permission: str) -> bool:
        if not permission:
            return True
        if self.user.get("is_superuser"):
            return True
        return permission in self.permissions

    # ------------------------------------------------------------------
    def apply_login_response(self, data: dict[str, Any]) -> None:
        """
        FIX V2: Menyimpan token + user + legal_entity_ids dari response
        login. Ditambahkan logging supaya kelihatan di app.log apakah
        token benar-benar tersimpan atau tidak.
        """
        if not isinstance(data, dict):
            logger.error("apply_login_response: data bukan dict, tipe=%s", type(data))
            return

        access = data.get("access_token")
        refresh = data.get("refresh_token")
        user = data.get("user") or {}
        expires_in = data.get("expires_in") or 900

        self.access_token = access
        self.refresh_token = refresh
        self.token_expires_at = time.time() + float(expires_in)
        self.user = user if isinstance(user, dict) else {}
        self.roles = self.user.get("role_ids") or []
        self.permissions = self.user.get("permissions") or []

        entity_ids = self.user.get("legal_entity_ids") or []
        if entity_ids and not self.legal_entity_id:
            self.legal_entity_id = str(entity_ids[0])

        logger.info(
            "Session.login applied: access_token=%s chars, refresh_token=%s chars, "
            "legal_entity_id=%s, entity_ids_from_user=%s, user=%s",
            len(access or ""),
            len(refresh or ""),
            self.legal_entity_id,
            entity_ids,
            self.user.get("username"),
        )

    def apply_refresh_response(self, data: dict[str, Any]) -> None:
        if not isinstance(data, dict):
            return
        self.access_token = data.get("access_token", self.access_token)
        self.refresh_token = data.get("refresh_token", self.refresh_token)
        expires_in = data.get("expires_in") or 900
        self.token_expires_at = time.time() + float(expires_in)
        logger.info(
            "Session.refresh applied: access_token=%s chars",
            len(self.access_token or ""),
        )

    def clear(self) -> None:
        self.access_token = None
        self.refresh_token = None
        self.token_expires_at = 0.0
        self.user = {}
        self.legal_entity_id = None
        self.permissions = []
        self.roles = []
        try:
            if TOKEN_CACHE_FILE.exists():
                TOKEN_CACHE_FILE.unlink()
        except OSError:
            pass

    # ------------------------------------------------------------------
    def persist(self, remember: bool = True) -> None:
        if not remember:
            return
        TOKEN_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "refresh_token": self.refresh_token,
            "username": self.user.get("username"),
            "legal_entity_id": self.legal_entity_id,
        }
        with open(TOKEN_CACHE_FILE, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)

    def load_cached_refresh_token(self) -> dict[str, Any] | None:
        if not TOKEN_CACHE_FILE.exists():
            return None
        try:
            with open(TOKEN_CACHE_FILE, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError):
            return None


# Singleton instance dipakai di seluruh aplikasi
session = Session()
