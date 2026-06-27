#!/usr/bin/env python3
"""
Module: field_encryption_aes256_gcm.py
Layer: Infrastructure (Security)
Responsibility: AES-256-GCM encryption/decryption with key management (non-Vault).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
from collections.abc import Callable
from datetime import datetime

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from config.loader_yaml import load_yaml_config

logger = logging.getLogger(__name__)

AES_KEY_SIZE = 32
NONCE_SIZE = 12
ENCRYPTION_VERSION = "v1"
DEFAULT_KEY_ID = "default"


class FieldEncryptionError(Exception):
    pass


class DecryptionError(FieldEncryptionError):
    pass


class KeyNotFoundError(FieldEncryptionError):
    pass


class FieldEncryptionService:
    def __init__(self, config_path: str = "config_files/security_config.yaml"):
        self.config = self._load_config(config_path)
        self._keys: dict[str, bytes] = {}
        self._key_meta: dict[str, dict] = {}
        self._current_key_id = DEFAULT_KEY_ID
        self._rotation_callback: Callable[[str, str], None] | None = None
        self._load_keys()

    def _load_config(self, config_path: str) -> dict:
        try:
            return load_yaml_config(config_path)
        except Exception as e:
            # ConfigNotFoundError is normal - no need to log
            if "ConfigNotFoundError" in str(type(e).__name__) or "ConfigNotFound" in str(e):
                pass
            else:
                logger.debug(f"Security config load error: {type(e).__name__}: {e!s}")
            return {}

    def _load_keys(self):
        enc_cfg = self.config.get("encryption", {})
        keys_cfg = enc_cfg.get("keys", {})
        for key_id, key_cfg in keys_cfg.items():
            key_b64 = key_cfg.get("key")
            if key_b64:
                self._keys[key_id] = base64.b64decode(key_b64)
                self._key_meta[key_id] = {
                    "created_at": key_cfg.get("created_at", datetime.utcnow().isoformat()),
                    "version": key_cfg.get("version", 1),
                }
        env_key = os.environ.get("ENCRYPTION_KEY")
        if env_key and DEFAULT_KEY_ID not in self._keys:
            self._keys[DEFAULT_KEY_ID] = base64.b64decode(env_key)
            self._key_meta[DEFAULT_KEY_ID] = {
                "created_at": datetime.utcnow().isoformat(),
                "version": 1,
            }
        if not self._keys:
            logger.info("No encryption keys found - generating ephemeral key for development")
            self._keys[DEFAULT_KEY_ID] = secrets.token_bytes(AES_KEY_SIZE)
            self._key_meta[DEFAULT_KEY_ID] = {
                "created_at": datetime.utcnow().isoformat(),
                "version": 1,
            }
        self._current_key_id = enc_cfg.get("current_key_id", DEFAULT_KEY_ID)
        if self._current_key_id not in self._keys:
            self._current_key_id = next(iter(self._keys.keys()))
        logger.info(f"Loaded {len(self._keys)} keys, current: {self._current_key_id}")

    def _get_key(self, key_id: str | None = None) -> tuple[bytes, str]:
        kid = key_id or self._current_key_id
        key = self._keys.get(kid)
        if not key:
            raise KeyNotFoundError(f"Encryption key '{kid}' not found")
        return key, kid

    def encrypt(self, plaintext: str, key_id: str | None = None, aad: bytes | None = None) -> str:
        if not plaintext:
            return ""
        key, used_id = self._get_key(key_id)
        nonce = secrets.token_bytes(NONCE_SIZE)
        aesgcm = AESGCM(key)
        aad_data = (aad or b"") + f"|{ENCRYPTION_VERSION}|{used_id}".encode()
        ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), aad_data)
        parts = [
            ENCRYPTION_VERSION,
            used_id,
            base64.b64encode(nonce).decode(),
            base64.b64encode(ciphertext).decode(),
        ]
        return "|".join(parts)

    def decrypt(self, ciphertext: str, aad: bytes | None = None) -> str:
        if not ciphertext:
            return ""
        try:
            parts = ciphertext.split("|")
            if len(parts) != 4:
                raise DecryptionError("Invalid encrypted data format")
            version, key_id, nonce_b64, data_b64 = parts
            if version != ENCRYPTION_VERSION:
                raise DecryptionError(f"Unsupported version: {version}")
            key, _ = self._get_key(key_id)
            nonce = base64.b64decode(nonce_b64)
            ct = base64.b64decode(data_b64)
            aad_data = (aad or b"") + f"|{version}|{key_id}".encode()
            aesgcm = AESGCM(key)
            plaintext = aesgcm.decrypt(nonce, ct, aad_data)
            return plaintext.decode()
        except DecryptionError:
            raise
        except Exception as e:
            raise DecryptionError(f"Decryption error: {e!s}") from e

    def encrypt_deterministic(self, plaintext: str, key_id: str | None = None) -> str:
        if not plaintext:
            return ""
        key, used_id = self._get_key(key_id)
        h = hmac.new(key, plaintext.encode(), hashlib.sha256)
        nonce = h.digest()[:NONCE_SIZE]
        aesgcm = AESGCM(key)
        aad_data = f"|{ENCRYPTION_VERSION}|{used_id}|deterministic".encode()
        ciphertext = aesgcm.encrypt(nonce, plaintext.encode(), aad_data)
        parts = [
            ENCRYPTION_VERSION,
            used_id,
            base64.b64encode(nonce).decode(),
            base64.b64encode(ciphertext).decode(),
        ]
        return "|".join(parts)

    def decrypt_deterministic(self, ciphertext: str, aad: bytes | None = None) -> str:
        return self.decrypt(ciphertext, aad)

    def encrypt_json(self, data: dict, key_id: str | None = None) -> str:
        return self.encrypt(json.dumps(data, default=str), key_id)

    def decrypt_to_json(self, ciphertext: str) -> dict:
        return json.loads(self.decrypt(ciphertext))

    def add_key(self, key_id: str, key_bytes: bytes, version: int = 1, created_at: str | None = None):
        self._keys[key_id] = key_bytes
        self._key_meta[key_id] = {
            "created_at": created_at or datetime.utcnow().isoformat(),
            "version": version,
        }
        logger.info(f"Added key {key_id} (version {version})")

    def rotate_key(self, new_key_id: str | None = None) -> str:
        new_id = new_key_id or f"key_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        new_key = secrets.token_bytes(AES_KEY_SIZE)
        self._keys[new_id] = new_key
        self._key_meta[new_id] = {
            "created_at": datetime.utcnow().isoformat(),
            "version": self._key_meta.get(self._current_key_id, {}).get("version", 0) + 1,
        }
        old_id = self._current_key_id
        self._current_key_id = new_id
        if self._rotation_callback:
            self._rotation_callback(old_id, new_id)
        logger.info(f"Rotated key from {old_id} to {new_id}")
        return new_id

    def set_rotation_callback(self, callback: Callable[[str, str], None]):
        self._rotation_callback = callback

    def get_current_key_id(self) -> str:
        return self._current_key_id

    def get_key_ids(self) -> list[str]:
        return list(self._keys.keys())

    def get_key_info(self, key_id: str) -> dict:
        return self._key_meta.get(key_id, {})


# Alias for backward compatibility
FieldEncryption = FieldEncryptionService

_field_encryption: FieldEncryptionService | None = None


def get_field_encryption() -> FieldEncryptionService:
    global _field_encryption
    if _field_encryption is None:
        _field_encryption = FieldEncryptionService()
    return _field_encryption


__all__ = [
    "DecryptionError",
    "FieldEncryption",
    "FieldEncryptionError",
    "FieldEncryptionService",
    "KeyNotFoundError",
    "get_field_encryption",
]
