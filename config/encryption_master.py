#!/usr/bin/env python3
"""
Module: encryption_master.py
Layer: 3 - Bootstrap & Config / Configuration
Responsibility: Mengelola kunci enkripsi untuk konfigurasi sensitif.
               Menyediakan enkripsi/dekripsi untuk nilai-nilai konfigurasi
               yang sensitif (password, API keys, secrets) menggunakan AES-256-GCM.
               Mendukung key rotation dan integrasi dengan Vault.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from config.exceptions import ConfigEncryptionError, ConfigError, ConfigErrorCode

try:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC as PBKDF2
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("cryptography library not available, using fallback encryption")

logger = logging.getLogger(__name__)

ENCRYPTED_PREFIX = "encrypted:"
DEFAULT_KEY_LENGTH = 32
SALT_LENGTH = 16
NONCE_LENGTH = 12
PBKDF2_ITERATIONS = 100000


@dataclass(kw_only=True)
class EncryptedValue:
    ciphertext: bytes
    nonce: bytes
    salt: bytes
    key_id: str
    encrypted_at: datetime

    _version: int = field(default=1, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _value_id: str = field(default_factory=lambda: str(uuid4()), repr=False)

    def __post_init__(self):
        self._take_snapshot()
        self._validate()

    def _validate(self):
        if not self.ciphertext:
            raise ValueError("ciphertext is required")
        if len(self.nonce) != NONCE_LENGTH:
            raise ValueError(f"nonce must be {NONCE_LENGTH} bytes")
        if len(self.salt) != SALT_LENGTH:
            raise ValueError(f"salt must be {SALT_LENGTH} bytes")
        if not self.key_id:
            raise ValueError("key_id is required")
        if self.encrypted_at.tzinfo is None:
            object.__setattr__(self, "encrypted_at", self.encrypted_at.replace(tzinfo=UTC))

    def _take_snapshot(self):
        self._snapshots.append({
            "version": self._version,
            "value_id": self._value_id,
            "key_id": self.key_id,
            "timestamp": datetime.now(UTC).isoformat(),
        })
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        self._audit_trail.append({
            "action": action,
            "performed_by": performed_by,
            "timestamp": datetime.now(UTC).isoformat(),
            "version": self._version,
            "value_id": self._value_id,
            "details": details,
        })

    def to_dict(self) -> dict[str, Any]:
        return {
            "value_id": self._value_id,
            "ciphertext": base64.b64encode(self.ciphertext).decode("ascii"),
            "nonce": base64.b64encode(self.nonce).decode("ascii"),
            "salt": base64.b64encode(self.salt).decode("ascii"),
            "key_id": self.key_id,
            "encrypted_at": self.encrypted_at.isoformat(),
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EncryptedValue:
        instance = cls(
            ciphertext=base64.b64decode(data["ciphertext"]),
            nonce=base64.b64decode(data["nonce"]),
            salt=base64.b64decode(data["salt"]),
            key_id=data["key_id"],
            encrypted_at=datetime.fromisoformat(data["encrypted_at"]),
        )
        instance._version = data.get("version", 1)
        instance._value_id = data.get("value_id", str(uuid4()))
        return instance

    def clone(self) -> EncryptedValue:
        new = EncryptedValue(
            ciphertext=self.ciphertext,
            nonce=self.nonce,
            salt=self.salt,
            key_id=self.key_id,
            encrypted_at=datetime.now(UTC),
        )
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self._value_id})
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "value_id": self._value_id,
            "key_id": self.key_id,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> EncryptedValue:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self

    def to_string(self) -> str:
        data = {
            "ciphertext": base64.b64encode(self.ciphertext).decode("ascii"),
            "nonce": base64.b64encode(self.nonce).decode("ascii"),
            "salt": base64.b64encode(self.salt).decode("ascii"),
            "key_id": self.key_id,
            "encrypted_at": self.encrypted_at.isoformat(),
        }
        return f"{ENCRYPTED_PREFIX}{base64.b64encode(json.dumps(data).encode()).decode('ascii')}"

    @classmethod
    def from_string(cls, value: str) -> EncryptedValue | None:
        if not value.startswith(ENCRYPTED_PREFIX):
            return None
        try:
            encoded_data = value[len(ENCRYPTED_PREFIX):]
            data_json = base64.b64decode(encoded_data).decode("utf-8")
            data = json.loads(data_json)
            return cls.from_dict(data)
        except Exception as e:
            logger.error(f"Failed to parse encrypted value: {e}")
            return None


@dataclass(kw_only=True)
class EncryptionKey:
    key_id: str
    key_material: bytes
    expires_at: datetime | None
    is_active: bool
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    version: int = 1

    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _key_uid: str = field(default_factory=lambda: str(uuid4()), repr=False)

    def __post_init__(self):
        self._take_snapshot()
        self._validate()

    def _validate(self):
        if not self.key_id:
            raise ValueError("key_id is required")
        if len(self.key_material) != DEFAULT_KEY_LENGTH:
            raise ValueError(f"key_material must be {DEFAULT_KEY_LENGTH} bytes")
        if self.expires_at and self.expires_at.tzinfo is None:
            object.__setattr__(self, "expires_at", self.expires_at.replace(tzinfo=UTC))
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))

    def _take_snapshot(self):
        self._snapshots.append({
            "version": self.version,
            "key_uid": self._key_uid,
            "key_id": self.key_id,
            "is_active": self.is_active,
            "timestamp": datetime.now(UTC).isoformat(),
        })
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        self._audit_trail.append({
            "action": action,
            "performed_by": performed_by,
            "timestamp": datetime.now(UTC).isoformat(),
            "version": self.version,
            "key_id": self.key_id,
            "details": details,
        })

    def is_expired(self) -> bool:
        return self.expires_at is not None and datetime.now(UTC) > self.expires_at

    def can_encrypt(self) -> bool:
        return self.is_active and not self.is_expired()

    def can_decrypt(self) -> bool:
        return not self.is_expired()

    def to_dict(self) -> dict[str, Any]:
        return {
            "key_uid": self._key_uid,
            "key_id": self.key_id,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat(),
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], key_material: bytes) -> EncryptionKey:
        instance = cls(
            key_id=data["key_id"],
            key_material=key_material,
            expires_at=datetime.fromisoformat(data["expires_at"]) if data.get("expires_at") else None,
            is_active=data["is_active"],
            created_at=datetime.fromisoformat(data["created_at"]),
            version=data.get("version", 1),
        )
        instance._key_uid = data.get("key_uid", str(uuid4()))
        return instance

    def clone(self) -> EncryptionKey:
        new = EncryptionKey(
            key_id=self.key_id,
            key_material=self.key_material,
            expires_at=self.expires_at,
            is_active=self.is_active,
            created_at=datetime.now(UTC),
            version=self.version + 1,
        )
        new._record_audit("CLONE", "system", {"source": self._key_uid})
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "key_uid": self._key_uid,
            "key_id": self.key_id,
            "is_active": self.is_active,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> EncryptionKey:
        self.version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


class EncryptionMaster:
    _instance: EncryptionMaster | None = None
    _keys: dict[str, EncryptionKey]
    _current_key_id: str | None

    def __new__(cls) -> EncryptionMaster:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._keys = {}
        self._current_key_id = None
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._take_snapshot()
        self._init_default_key()

    def _take_snapshot(self):
        self._snapshots.append({
            "version": self._version,
            "key_count": len(self._keys),
            "current_key_id": self._current_key_id,
            "timestamp": datetime.now(UTC).isoformat(),
        })
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        self._audit_trail.append({
            "action": action,
            "performed_by": performed_by,
            "timestamp": datetime.now(UTC).isoformat(),
            "version": self._version,
            "details": details,
        })

    def _init_default_key(self) -> None:
        env_key = os.environ.get("CONFIG_ENCRYPTION_KEY")
        if env_key:
            try:
                key_material = base64.b64decode(env_key)
                if len(key_material) == DEFAULT_KEY_LENGTH:
                    self._add_key("default", key_material, is_active=True)
                    return
            except Exception:
                pass
        key_material = secrets.token_bytes(DEFAULT_KEY_LENGTH)
        self._add_key("default", key_material, is_active=True)
        logger.warning("Generated new default encryption key (store it safely!)")

    def _add_key(self, key_id: str, key_material: bytes, is_active: bool = True, expires_at: datetime | None = None) -> EncryptionKey:
        key = EncryptionKey(
            key_id=key_id,
            key_material=key_material,
            created_at=datetime.now(UTC),
            expires_at=expires_at,
            is_active=is_active,
            version=len(self._keys) + 1,
        )
        self._keys[key_id] = key
        if is_active:
            self._current_key_id = key_id
        self._record_audit("ADD_KEY", "system", {"key_id": key_id})
        logger.info(f"Added encryption key: {key_id}")
        return key

    def rotate_key(self, new_key_id: str | None = None) -> str:
        key_id = new_key_id or f"key_{int(datetime.now(UTC).timestamp())}"
        key_material = secrets.token_bytes(DEFAULT_KEY_LENGTH)
        for key in self._keys.values():
            key.is_active = False
        self._add_key(key_id, key_material, is_active=True)
        self._record_audit("ROTATE_KEY", "system", {"new_key_id": key_id})
        logger.info(f"Rotated encryption key to {key_id}")
        return key_id

    def encrypt(self, plaintext: str, key_id: str | None = None) -> str:
        if not CRYPTO_AVAILABLE:
            logger.warning("Cryptography not available, using base64 encoding (insecure)")
            encoded = base64.b64encode(plaintext.encode()).decode()
            return f"{ENCRYPTED_PREFIX}{encoded}"

        key_id = key_id or self._current_key_id
        if not key_id or key_id not in self._keys:
            raise ConfigEncryptionError(
                f"Encryption key {key_id} not found",
                key_id=key_id,
            )

        key = self._keys[key_id]
        if not key.can_encrypt():
            raise ConfigEncryptionError(
                f"Encryption key {key_id} is not active or expired",
                key_id=key_id,
            )

        salt = secrets.token_bytes(SALT_LENGTH)
        nonce = secrets.token_bytes(NONCE_LENGTH)
        kdf = PBKDF2(
            algorithm=hashes.SHA256(),
            length=DEFAULT_KEY_LENGTH,
            salt=salt,
            iterations=PBKDF2_ITERATIONS,
        )
        derived_key = kdf.derive(key.key_material)
        aesgcm = AESGCM(derived_key)
        ciphertext = aesgcm.encrypt(nonce, plaintext.encode(), None)

        encrypted = EncryptedValue(
            ciphertext=ciphertext,
            nonce=nonce,
            salt=salt,
            key_id=key_id,
            encrypted_at=datetime.now(UTC),
        )
        self._record_audit("ENCRYPT", "system", {"key_id": key_id})
        return encrypted.to_string()

    def decrypt(self, encrypted_value: str) -> str:
        if not encrypted_value.startswith(ENCRYPTED_PREFIX):
            return encrypted_value
        if not CRYPTO_AVAILABLE:
            encoded = encrypted_value[len(ENCRYPTED_PREFIX):]
            try:
                return base64.b64decode(encoded).decode("utf-8")
            except Exception:
                return encrypted_value

        encrypted = EncryptedValue.from_string(encrypted_value)
        if not encrypted:
            raise ConfigEncryptionError("Failed to parse encrypted value")

        if encrypted.key_id not in self._keys:
            raise ConfigEncryptionError(
                f"Encryption key {encrypted.key_id} not found for decryption",
                key_id=encrypted.key_id,
            )

        key = self._keys[encrypted.key_id]
        if not key.can_decrypt():
            raise ConfigEncryptionError(
                f"Encryption key {encrypted.key_id} is expired",
                key_id=encrypted.key_id,
            )

        kdf = PBKDF2(
            algorithm=hashes.SHA256(),
            length=DEFAULT_KEY_LENGTH,
            salt=encrypted.salt,
            iterations=PBKDF2_ITERATIONS,
        )
        derived_key = kdf.derive(key.key_material)
        aesgcm = AESGCM(derived_key)
        plaintext = aesgcm.decrypt(encrypted.nonce, encrypted.ciphertext, None)
        return plaintext.decode("utf-8")

    def reencrypt(self, encrypted_value: str, target_key_id: str | None = None) -> str:
        plaintext = self.decrypt(encrypted_value)
        target_key_id = target_key_id or self._current_key_id
        return self.encrypt(plaintext, target_key_id)

    def is_encrypted(self, value: str) -> bool:
        return value.startswith(ENCRYPTED_PREFIX)

    def get_current_key_id(self) -> str | None:
        return self._current_key_id

    def get_keys(self) -> list[dict[str, Any]]:
        return [
            {
                "key_id": k.key_id,
                "created_at": k.created_at.isoformat(),
                "expires_at": k.expires_at.isoformat() if k.expires_at else None,
                "is_active": k.is_active,
                "version": k.version,
            }
            for k in self._keys.values()
        ]

    def process_config(self, config: dict[str, Any]) -> dict[str, Any]:
        if isinstance(config, dict):
            return {k: self.process_config(v) for k, v in config.items()}
        elif isinstance(config, list):
            return [self.process_config(item) for item in config]
        elif isinstance(config, str) and self.is_encrypted(config):
            return self.decrypt(config)
        else:
            return config

    def encrypt_sensitive_values(self, config: dict[str, Any], sensitive_keys: list[str]) -> dict[str, Any]:
        result = config.copy()
        for key_path in sensitive_keys:
            self._encrypt_nested_value(result, key_path)
        return result

    def _encrypt_nested_value(self, config: dict[str, Any], key_path: str) -> None:
        keys = key_path.split(".")
        current = config
        for key in keys[:-1]:
            if key not in current or not isinstance(current[key], dict):
                return
            current = current[key]
        last_key = keys[-1]
        if last_key in current and isinstance(current[last_key], str):
            current[last_key] = self.encrypt(current[last_key])

    def validate(self) -> dict[str, Any]:
        errors = []
        if not self._keys:
            errors.append("No encryption keys available")
        if not self._current_key_id:
            errors.append("No active encryption key")
        for key in self._keys.values():
            try:
                key._validate()
            except ValueError as e:
                errors.append(f"Key {key.key_id}: {e}")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_key_id": self._current_key_id,
            "keys": self.get_keys(),
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EncryptionMaster:
        instance = cls()
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> EncryptionMaster:
        new = EncryptionMaster()
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "key_count": len(self._keys),
            "current_key_id": self._current_key_id,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> EncryptionMaster:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self

    def reset(self) -> None:
        self._keys = {}
        self._current_key_id = None
        self._version = 1
        self._audit_trail = []
        self._snapshots = []
        self._init_default_key()
        self._record_audit("RESET", "system", {})


_encryption_master_instance: EncryptionMaster | None = None

def get_encryption_master() -> EncryptionMaster:
    global _encryption_master_instance
    if _encryption_master_instance is None:
        _encryption_master_instance = EncryptionMaster()
    return _encryption_master_instance

def encrypt_config_value(plaintext: str) -> str:
    return get_encryption_master().encrypt(plaintext)

def decrypt_config_value(encrypted: str) -> str:
    return get_encryption_master().decrypt(encrypted)

def process_encrypted_config(config: dict[str, Any]) -> dict[str, Any]:
    return get_encryption_master().process_config(config)

__all__ = [
    "CRYPTO_AVAILABLE",
    "EncryptedValue",
    "EncryptionKey",
    "EncryptionMaster",
    "decrypt_config_value",
    "encrypt_config_value",
    "get_encryption_master",
    "process_encrypted_config",
]