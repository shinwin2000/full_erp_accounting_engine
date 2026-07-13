#!/usr/bin/env python3
"""
Module: securitykey_management_vault.py
Layer: Infrastructure (Security)
Responsibility: Manage encryption keys using HashiCorp Vault.
               No direct import of FieldEncryptionService.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

try:
    import hvac
    VAULT_AVAILABLE = True
except ImportError:
    VAULT_AVAILABLE = False
    hvac = None

from config.loader_yaml import load_yaml_config

logger = logging.getLogger(__name__)

DEFAULT_TRANSIT_PATH = "transit"
DEFAULT_KV_ENGINE = "secret"
DEFAULT_KEY_NAME = "aes256-gcm-key"
KEY_CACHE_TTL = 300


class KeyManagementError(Exception):
    pass


class KeyNotFoundError(KeyManagementError):
    pass


class VaultUnavailableError(KeyManagementError):
    pass


@dataclass
class EncryptionKey:
    id: str
    version: int
    key_bytes: bytes
    created_at: datetime
    expires_at: datetime | None = None
    is_active: bool = True


class KeyManagementVault:
    def __init__(
        self,
        config_path: str = "config_files/security_config.yaml",
        fallback_encrypt: Callable[[str, str | None], str] | None = None,
        fallback_decrypt: Callable[[str], str] | None = None,
    ):
        self.config = self._load_config(config_path)
        self._client: hvac.Client | None = None
        self._cache: dict[str, tuple[EncryptionKey, datetime]] = {}
        self._lock = asyncio.Lock()
        self._transit_engine = self.config.get("transit_engine", DEFAULT_TRANSIT_PATH)
        self._kv_engine = self.config.get("kv_engine", DEFAULT_KV_ENGINE)
        self._fallback_encrypt = fallback_encrypt
        self._fallback_decrypt = fallback_decrypt

    def _load_config(self, config_path: str) -> dict:
        try:
            config = load_yaml_config(config_path)
            return config.get("vault", {})
        except Exception as e:
            # ConfigNotFoundError adalah kondisi normal – tidak perlu log
            if "ConfigNotFoundError" in str(type(e).__name__) or "ConfigNotFound" in str(e):
                # Still log at debug level to avoid silent swallow
                logger.debug(f"Config not found, using default Vault config: {e}")
            else:
                logger.debug(f"Vault config load error: {type(e).__name__}: {str(e)}")
            return {}

    def _get_client(self) -> hvac.Client | None:
        if not VAULT_AVAILABLE:
            return None
        if self._client:
            return self._client

        url = self.config.get("url", "http://localhost:8200")
        token = self.config.get("token")
        namespace = self.config.get("namespace")
        if token:
            self._client = hvac.Client(url=url, token=token, namespace=namespace)
            if self._client.is_authenticated():
                logger.info("Vault connected (token)")
                return self._client
        role_id = self.config.get("role_id")
        secret_id = self.config.get("secret_id")
        if role_id and secret_id:
            client = hvac.Client(url=url, namespace=namespace)
            client.auth.approle.login(role_id=role_id, secret_id=secret_id)
            self._client = client
            logger.info("Vault connected (AppRole)")
            return client
        return None

    async def _get_cached_key(self, key_id: str) -> EncryptionKey | None:
        if key_id in self._cache:
            key, expires = self._cache[key_id]
            if datetime.utcnow() < expires:
                return key
            del self._cache[key_id]
        return None

    async def _set_cached_key(self, key: EncryptionKey, ttl: int = KEY_CACHE_TTL):
        self._cache[key.id] = (key, datetime.utcnow() + timedelta(seconds=ttl))

    async def get_key(self, key_id: str = DEFAULT_KEY_NAME, version: int | None = None) -> EncryptionKey:
        cached = await self._get_cached_key(key_id)
        if cached:
            return cached

        client = self._get_client()
        if client is None:
            if self._fallback_encrypt is not None:
                raise KeyManagementError("Vault unavailable and no local key store")
            raise VaultUnavailableError("Vault unavailable")

        try:
            path = f"{self._kv_engine}/data/{key_id}"
            resp = client.secrets.kv.v2.read_secret_version(path=path, version=version)
            data = resp.get("data", {}).get("data", {})
            key_b64 = data.get("key")
            if not key_b64:
                raise KeyNotFoundError(f"Key '{key_id}' not found in Vault")
            key_bytes = base64.b64decode(key_b64)
            created_at = datetime.fromisoformat(
                data.get("created_at", datetime.utcnow().isoformat())
            )
            key = EncryptionKey(
                id=key_id,
                version=version or data.get("version", 1),
                key_bytes=key_bytes,
                created_at=created_at,
                expires_at=None,
                is_active=data.get("is_active", True),
            )
            await self._set_cached_key(key)
            return key
        except hvac.exceptions.InvalidPath as e:
            # Key not found in KV store; create it automatically
            logger.debug(f"Key '{key_id}' not found in Vault KV, creating: {e}")
            return await self.create_key(key_id)

    async def create_key(self, key_id: str, key_bytes: bytes | None = None) -> EncryptionKey:
        client = self._get_client()
        if client is None:
            raise VaultUnavailableError("Cannot create key: Vault unavailable")
        key_bytes = key_bytes or os.urandom(32)
        data = {
            "key": base64.b64encode(key_bytes).decode(),
            "created_at": datetime.utcnow().isoformat(),
            "is_active": True,
            "version": 1,
        }
        path = f"{self._kv_engine}/data/{key_id}"
        try:
            client.secrets.kv.v2.create_or_update_secret(path=path, secret=data)
            logger.info(f"Encryption key '{key_id}' stored in Vault")
        except Exception as e:
            raise KeyManagementError(f"Failed to create key: {str(e)}") from e
        key = EncryptionKey(id=key_id, version=1, key_bytes=key_bytes, created_at=datetime.utcnow())
        await self._set_cached_key(key)
        return key

    async def rotate_key(self, key_id: str = DEFAULT_KEY_NAME) -> EncryptionKey:
        client = self._get_client()
        if client is None:
            raise VaultUnavailableError("Cannot rotate key: Vault unavailable")
        try:
            client.secrets.transit.rotate_key(name=key_id)
            logger.info(f"Transit key '{key_id}' rotated")
            return await self.get_key(key_id)
        except hvac.exceptions.InvalidPath as e:
            # Transit key not found; fallback to KV rotation
            logger.debug(f"Transit key '{key_id}' not found, falling back to KV rotation: {e}")
            current = await self.get_key(key_id)
            new_version = current.version + 1
            new_bytes = os.urandom(32)
            data = {
                "key": base64.b64encode(new_bytes).decode(),
                "created_at": datetime.utcnow().isoformat(),
                "previous_version": current.version,
                "is_active": True,
                "version": new_version,
            }
            path = f"{self._kv_engine}/data/{key_id}"
            client.secrets.kv.v2.create_or_update_secret(path=path, secret=data)
            new_key = EncryptionKey(
                id=key_id, version=new_version, key_bytes=new_bytes, created_at=datetime.utcnow()
            )
            await self._set_cached_key(new_key)
            logger.info(f"KV key '{key_id}' rotated to version {new_version}")
            return new_key

    async def encrypt_with_transit(self, key_id: str, plaintext: str) -> str:
        client = self._get_client()
        if client is None:
            if self._fallback_encrypt:
                return self._fallback_encrypt(plaintext, key_id)
            raise VaultUnavailableError("No Vault and no fallback encryptor")
        try:
            b64_plain = base64.b64encode(plaintext.encode()).decode()
            resp = client.secrets.transit.encrypt_data(name=key_id, plaintext=b64_plain)
            return resp["data"]["ciphertext"]
        except Exception as e:
            raise KeyManagementError(f"Transit encrypt failed: {str(e)}") from e

    async def decrypt_with_transit(self, key_id: str, ciphertext: str) -> str:
        client = self._get_client()
        if client is None:
            if self._fallback_decrypt:
                return self._fallback_decrypt(ciphertext)
            raise VaultUnavailableError("No Vault and no fallback decryptor")
        try:
            resp = client.secrets.transit.decrypt_data(name=key_id, ciphertext=ciphertext)
            b64_plain = resp["data"]["plaintext"]
            return base64.b64decode(b64_plain).decode()
        except Exception as e:
            raise KeyManagementError(f"Transit decrypt failed: {str(e)}") from e

    async def health_check(self) -> dict:
        client = self._get_client()
        if client is None:
            return {
                "status": "degraded",
                "vault_available": False,
                "fallback_available": self._fallback_encrypt is not None,
            }
        try:
            health = client.sys.read_health_status()
            return {
                "status": "healthy" if not health.get("sealed") else "sealed",
                "sealed": health.get("sealed", True),
                "version": health.get("version"),
                "vault_available": True,
            }
        except Exception as e:
            logger.debug(f"Vault health check failed: {e}")
            return {"status": "unhealthy", "error": str(e), "vault_available": False}

    def clear_cache(self):
        self._cache.clear()
        logger.debug("Key cache cleared")


_key_management_vault: KeyManagementVault | None = None


async def get_key_management_vault(
    fallback_encrypt: Callable[[str, str | None], str] | None = None,
    fallback_decrypt: Callable[[str], str] | None = None,
) -> KeyManagementVault:
    global _key_management_vault
    if _key_management_vault is None:
        _key_management_vault = KeyManagementVault(
            fallback_encrypt=fallback_encrypt, fallback_decrypt=fallback_decrypt
        )
    return _key_management_vault


async def close_key_management_vault():
    global _key_management_vault
    _key_management_vault = None


__all__ = [
    "EncryptionKey",
    "KeyManagementError",
    "KeyManagementVault",
    "KeyNotFoundError",
    "VaultUnavailableError",
    "close_key_management_vault",
    "get_key_management_vault",
]