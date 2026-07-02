#!/usr/bin/env python3
"""
Module: infrastructure/security/key_management.py
Layer: 4 - Infrastructure / Security
Responsibility: Manajemen kunci enkripsi yang persisten.
                Mendukung multiple keys, key rotation, dan penyimpanan
                di environment variable (production) atau file (development).

Fitur:
- Menyimpan key dalam format base64 di environment variable atau file JSON.
- Mendukung multiple keys dengan key ID.
- Menyediakan current key untuk enkripsi/dekripsi.
- Key rotation dengan re-encryption (callback opsional).
- Validasi key strength (minimal 32 bytes).
- Logging dan error handling yang jelas.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# ============================================================
# Constants
# ============================================================
DEFAULT_KEY_LENGTH = 32  # 256-bit AES key
ENV_KEYS_VAR = "ENCRYPTION_KEYS"  # JSON string dengan keys dan current
ENV_MASTER_KEY_VAR = "ENCRYPTION_MASTER_KEY"  # Opsional: untuk enkripsi file keys
DEFAULT_KEYS_FILE = Path(__file__).parent.parent.parent / "config" / "encryption_keys.json"
DEFAULT_KEY_ID = "default"

# ============================================================
# Data Classes
# ============================================================
@dataclass
class KeyEntry:
    """Representasi satu kunci enkripsi."""
    key_id: str
    key_bytes: bytes
    created_at: datetime
    version: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key_id": self.key_id,
            "key": base64.b64encode(self.key_bytes).decode("ascii"),
            "created_at": self.created_at.isoformat(),
            "version": self.version,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KeyEntry:
        return cls(
            key_id=data["key_id"],
            key_bytes=base64.b64decode(data["key"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            version=data.get("version", 1),
            metadata=data.get("metadata", {}),
        )


# ============================================================
# KeyManager Class
# ============================================================
class KeyManager:
    """
    Manajer kunci enkripsi yang persisten.
    Mendukung environment variable (production) atau file JSON (development).
    """

    _instance: KeyManager | None = None
    _lock = None

    def __new__(cls) -> KeyManager:
        if cls._instance is None:
            import threading
            cls._lock = threading.Lock()
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._keys: dict[str, KeyEntry] = {}
        self._current_key_id: str | None = None
        self._loaded = False
        self._keys_file: Path = DEFAULT_KEYS_FILE
        self._load_keys()

    # ============================================================
    # Load / Save Keys
    # ============================================================
    def _load_keys(self) -> None:
        """Muat kunci dari environment variable atau file JSON."""
        try:
            # 1. Coba dari environment variable
            env_keys = os.environ.get(ENV_KEYS_VAR)
            if env_keys:
                data = json.loads(env_keys)
                self._load_from_dict(data)
                logger.info(f"Loaded {len(self._keys)} keys from environment variable {ENV_KEYS_VAR}")
                self._loaded = True
                return

            # 2. Coba dari file JSON
            if self._keys_file.exists():
                with open(self._keys_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._load_from_dict(data)
                logger.info(f"Loaded {len(self._keys)} keys from {self._keys_file}")
                self._loaded = True
                return

            # 3. Tidak ada key: generate default untuk development
            logger.warning("No encryption keys found. Generating ephemeral key for development.")
            self._generate_default_key()
            self._loaded = True
            # Simpan ke file agar persisten
            self._save_keys()
            logger.info(f"Generated ephemeral key and saved to {self._keys_file}")

        except Exception as e:
            logger.error(f"Failed to load encryption keys: {e}")
            # Fallback: generate key default
            logger.warning("Generating fallback key due to load failure")
            self._generate_default_key()
            self._loaded = True

    def _load_from_dict(self, data: dict[str, Any]) -> None:
        """Load keys from dictionary structure."""
        keys_data = data.get("keys", {})
        current = data.get("current")
        for key_id, key_data in keys_data.items():
            entry = KeyEntry.from_dict({"key_id": key_id, **key_data})
            self._keys[key_id] = entry
        if current and current in self._keys:
            self._current_key_id = current
        elif self._keys:
            # Set current to first key if none specified
            self._current_key_id = next(iter(self._keys))
        else:
            self._current_key_id = None

    def _save_keys(self) -> None:
        """Simpan kunci ke file JSON (untuk development) atau environment variable."""
        try:
            data = self._to_dict()
            # Simpan ke file
            self._keys_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._keys_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.debug(f"Saved keys to {self._keys_file}")
            # Jika ada ENV_MASTER_KEY, kita bisa enkripsi file, tapi untuk sekarang cukup simpan plain.
        except Exception as e:
            logger.error(f"Failed to save keys to file: {e}")
            # Tidak raise agar aplikasi tetap bisa berjalan

    def _to_dict(self) -> dict[str, Any]:
        """Konversi semua key ke dictionary untuk serialisasi."""
        return {
            "keys": {
                key_id: entry.to_dict() for key_id, entry in self._keys.items()
            },
            "current": self._current_key_id,
        }

    def _generate_default_key(self) -> None:
        """Generate default key dan set sebagai current."""
        key_bytes = secrets.token_bytes(DEFAULT_KEY_LENGTH)
        entry = KeyEntry(
            key_id=DEFAULT_KEY_ID,
            key_bytes=key_bytes,
            created_at=datetime.now(UTC),
            version=1,
            metadata={"source": "auto_generated"},
        )
        self._keys[DEFAULT_KEY_ID] = entry
        self._current_key_id = DEFAULT_KEY_ID
        logger.info("Default encryption key generated")

    # ============================================================
    # Public Methods
    # ============================================================
    def get_current_key(self) -> bytes | None:
        """Kembalikan bytes dari kunci yang sedang aktif."""
        if not self._loaded:
            self._load_keys()
        if self._current_key_id is None:
            return None
        entry = self._keys.get(self._current_key_id)
        return entry.key_bytes if entry else None

    def get_current_key_id(self) -> str | None:
        """Kembalikan ID kunci yang sedang aktif."""
        return self._current_key_id

    def get_key(self, key_id: str) -> bytes | None:
        """Kembalikan bytes dari kunci dengan ID tertentu."""
        if not self._loaded:
            self._load_keys()
        entry = self._keys.get(key_id)
        return entry.key_bytes if entry else None

    def list_keys(self) -> list[dict[str, Any]]:
        """Daftar semua kunci (metadata)."""
        if not self._loaded:
            self._load_keys()
        result = []
        for key_id, entry in self._keys.items():
            result.append({
                "key_id": key_id,
                "created_at": entry.created_at.isoformat(),
                "version": entry.version,
                "is_current": (key_id == self._current_key_id),
                "metadata": entry.metadata,
            })
        return result

    def add_key(self, key_id: str, key_bytes: bytes, metadata: dict[str, Any] | None = None) -> None:
        """Tambahkan kunci baru (tidak otomatis menjadi current)."""
        if not self._loaded:
            self._load_keys()
        if len(key_bytes) < DEFAULT_KEY_LENGTH:
            raise ValueError(f"Key must be at least {DEFAULT_KEY_LENGTH} bytes")
        if key_id in self._keys:
            raise ValueError(f"Key ID '{key_id}' already exists")
        entry = KeyEntry(
            key_id=key_id,
            key_bytes=key_bytes,
            created_at=datetime.now(UTC),
            version=1,
            metadata=metadata or {},
        )
        self._keys[key_id] = entry
        self._save_keys()
        logger.info(f"Added new key: {key_id}")

    def set_current_key(self, key_id: str) -> None:
        """Set kunci aktif."""
        if not self._loaded:
            self._load_keys()
        if key_id not in self._keys:
            raise ValueError(f"Key '{key_id}' not found")
        self._current_key_id = key_id
        self._save_keys()
        logger.info(f"Current key set to: {key_id}")

    def rotate_key(self, new_key_id: str | None = None, callback: Callable[[bytes, bytes], None] | None = None) -> str:
        """
        Rotasi kunci: generate key baru, set sebagai current, dan panggil callback untuk re-encrypt.
        Args:
            new_key_id: ID untuk key baru, jika None akan auto-generate.
            callback: Fungsi yang menerima (old_key, new_key) untuk re-encrypt data.
        Returns:
            key_id dari key baru.
        """
        if not self._loaded:
            self._load_keys()
        old_key = self.get_current_key()
        if old_key is None:
            raise RuntimeError("No current key to rotate from")

        # Generate key baru
        new_key_bytes = secrets.token_bytes(DEFAULT_KEY_LENGTH)
        if new_key_id is None:
            new_key_id = f"key_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
        if new_key_id in self._keys:
            raise ValueError(f"Key ID '{new_key_id}' already exists")

        # Tambahkan key baru
        self.add_key(new_key_id, new_key_bytes, metadata={"rotated_from": self._current_key_id})

        # Set sebagai current
        self._current_key_id = new_key_id
        self._save_keys()

        # Panggil callback untuk re-encrypt jika disediakan
        if callback:
            try:
                callback(old_key, new_key_bytes)
            except Exception as e:
                logger.error(f"Re-encryption callback failed: {e}")
                # Rollback? Kita tetap lanjutkan, tapi log error

        logger.info(f"Key rotated to: {new_key_id}")
        return new_key_id

    def remove_key(self, key_id: str) -> None:
        """Hapus kunci (tidak boleh menghapus current key)."""
        if not self._loaded:
            self._load_keys()
        if key_id == self._current_key_id:
            raise ValueError("Cannot remove current key")
        if key_id not in self._keys:
            raise ValueError(f"Key '{key_id}' not found")
        del self._keys[key_id]
        self._save_keys()
        logger.info(f"Removed key: {key_id}")

    def reload(self) -> None:
        """Muat ulang kunci dari penyimpanan (jika ada perubahan eksternal)."""
        self._keys.clear()
        self._current_key_id = None
        self._loaded = False
        self._load_keys()
        logger.info("Keys reloaded")

    def to_dict(self) -> dict[str, Any]:
        """Kembalikan semua data keys sebagai dict (untuk debugging)."""
        if not self._loaded:
            self._load_keys()
        return self._to_dict()


# ============================================================
# Singleton Accessor
# ============================================================
_key_manager_instance: KeyManager | None = None


def get_key_manager() -> KeyManager:
    """Singleton accessor untuk KeyManager."""
    global _key_manager_instance
    if _key_manager_instance is None:
        _key_manager_instance = KeyManager()
    return _key_manager_instance


# ============================================================
# Convenience Functions
# ============================================================
def get_current_key() -> bytes | None:
    """Ambil current encryption key (bytes)."""
    return get_key_manager().get_current_key()


def get_current_key_id() -> str | None:
    """Ambil ID current encryption key."""
    return get_key_manager().get_current_key_id()


def list_keys() -> list[dict[str, Any]]:
    """Daftar semua key metadata."""
    return get_key_manager().list_keys()


def add_key(key_id: str, key_bytes: bytes, metadata: dict[str, Any] | None = None) -> None:
    """Tambahkan key baru."""
    get_key_manager().add_key(key_id, key_bytes, metadata)


def set_current_key(key_id: str) -> None:
    """Set current key."""
    get_key_manager().set_current_key(key_id)


def rotate_key(new_key_id: str | None = None, callback: Callable[[bytes, bytes], None] | None = None) -> str:
    """Rotasi key."""
    return get_key_manager().rotate_key(new_key_id, callback)


def remove_key(key_id: str) -> None:
    """Hapus key (tidak boleh current)."""
    get_key_manager().remove_key(key_id)


def reload_keys() -> None:
    """Reload keys dari penyimpanan."""
    get_key_manager().reload()


__all__ = [
    "KeyManager",
    "get_key_manager",
    "get_current_key",
    "get_current_key_id",
    "list_keys",
    "add_key",
    "set_current_key",
    "rotate_key",
    "remove_key",
    "reload_keys",
]