#!/usr/bin/env python3
"""
Module: encryption_key_vault_port.py
Layer: Ports (Primary)
Responsibility: Implementasi in-memory yang sangat lengkap untuk key vault (HSM/Vault).
               Menyediakan manajemen kunci enkripsi, rotasi, enkripsi/dekripsi,
               audit trail, dan simulasi keamanan bank-grade.
Audit: Semua operasi kunci dicatat dengan timestamp, user, dan action.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from base64 import b64decode, b64encode
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)


class KeyStatus(Enum):
    """Status kunci enkripsi."""

    ACTIVE = "active"
    DEPRECATED = "deprecated"
    DESTROYED = "destroyed"
    PENDING_ROTATION = "pending_rotation"


class KeyAlgorithm(Enum):
    """Algoritma kunci yang didukung."""

    AES_128_GCM = "AES-128-GCM"
    AES_256_GCM = "AES-256-GCM"
    RSA_2048 = "RSA-2048"
    RSA_4096 = "RSA-4096"


@dataclass
class KeyMetadata:
    """Metadata untuk sebuah kunci enkripsi."""

    key_id: str
    version: str
    algorithm: KeyAlgorithm
    status: KeyStatus
    created_at: datetime
    created_by: UUID
    last_rotated_at: datetime | None
    expires_at: datetime | None
    used_count: int = 0
    last_used_at: datetime | None = None
    tags: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key_id": self.key_id,
            "version": self.version,
            "algorithm": self.algorithm.value,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "created_by": str(self.created_by),
            "last_rotated_at": self.last_rotated_at.isoformat() if self.last_rotated_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "used_count": self.used_count,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "tags": self.tags,
        }


class EncryptionKeyVaultPort:
    """
    Implementasi in-memory key vault dengan AES-256-GCM.
    Mendukung rotasi kunci, audit log, dan keamanan tingkat bank.
    """

    def __init__(self, master_key_salt: bytes | None = None):
        self._keys: dict[str, bytes] = {}  # key_id_version -> material
        self._metadata: dict[str, KeyMetadata] = {}  # key_id_version -> metadata
        self._key_aliases: dict[str, str] = {}  # alias -> latest key_id_version
        self._audit_log: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self._master_salt = master_key_salt or os.urandom(32)
        self._rotation_job_active = False

        # Inisialisasi default master key (untuk testing/development)
        self._init_default_keys()

    def _init_default_keys(self):
        """Membuat key default untuk development."""
        # Since we are in synchronous __init__, we cannot run async code directly.
        # We'll schedule it later if event loop is running, or use asyncio.run if needed.
        # For simplicity, we'll create a task if loop exists.
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._create_default_keys())
        except RuntimeError:
            # No running loop, we'll create them synchronously? Actually we can't.
            # We'll just log and let the application call create_key later if needed.
            logger.warning(
                "No async loop running, default keys not created automatically. Call create_key() manually."
            )
        except Exception as e:
            logger.warning(f"Could not create default keys: {e}")

    async def _create_default_keys(self):
        """Create default keys asynchronously."""
        try:
            await self.create_key(
                "master",
                KeyAlgorithm.AES_256_GCM,
                created_by=UUID(int=0),
                tags={"purpose": "master"},
            )
            await self.create_key(
                "data_encryption",
                KeyAlgorithm.AES_256_GCM,
                created_by=UUID(int=0),
                tags={"purpose": "data"},
            )
            await self.create_key(
                "audit_signing",
                KeyAlgorithm.AES_256_GCM,
                created_by=UUID(int=0),
                tags={"purpose": "audit"},
            )
            logger.info("Default keys created successfully.")
        except Exception as e:
            logger.warning(f"Could not create default keys: {e}")

    async def _log_audit(self, action: str, key_id: str, user_id: UUID, details: dict[str, Any]):
        """Mencatat aksi ke audit log."""
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "action": action,
            "key_id": key_id,
            "user_id": str(user_id),
            "details": details,
        }
        self._audit_log.append(entry)
        logger.info(f"VAULT AUDIT: {action} on {key_id} by {user_id}")

    async def create_key(
        self,
        key_id: str,
        algorithm: KeyAlgorithm = KeyAlgorithm.AES_256_GCM,
        key_size: int = 256,
        created_by: UUID | None = None,
        rotation_days: int | None = None,
        tags: dict[str, str] | None = None,
    ) -> str:
        """
        Membuat kunci baru dengan algoritma tertentu.
        Returns version string.
        """
        if created_by is None:
            created_by = UUID(int=0)

        async with self._lock:
            # Generate key material
            if algorithm in (KeyAlgorithm.AES_128_GCM, KeyAlgorithm.AES_256_GCM):
                key_bytes = os.urandom(key_size // 8)
            else:
                raise ValueError(f"Algorithm {algorithm} not supported in this implementation")

            version = f"v{int(time.time())}"
            key_full_id = f"{key_id}:{version}"
            self._keys[key_full_id] = key_bytes

            # Tentukan expiry (default 1 tahun)
            expires_at = None
            if rotation_days:
                expires_at = datetime.now(UTC) + timedelta(days=rotation_days)

            metadata = KeyMetadata(
                key_id=key_id,
                version=version,
                algorithm=algorithm,
                status=KeyStatus.ACTIVE,
                created_at=datetime.now(UTC),
                created_by=created_by,
                last_rotated_at=None,
                expires_at=expires_at,
                tags=tags or {},
            )
            self._metadata[key_full_id] = metadata

            # Update alias ke versi terbaru
            self._key_aliases[key_id] = key_full_id

            await self._log_audit(
                "CREATE_KEY", key_id, created_by, {"version": version, "algorithm": algorithm.value}
            )

            return version

    async def get_key(self, key_id: str, version: str | None = None) -> bytes:
        """
        Mendapatkan material kunci (bytes) berdasarkan ID dan versi.
        Jika version None, ambil versi aktif terbaru.
        """
        async with self._lock:
            if version is None:
                full_id = self._key_aliases.get(key_id)
                if not full_id:
                    raise ValueError(f"Key {key_id} not found")
            else:
                full_id = f"{key_id}:{version}"

            key_material = self._keys.get(full_id)
            if not key_material:
                raise ValueError(f"Key material for {full_id} not found")

            # Update metadata usage
            metadata = self._metadata.get(full_id)
            if metadata:
                metadata.used_count += 1
                metadata.last_used_at = datetime.now(UTC)

            await self._log_audit("GET_KEY", key_id, UUID(int=0), {"version": version or "latest"})
            return key_material

    async def rotate_key(
        self, key_id: str, created_by: UUID | None = None, new_algorithm: KeyAlgorithm | None = None
    ) -> str:
        """
        Rotasi kunci: menonaktifkan versi lama, membuat versi baru.
        Mengembalikan versi baru.
        """
        if created_by is None:
            created_by = UUID(int=0)

        async with self._lock:
            old_full = self._key_aliases.get(key_id)
            if not old_full:
                raise ValueError(f"Key {key_id} not found")

            old_meta = self._metadata.get(old_full)
            if old_meta:
                old_meta.status = KeyStatus.DEPRECATED
                old_meta.last_rotated_at = datetime.now(UTC)

            # Buat versi baru
            algorithm = new_algorithm or (
                old_meta.algorithm if old_meta else KeyAlgorithm.AES_256_GCM
            )
            version = await self.create_key(
                key_id, algorithm, created_by=created_by, tags=old_meta.tags if old_meta else {}
            )
            await self._log_audit(
                "ROTATE_KEY",
                key_id,
                created_by,
                {"old_version": old_full.split(":")[-1], "new_version": version},
            )
            return version

    async def delete_key(self, key_id: str, version: str | None = None) -> bool:
        """Soft delete atau destroy key (jika version None, destroy seluruh versi)."""
        async with self._lock:
            if version is None:
                # Hapus semua versi dari key_id
                to_delete = [k for k in self._keys.keys() if k.startswith(f"{key_id}:")]
                for full in to_delete:
                    del self._keys[full]
                    if full in self._metadata:
                        self._metadata[full].status = KeyStatus.DESTROYED
                if key_id in self._key_aliases:
                    del self._key_aliases[key_id]
                await self._log_audit(
                    "DELETE_KEY_ALL", key_id, UUID(int=0), {"versions_deleted": len(to_delete)}
                )
                return True
            else:
                full = f"{key_id}:{version}"
                if full not in self._keys:
                    return False
                del self._keys[full]
                if full in self._metadata:
                    self._metadata[full].status = KeyStatus.DESTROYED
                if self._key_aliases.get(key_id) == full:
                    # Jika menghapus versi aktif, pilih versi lain sebagai aktif
                    remaining = [k for k in self._keys.keys() if k.startswith(f"{key_id}:")]
                    if remaining:
                        latest = sorted(
                            remaining,
                            key=lambda x: (
                                self._metadata[x].created_at
                                if x in self._metadata
                                else datetime.min
                            ),
                        )[-1]
                        self._key_aliases[key_id] = latest
                    else:
                        del self._key_aliases[key_id]
                await self._log_audit(
                    "DELETE_KEY_VERSION", key_id, UUID(int=0), {"version": version}
                )
                return True

    async def key_exists(self, key_id: str) -> bool:
        """Cek apakah key_id ada (setidaknya satu versi)."""
        return key_id in self._key_aliases

    async def get_current_key_version(self, key_id: str) -> str:
        """Mendapatkan versi terbaru dari key_id."""
        full = self._key_aliases.get(key_id)
        if not full:
            raise ValueError(f"Key {key_id} not found")
        return full.split(":")[-1]

    async def get_key_metadata(self, key_id: str, version: str | None = None) -> KeyMetadata:
        """Mendapatkan metadata kunci."""
        if version is None:
            full = self._key_aliases.get(key_id)
        else:
            full = f"{key_id}:{version}"
        if not full or full not in self._metadata:
            raise ValueError(f"Key metadata for {key_id}:{version} not found")
        return self._metadata[full]

    async def list_keys(self, status_filter: KeyStatus | None = None) -> list[dict[str, Any]]:
        """Daftar semua key dengan metadata."""
        result = []
        processed_keys = set()
        for full, meta in self._metadata.items():
            key_id = full.split(":")[0]
            if key_id in processed_keys:
                continue
            processed_keys.add(key_id)
            if status_filter and meta.status != status_filter:
                continue
            result.append(meta.to_dict())
        return result

    async def encrypt_with_vault(
        self,
        key_id: str,
        plaintext: bytes,
        context: dict[str, Any] | None = None,
        version: str | None = None,
    ) -> bytes:
        """
        Enkripsi menggunakan AES-256-GCM.
        Menghasilkan ciphertext dengan format: nonce (12 byte) + ciphertext + tag (16 byte).
        Context digunakan sebagai additional authenticated data (AAD).
        """
        key_material = await self.get_key(key_id, version)
        if len(key_material) not in (16, 24, 32):
            raise ValueError("Key material length must be 16, 24, or 32 bytes for AES")

        nonce = os.urandom(12)
        aesgcm = AESGCM(key_material)

        aad = None
        if context:
            aad = json.dumps(context, sort_keys=True).encode("utf-8")

        ciphertext = aesgcm.encrypt(nonce, plaintext, aad)
        # Format: nonce (12) + ciphertext
        result = nonce + ciphertext
        await self._log_audit(
            "ENCRYPT",
            key_id,
            UUID(int=0),
            {"plaintext_len": len(plaintext), "ciphertext_len": len(result)},
        )
        return result

    async def decrypt_with_vault(
        self,
        key_id: str,
        ciphertext: bytes,
        context: dict[str, Any] | None = None,
        version: str | None = None,
    ) -> bytes:
        """
        Dekripsi menggunakan AES-256-GCM.
        ciphertext: nonce (12 byte) + ciphertext+tag.
        """
        if len(ciphertext) < 12:
            raise ValueError("Ciphertext too short")

        key_material = await self.get_key(key_id, version)
        nonce = ciphertext[:12]
        encrypted_data = ciphertext[12:]

        aesgcm = AESGCM(key_material)
        aad = None
        if context:
            aad = json.dumps(context, sort_keys=True).encode("utf-8")

        try:
            plaintext = aesgcm.decrypt(nonce, encrypted_data, aad)
            await self._log_audit("DECRYPT", key_id, UUID(int=0), {"plaintext_len": len(plaintext)})
            return plaintext
        except InvalidTag:
            logger.error(f"Decryption failed for key {key_id}: invalid tag")
            raise ValueError("Decryption failed: integrity check failed")

    async def rewrap_key(self, key_id: str, old_version: str, new_version: str) -> bytes:
        """
        Rewrap kunci: mendekripsi dengan versi lama, enkripsi dengan versi baru.
        Digunakan untuk rotasi kunci tanpa mengekspos plaintext.
        """
        old_key = await self.get_key(key_id, old_version)
        new_key = await self.get_key(key_id, new_version)
        # Simulasi rewrap: enkripsi old_key dengan new_key
        nonce = os.urandom(12)
        aesgcm = AESGCM(new_key)
        wrapped = aesgcm.encrypt(nonce, old_key, None)
        return nonce + wrapped

    async def start_auto_rotation(
        self, key_id: str, rotation_days: int = 90, check_interval_hours: int = 24
    ):
        """Memulai task background untuk rotasi otomatis."""
        if self._rotation_job_active:
            logger.warning("Auto rotation already running")
            return

        async def _rotation_loop():
            while True:
                await asyncio.sleep(check_interval_hours * 3600)
                try:
                    meta = await self.get_key_metadata(key_id)
                    if meta.expires_at and meta.expires_at <= datetime.now(UTC):
                        await self.rotate_key(key_id, created_by=UUID(int=0))
                        logger.info(f"Auto-rotated key {key_id}")
                except Exception as e:
                    logger.error(f"Auto-rotation error: {e}")

        self._rotation_job_active = True
        asyncio.create_task(_rotation_loop())

    async def export_key(self, key_id: str, version: str, passphrase: str) -> str:
        """
        Mengekspor kunci (dienkripsi dengan passphrase) ke format base64.
        Hanya untuk backup; sangat hati-hati.
        """
        key_material = await self.get_key(key_id, version)
        # Derive key dari passphrase using PBKDF2HMAC
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=self._master_salt,
            iterations=100000,
        )
        kek = kdf.derive(passphrase.encode())
        aesgcm = AESGCM(kek)
        nonce = os.urandom(12)
        encrypted = aesgcm.encrypt(nonce, key_material, None)
        export_data = nonce + encrypted
        return b64encode(export_data).decode("ascii")

    async def import_key(
        self, key_id: str, version: str, encrypted_key_b64: str, passphrase: str
    ) -> None:
        """Mengimpor kunci dari format ekspor."""
        encrypted_data = b64decode(encrypted_key_b64)
        if len(encrypted_data) < 12:
            raise ValueError("Invalid encrypted key data")
        nonce = encrypted_data[:12]
        ciphertext = encrypted_data[12:]

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=self._master_salt,
            iterations=100000,
        )
        kek = kdf.derive(passphrase.encode())
        aesgcm = AESGCM(kek)
        try:
            key_material = aesgcm.decrypt(nonce, ciphertext, None)
        except InvalidTag:
            raise ValueError("Decryption failed: wrong passphrase or corrupted data")

        full_id = f"{key_id}:{version}"
        async with self._lock:
            self._keys[full_id] = key_material
            self._metadata[full_id] = KeyMetadata(
                key_id=key_id,
                version=version,
                algorithm=KeyAlgorithm.AES_256_GCM,
                status=KeyStatus.ACTIVE,
                created_at=datetime.now(UTC),
                created_by=UUID(int=0),
                last_rotated_at=None,
                expires_at=None,
                tags={"imported": "true"},
            )
            # Update alias jika versi lebih baru
            current = self._key_aliases.get(key_id)
            if (
                not current
                or self._metadata[current].created_at < self._metadata[full_id].created_at
            ):
                self._key_aliases[key_id] = full_id
        await self._log_audit("IMPORT_KEY", key_id, UUID(int=0), {"version": version})

    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """Mengambil audit log."""
        return self._audit_log[offset : offset + limit]

    async def health_check(self) -> dict[str, Any]:
        """Cek kesehatan vault."""
        total_keys = len(self._keys)
        active_keys = sum(1 for m in self._metadata.values() if m.status == KeyStatus.ACTIVE)
        return {
            "status": "healthy" if total_keys > 0 else "degraded",
            "total_keys": total_keys,
            "active_keys": active_keys,
            "audit_log_size": len(self._audit_log),
            "master_salt_length": len(self._master_salt),
        }
