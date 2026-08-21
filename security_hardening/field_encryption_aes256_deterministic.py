#!/usr/bin/env python3
"""
Module: field_encryption_aes256_deterministic.py
Layer: Security Hardening

Responsibility:
    Enkripsi field dengan AES-256 dalam mode deterministic (AES-SIV atau AES-CBC dengan IV deterministik).
    Memungkinkan pencarian exact match pada data terenkripsi (seperti NPWP, email, nomor rekening).
    Mendukung key rotation, key versioning, dan integrasi dengan KMS.

Metode yang ditambahkan:
- Untuk DeterministicKeyManager: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk DeterministicEncryption: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk EncryptedField: validate (descriptor) dan method pendukung.
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
from datetime import UTC, datetime
from typing import Any

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .security_exceptions import EncryptionError, KeyManagementError

logger = logging.getLogger(__name__)

# Coba import AES-SIV (dari cryptography >= 3.0)
try:
    from cryptography.hazmat.primitives.ciphers.modes import SIV

    HAS_SIV = True
except ImportError:
    HAS_SIV = False


# ============================================================================
# DeterministicKeyManager (dengan entity dasar)
# ============================================================================
class DeterministicKeyManager:
    """Manajer kunci untuk deterministic encryption dengan rotasi sederhana."""

    def __init__(self, master_key: bytes | None = None, key_file: str | None = None):
        self._keys: dict[int, bytes] = {}
        self._current_version: int = 1
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._take_snapshot()

        if master_key:
            self._keys[1] = master_key
        elif key_file and os.path.exists(key_file):
            self._load_keys(key_file)
        else:
            self._keys[1] = secrets.token_bytes(32)
            self._current_version = 1
            if key_file:
                self._save_keys(key_file)

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "current_version": self._current_version,
                "key_count": len(self._keys),
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "details": details,
            }
        )

    def _save_keys(self, key_file: str) -> None:
        data = {
            "keys": {str(v): base64.b64encode(k).decode() for v, k in self._keys.items()},
            "current_version": self._current_version,
            "version": self._version,
        }
        with open(key_file, "w") as f:
            json.dump(data, f)
        os.chmod(key_file, 0o600)

    def _load_keys(self, key_file: str) -> None:
        with open(key_file) as f:
            data = json.load(f)
        self._keys = {int(v): base64.b64decode(k) for v, k in data["keys"].items()}
        self._current_version = data.get(
            "current_version", max(self._keys.keys()) if self._keys else 1
        )
        self._version = data.get("version", 1)

    def get_current_key(self) -> tuple[int, bytes]:
        return self._current_version, self._keys[self._current_version]

    def get_key_by_version(self, version: int) -> bytes | None:
        return self._keys.get(version)

    def rotate_key(self) -> int:
        new_version = max(self._keys.keys()) + 1
        self._keys[new_version] = secrets.token_bytes(32)
        self._current_version = new_version
        self._version += 1
        self._record_audit("ROTATE_KEY", "system", {"new_version": new_version})
        return new_version

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if not self._keys:
            errors.append("No keys available")
        for ver, key in self._keys.items():
            if len(key) != 32:
                errors.append(f"Key version {ver} has invalid length {len(key)}")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_version": self._current_version,
            "key_count": len(self._keys),
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeterministicKeyManager:
        instance = cls()
        instance._current_version = data.get("current_version", 1)
        instance._version = data.get("version", 1)
        # Note: keys cannot be restored from dict for security
        return instance

    def clone(self) -> DeterministicKeyManager:
        new = DeterministicKeyManager()
        new._keys = self._keys.copy()
        new._current_version = self._current_version
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "current_version": self._current_version,
            "key_count": len(self._keys),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> DeterministicKeyManager:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# ============================================================================
# DeterministicEncryption Core (dengan entity dasar)
# ============================================================================
class DeterministicEncryption:
    """
    Enkripsi deterministic AES-256 dalam mode SIV (jika tersedia) atau
    CBC dengan IV deterministik (HMAC-SHA256).
    """

    def __init__(
        self,
        master_key: bytes | None = None,
        key_manager: DeterministicKeyManager | None = None,
        use_siv: bool = True,
    ):
        self._backend = default_backend()
        self._use_siv = use_siv and HAS_SIV
        if key_manager:
            self._key_manager = key_manager
        else:
            self._key_manager = DeterministicKeyManager(master_key=master_key)
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._take_snapshot()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "use_siv": self._use_siv,
                "key_manager_version": self._key_manager.version(),
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "details": details,
            }
        )

    def _derive_iv(self, plaintext: bytes, key: bytes) -> bytes:
        """Menghasilkan IV deterministik dari plaintext menggunakan HMAC-SHA256."""
        return hmac.new(key, plaintext, hashlib.sha256).digest()[:16]

    def encrypt(self, plaintext: str, key_version: int | None = None) -> str:
        if plaintext is None:
            return None
        if not isinstance(plaintext, str):
            plaintext = str(plaintext)
        try:
            version, key = self._key_manager.get_current_key()
            if key_version is not None:
                # FIX: gunakan temporary variable untuk menghindari mypy error
                temp_key = self._key_manager.get_key_by_version(key_version)
                if temp_key is None:
                    raise KeyManagementError(f"Key version {key_version} not found")
                key = temp_key
                version = key_version

            plain_bytes = plaintext.encode("utf-8")

            if self._use_siv:
                cipher = Cipher(algorithms.AES(key), mode=SIV(), backend=self._backend)
                encryptor = cipher.encryptor()
                ciphertext = encryptor.update(plain_bytes) + encryptor.finalize()
                result = f"siv:v{version}:{base64.b64encode(ciphertext).decode()}"
            else:
                iv = self._derive_iv(plain_bytes, key)
                cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=self._backend)
                encryptor = cipher.encryptor()
                padder = padding.PKCS7(128).padder()
                padded = padder.update(plain_bytes) + padder.finalize()
                ciphertext = encryptor.update(padded) + encryptor.finalize()
                result = f"v{version}:{base64.b64encode(iv + ciphertext).decode()}"

            self._record_audit(
                "ENCRYPT", "system", {"key_version": version, "use_siv": self._use_siv}
            )
            logger.debug(f"Encrypted field with version {version}, use_siv={self._use_siv}")
            return result
        except Exception as e:
            raise EncryptionError(f"Deterministic encryption failed: {e}")

    def decrypt(self, ciphertext_b64_or_str: str) -> str:
        if ciphertext_b64_or_str is None:
            return None
        try:
            if ciphertext_b64_or_str.startswith("siv:v"):
                parts = ciphertext_b64_or_str.split(":")
                if len(parts) < 3:
                    raise EncryptionError("Invalid SIV ciphertext format")
                version_str = parts[1]
                version = int(version_str[1:])
                b64_data = parts[2]
                key = self._key_manager.get_key_by_version(version)
                if key is None:
                    raise KeyManagementError(f"Key version {version} not found")
                ciphertext = base64.b64decode(b64_data)
                cipher = Cipher(algorithms.AES(key), mode=SIV(), backend=self._backend)
                decryptor = cipher.decryptor()
                plaintext = decryptor.update(ciphertext) + decryptor.finalize()
                return plaintext.decode("utf-8")
            elif ciphertext_b64_or_str.startswith("v"):
                parts = ciphertext_b64_or_str.split(":", 1)
                if len(parts) < 2:
                    raise EncryptionError("Invalid ciphertext format")
                version_str = parts[0]
                version = int(version_str[1:])
                b64_data = parts[1]
                key = self._key_manager.get_key_by_version(version)
                if key is None:
                    raise KeyManagementError(f"Key version {version} not found")
                data = base64.b64decode(b64_data)
                iv = data[:16]
                ciphertext = data[16:]
                cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=self._backend)
                decryptor = cipher.decryptor()
                padded = decryptor.update(ciphertext) + decryptor.finalize()
                unpadder = padding.PKCS7(128).unpadder()
                plain_bytes = unpadder.update(padded) + unpadder.finalize()
                return plain_bytes.decode("utf-8")
            else:
                data = base64.b64decode(ciphertext_b64_or_str)
                iv = data[:16]
                ciphertext = data[16:]
                version, key = self._key_manager.get_current_key()
                cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=self._backend)
                decryptor = cipher.decryptor()
                padded = decryptor.update(ciphertext) + decryptor.finalize()
                unpadder = padding.PKCS7(128).unpadder()
                plain_bytes = unpadder.update(padded) + unpadder.finalize()
                return plain_bytes.decode("utf-8")
        except Exception as e:
            raise EncryptionError(f"Deterministic decryption failed: {e}")

    def rotate_keys(self, reencrypt_func: Callable[[str], str] | None = None) -> int:
        new_version = self._key_manager.rotate_key()
        self._record_audit("ROTATE_KEYS", "system", {"new_version": new_version})
        logger.info(f"Key rotated to version {new_version}")
        return new_version

    def get_current_version(self) -> int:
        return self._key_manager._current_version

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        res = self._key_manager.validate()
        if not res["is_valid"]:
            errors.extend([f"KeyManager: {e}" for e in res["errors"]])
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "use_siv": self._use_siv,
            "key_manager": self._key_manager.to_dict(),
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeterministicEncryption:
        key_mgr = DeterministicKeyManager.from_dict(data.get("key_manager", {}))
        instance = cls(key_manager=key_mgr, use_siv=data.get("use_siv", HAS_SIV))
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> DeterministicEncryption:
        new = DeterministicEncryption(
            key_manager=self._key_manager.clone(),
            use_siv=self._use_siv,
        )
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "use_siv": self._use_siv,
            "current_key_version": self.get_current_version(),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> DeterministicEncryption:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# ============================================================================
# EncryptedField (descriptor untuk model)
# ============================================================================
class EncryptedField:
    """Descriptor untuk field yang dienkripsi deterministic di model."""

    def __init__(self, cipher: DeterministicEncryption, field_name: str):
        self.cipher = cipher
        self.field_name = field_name
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "details": details,
            }
        )

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        encrypted_value = obj.__dict__.get(f"_{self.field_name}")
        if encrypted_value is None:
            return None
        return self.cipher.decrypt(encrypted_value)

    def __set__(self, obj, value):
        if value is None:
            obj.__dict__[f"_{self.field_name}"] = None
            return
        encrypted = self.cipher.encrypt(value)
        obj.__dict__[f"_{self.field_name}"] = encrypted
        self._record_audit("SET", "system", {"field": self.field_name})

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if not self.cipher:
            errors.append("Cipher is required")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_name": self.field_name,
            "cipher_version": self.cipher.version() if self.cipher else None,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], cipher: DeterministicEncryption) -> EncryptedField:
        instance = cls(cipher, data["field_name"])
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> EncryptedField:
        new = EncryptedField(self.cipher, self.field_name)
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "field_name": self.field_name,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> EncryptedField:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    encryption = DeterministicEncryption(use_siv=HAS_SIV)
    plain = "123456789012345"
    encrypted = encryption.encrypt(plain)
    print(f"Plain: {plain}")
    print(f"Encrypted: {encrypted}")
    decrypted = encryption.decrypt(encrypted)
    print(f"Decrypted: {decrypted}")
    assert plain == decrypted

    print(f"\nCurrent key version: {encryption.get_current_version()}")
    new_version = encryption.rotate_keys()
    print(f"New key version: {new_version}")

    new_encrypted = encryption.encrypt(plain)
    print(f"Re-encrypted with new key: {new_encrypted}")
    new_decrypted = encryption.decrypt(new_encrypted)
    print(f"Decrypted after rotation: {new_decrypted}")

    key_mgr = DeterministicKeyManager(key_file="encryption_keys.json")
    print("\nKeys saved to encryption_keys.json")
