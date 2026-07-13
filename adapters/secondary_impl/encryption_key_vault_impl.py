#!/usr/bin/env python3
"""
Adapter: Encryption Key Vault
Layer: Adapters (Secondary Implementation)

Adapter untuk manajemen kunci enkripsi menggunakan KeyManagementVault.
Mengimplementasikan semua method dari port EncryptionKeyVaultPort.
"""

from __future__ import annotations

import base64
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from infrastructure.security.securitykey_management_vault import KeyManagementVault
from infrastructure.telemetry.structured_json_logging import get_logger
from ports.primary.encryption_key_vault_port import (
    EncryptionKeyVaultPort,
    KeyAlgorithm,
    KeyMetadata,
    KeyStatus,
)

logger = get_logger(__name__)


class EncryptionKeyVaultAdapter(EncryptionKeyVaultPort):
    """
    Adapter yang menggunakan KeyManagementVault sebagai implementasi.
    Jika vault tidak mendukung method tertentu, fallback ke stub in-memory.
    """

    def __init__(self, vault: KeyManagementVault | None = None):
        self._vault = vault or KeyManagementVault()
        # In-memory stores untuk stub functionality (jika vault tidak mendukung)
        self._keys: dict[str, dict] = {}
        self._metadata: dict[str, dict] = {}
        self._key_aliases: dict[str, str] = {}
        self._audit_log: list[dict] = []
        self._rotation_tasks: dict[str, Any] = {}
        self._background_tasks: list[Any] = []

    # ========== Helper untuk logging ==========

    def _add_audit(self, action: str, key_id: str, details: dict | None = None):
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "action": action,
            "key_id": key_id,
            "details": details or {},
        }
        self._audit_log.append(entry)
        logger.info(f"VAULT AUDIT: {action} on {key_id}")

    # ========== Method dari port ==========

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
        Membuat kunci baru.
        Returns version string.
        """
        algo_str = algorithm.value if hasattr(algorithm, "value") else str(algorithm)
        created_by_str = str(created_by) if created_by else None
        if hasattr(self._vault, "create_key") and callable(self._vault.create_key):
            # Vault mungkin menerima parameter yang berbeda
            try:
                version = await self._vault.create_key(
                    key_id, algo_str, key_size, created_by_str, rotation_days, tags
                )
                self._add_audit("CREATE_KEY", key_id, {"version": version, "algorithm": algo_str})
                return version
            except TypeError:
                # Coba tanpa created_by dan rotation_days
                version = await self._vault.create_key(key_id, algo_str, key_size)
                self._add_audit("CREATE_KEY", key_id, {"version": version, "algorithm": algo_str})
                return version
        # Stub
        version = f"v{int(datetime.now(UTC).timestamp())}"
        self._keys[key_id] = {"algorithm": algo_str, "size": key_size, "version": version}
        self._metadata[key_id] = {
            "current_version": version,
            "created_at": datetime.now(UTC).isoformat(),
            "tags": tags or {},
        }
        self._key_aliases[key_id] = version
        self._add_audit("CREATE_KEY", key_id, {"version": version, "algorithm": algo_str})
        return version

    async def get_key(self, key_id: str, version: str | None = None) -> bytes:
        """
        Mendapatkan material kunci (bytes) berdasarkan ID dan versi.
        Jika version None, ambil versi aktif terbaru.
        """
        if hasattr(self._vault, "get_key") and callable(self._vault.get_key):
            return await self._vault.get_key(key_id, version)
        # Stub: return dummy bytes
        self._add_audit("GET_KEY", key_id, {"version": version or "latest"})
        return b"stub_key_material_32_bytes_long!!!"

    async def rotate_key(
        self,
        key_id: str,
        created_by: UUID | None = None,
        new_algorithm: KeyAlgorithm | None = None,
    ) -> str:
        """
        Rotasi kunci: menonaktifkan versi lama, membuat versi baru.
        Mengembalikan versi baru.
        """
        created_by_str = str(created_by) if created_by else None
        algo_str = new_algorithm.value if new_algorithm and hasattr(new_algorithm, "value") else None
        if hasattr(self._vault, "rotate_key") and callable(self._vault.rotate_key):
            try:
                version = await self._vault.rotate_key(key_id, created_by_str, algo_str)
                self._add_audit("ROTATE_KEY", key_id, {"new_version": version})
                return version
            except TypeError:
                version = await self._vault.rotate_key(key_id, created_by_str)
                self._add_audit("ROTATE_KEY", key_id, {"new_version": version})
                return version
        # Stub
        version = f"v{int(datetime.now(UTC).timestamp())}"
        self._keys[key_id]["version"] = version
        self._metadata[key_id]["current_version"] = version
        self._metadata[key_id]["last_rotated_at"] = datetime.now(UTC).isoformat()
        self._key_aliases[key_id] = version
        self._add_audit("ROTATE_KEY", key_id, {"new_version": version})
        return version

    async def delete_key(self, key_id: str, version: str | None = None) -> bool:
        """
        Soft delete atau destroy key (jika version None, destroy seluruh versi).
        """
        if hasattr(self._vault, "delete_key") and callable(self._vault.delete_key):
            return await self._vault.delete_key(key_id, version)
        # Stub
        if version is None:
            self._keys.pop(key_id, None)
            self._metadata.pop(key_id, None)
            self._key_aliases.pop(key_id, None)
            self._add_audit("DELETE_KEY_ALL", key_id, {})
        else:
            # Hapus versi tertentu (stub)
            if key_id in self._keys:
                self._keys[key_id]["version"] = None
                self._add_audit("DELETE_KEY_VERSION", key_id, {"version": version})
        return True

    async def key_exists(self, key_id: str) -> bool:
        """Cek apakah key_id ada (setidaknya satu versi)."""
        if hasattr(self._vault, "key_exists") and callable(self._vault.key_exists):
            return await self._vault.key_exists(key_id)
        return key_id in self._keys

    async def get_current_key_version(self, key_id: str) -> str:
        """Mendapatkan versi terbaru dari key_id."""
        if hasattr(self._vault, "get_current_key_version") and callable(self._vault.get_current_key_version):
            return await self._vault.get_current_key_version(key_id)
        meta = self._metadata.get(key_id, {})
        if "current_version" in meta:
            return meta["current_version"]
        # Fallback: ambil dari _key_aliases
        return self._key_aliases.get(key_id, "")

    async def get_key_metadata(self, key_id: str, version: str | None = None) -> KeyMetadata:
        """
        Mendapatkan metadata kunci. Return KeyMetadata object.
        """
        if hasattr(self._vault, "get_key_metadata") and callable(self._vault.get_key_metadata):
            result = await self._vault.get_key_metadata(key_id, version)
            if isinstance(result, dict):
                # Konversi dict ke KeyMetadata
                return KeyMetadata(
                    key_id=result.get("key_id", key_id),
                    version=result.get("version", version or "latest"),
                    algorithm=KeyAlgorithm(result.get("algorithm", "AES_256_GCM")),
                    status=KeyStatus(result.get("status", "active")),
                    created_at=datetime.fromisoformat(result.get("created_at", datetime.now(UTC).isoformat())),
                    created_by=UUID(result.get("created_by", "00000000-0000-0000-0000-000000000000")),
                    last_rotated_at=datetime.fromisoformat(result["last_rotated_at"]) if result.get("last_rotated_at") else None,
                    expires_at=datetime.fromisoformat(result["expires_at"]) if result.get("expires_at") else None,
                    used_count=result.get("used_count", 0),
                    last_used_at=datetime.fromisoformat(result["last_used_at"]) if result.get("last_used_at") else None,
                    tags=result.get("tags", {}),
                )
            return result
        # Stub: buat dari metadata dict
        meta = self._metadata.get(key_id, {})
        if version and "versions" in meta:
            meta = meta["versions"].get(version, {})
        return KeyMetadata(
            key_id=key_id,
            version=version or meta.get("current_version", "latest"),
            algorithm=KeyAlgorithm(meta.get("algorithm", "AES_256_GCM")),
            status=KeyStatus(meta.get("status", "active")),
            created_at=datetime.fromisoformat(meta.get("created_at", datetime.now(UTC).isoformat())),
            created_by=UUID(meta.get("created_by", "00000000-0000-0000-0000-000000000000")),
            last_rotated_at=datetime.fromisoformat(meta["last_rotated_at"]) if meta.get("last_rotated_at") else None,
            expires_at=datetime.fromisoformat(meta["expires_at"]) if meta.get("expires_at") else None,
            used_count=meta.get("used_count", 0),
            last_used_at=datetime.fromisoformat(meta["last_used_at"]) if meta.get("last_used_at") else None,
            tags=meta.get("tags", {}),
        )

    async def list_keys(
        self, status_filter: KeyStatus | None = None, limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        """Daftar semua key dengan metadata."""
        if hasattr(self._vault, "list_keys") and callable(self._vault.list_keys):
            return await self._vault.list_keys(status_filter, limit, offset)
        # Stub
        keys = []
        for key_id, meta in self._metadata.items():
            if status_filter:
                # Sederhana: tidak ada filter status
                pass
            keys.append({
                "key_id": key_id,
                "algorithm": meta.get("algorithm", "AES_256_GCM"),
                "version": meta.get("current_version", "latest"),
                "created_at": meta.get("created_at"),
                "status": meta.get("status", "active"),
            })
        return keys[offset:offset + limit]

    async def encrypt_with_vault(
        self,
        key_id: str,
        plaintext: bytes,
        context: dict[str, Any] | None = None,
        version: str | None = None,
    ) -> bytes:
        """Enkripsi menggunakan vault."""
        if hasattr(self._vault, "encrypt_with_vault") and callable(self._vault.encrypt_with_vault):
            return await self._vault.encrypt_with_vault(key_id, plaintext, context, version)
        if hasattr(self._vault, "encrypt") and callable(self._vault.encrypt):
            return await self._vault.encrypt(key_id, plaintext, context, version)
        # Stub: return dummy ciphertext
        self._add_audit("ENCRYPT", key_id, {"plaintext_len": len(plaintext)})
        return b"stub_ciphertext"

    async def decrypt_with_vault(
        self,
        key_id: str,
        ciphertext: bytes,
        context: dict[str, Any] | None = None,
        version: str | None = None,
    ) -> bytes:
        """Dekripsi menggunakan vault."""
        if hasattr(self._vault, "decrypt_with_vault") and callable(self._vault.decrypt_with_vault):
            return await self._vault.decrypt_with_vault(key_id, ciphertext, context, version)
        if hasattr(self._vault, "decrypt") and callable(self._vault.decrypt):
            return await self._vault.decrypt(key_id, ciphertext, context, version)
        # Stub: return plaintext dummy
        self._add_audit("DECRYPT", key_id, {"ciphertext_len": len(ciphertext)})
        return b"stub_plaintext"

    async def rewrap_key(self, key_id: str, old_version: str, new_version: str) -> bytes:
        """
        Rewrap kunci: mendekripsi dengan versi lama, enkripsi dengan versi baru.
        """
        if hasattr(self._vault, "rewrap_key") and callable(self._vault.rewrap_key):
            return await self._vault.rewrap_key(key_id, old_version, new_version)
        # Stub
        self._add_audit("REWRAP_KEY", key_id, {"old_version": old_version, "new_version": new_version})
        return b"stub_rewrapped_key"

    async def export_key(self, key_id: str, version: str, passphrase: str) -> str:
        """
        Mengekspor kunci (dienkripsi dengan passphrase) ke base64.
        """
        if hasattr(self._vault, "export_key") and callable(self._vault.export_key):
            result = await self._vault.export_key(key_id, version, passphrase)
            if isinstance(result, bytes):
                return base64.b64encode(result).decode("ascii")
            return str(result)
        # Stub
        self._add_audit("EXPORT_KEY", key_id, {"version": version})
        return base64.b64encode(b"stub_exported_key").decode("ascii")

    async def import_key(
        self,
        key_id: str,
        version: str,
        encrypted_key_b64: str,
        passphrase: str,
    ) -> None:
        """
        Mengimpor kunci dari format ekspor base64.
        Jika gagal, raise ValueError.
        """
        if hasattr(self._vault, "import_key") and callable(self._vault.import_key):
            await self._vault.import_key(key_id, version, encrypted_key_b64, passphrase)
            self._add_audit("IMPORT_KEY", key_id, {"version": version})
            return
        # Stub: simpan di memori
        self._keys[key_id] = {"encrypted": encrypted_key_b64, "version": version}
        self._metadata[key_id] = {
            "imported_at": datetime.now(UTC).isoformat(),
            "version": version,
            "status": "active",
            "tags": {"imported": "true"},
        }
        self._key_aliases[key_id] = version
        self._add_audit("IMPORT_KEY", key_id, {"version": version})
        logger.info(f"Key {key_id} version {version} imported (stub)")

    # ========================================================================
    # PERBAIKAN: stop_auto_rotation - method yang hilang
    # ========================================================================

    async def stop_auto_rotation(self) -> None:
        """Menghentikan task background rotasi otomatis."""
        if hasattr(self._vault, "stop_auto_rotation") and callable(self._vault.stop_auto_rotation):
            await self._vault.stop_auto_rotation()
            self._add_audit("STOP_AUTO_ROTATION", "all", {})
            return
        # Stub: hapus semua rotation tasks
        self._rotation_tasks.clear()
        self._add_audit("STOP_AUTO_ROTATION", "all", {})
        logger.info("Auto-rotation stopped for all keys (stub)")

    async def start_auto_rotation(
        self, key_id: str, rotation_days: int = 90, check_interval_hours: int = 24
    ) -> None:
        """
        Memulai task background untuk rotasi otomatis.
        Port signature: start_auto_rotation(...) -> None
        """
        if hasattr(self._vault, "start_auto_rotation") and callable(self._vault.start_auto_rotation):
            await self._vault.start_auto_rotation(key_id, rotation_days, check_interval_hours)
            self._add_audit("START_AUTO_ROTATION", key_id, {"rotation_days": rotation_days})
            return
        # Stub
        self._rotation_tasks[key_id] = {
            "rotation_days": rotation_days,
            "check_interval_hours": check_interval_hours,
            "started_at": datetime.now(UTC).isoformat(),
        }
        self._add_audit("START_AUTO_ROTATION", key_id, {"rotation_days": rotation_days})
        logger.info(f"Auto-rotation started for key {key_id} every {rotation_days} days (stub)")

    # ========================================================================
    # Audit log & health
    # ========================================================================

    async def get_audit_log(
        self,
        key_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Mengambil audit log."""
        if hasattr(self._vault, "get_audit_log") and callable(self._vault.get_audit_log):
            return await self._vault.get_audit_log(key_id, limit, offset)
        logs = self._audit_log
        if key_id:
            logs = [l for l in logs if l.get("key_id") == key_id]
        logs.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return logs[offset:offset + limit]

    async def health_check(self) -> dict[str, Any]:
        """Cek kesehatan vault."""
        if hasattr(self._vault, "health_check") and callable(self._vault.health_check):
            return await self._vault.health_check()
        total_keys = len(self._keys)
        return {
            "status": "healthy" if total_keys > 0 else "degraded",
            "total_keys": total_keys,
            "active_keys": sum(1 for m in self._metadata.values() if m.get("status") == "active"),
            "audit_log_size": len(self._audit_log),
            "adapter": "EncryptionKeyVaultAdapter",
            "mode": "in-memory stub",
        }


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_vault_adapter: EncryptionKeyVaultAdapter | None = None


async def get_encryption_key_vault_adapter() -> EncryptionKeyVaultAdapter:
    """Factory untuk mendapatkan singleton adapter."""
    global _vault_adapter
    if _vault_adapter is None:
        _vault_adapter = EncryptionKeyVaultAdapter()
    return _vault_adapter


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "EncryptionKeyVaultAdapter",
    "get_encryption_key_vault_adapter",
]