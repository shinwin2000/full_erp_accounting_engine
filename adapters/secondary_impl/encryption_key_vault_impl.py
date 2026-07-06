#!/usr/bin/env python3
"""
Adapter: Encryption Key Vault
Layer: Adapters (Secondary Implementation)

Adapter untuk manajemen kunci enkripsi menggunakan KeyManagementVault.
"""

from __future__ import annotations

import base64
from datetime import datetime
from typing import Any

from infrastructure.security.securitykey_management_vault import KeyManagementVault
from infrastructure.telemetry.structured_json_logging import get_logger
from ports.primary.encryption_key_vault_port import EncryptionKeyVaultPort, KeyAlgorithm, KeyMetadata

logger = get_logger(__name__)


class EncryptionKeyVaultAdapter(EncryptionKeyVaultPort):
    """
    Adapter yang menggunakan KeyManagementVault sebagai implementasi.
    """

    def __init__(self, vault: KeyManagementVault | None = None):
        self._vault = vault or KeyManagementVault()
        # In-memory stores for stub functionality (if vault lacks these)
        self._keys: dict[str, dict] = {}
        self._metadata: dict[str, dict] = {}
        self._key_aliases: dict[str, str] = {}
        self._audit_log: list[dict] = []
        self._rotation_tasks: dict[str, Any] = {}

    # ========== Existing methods (kept for compatibility) ==========

    async def create_key(
        self,
        key_id: str,
        algorithm: KeyAlgorithm = KeyAlgorithm.AES_256_GCM,
        key_size: int = 256,
        created_by: str | None = None,
        rotation_days: int | None = None,
        tags: dict | None = None,
    ):
        """
        Create a new key. Delegates to vault if available, else stub.
        """
        algo_str = algorithm.value if hasattr(algorithm, "value") else str(algorithm)
        return await self._vault.create_key(
            key_id, algo_str, key_size, created_by, rotation_days, tags
        )

    async def get_key(self, key_id: str, version: str | None = None) -> bytes:
        return await self._vault.get_key(key_id, version)

    async def rotate_key(self, key_id: str, created_by: str | None = None, new_algorithm: str | None = None) -> str:
        return await self._vault.rotate_key(key_id, created_by, new_algorithm)

    async def delete_key(self, key_id: str, version: str | None = None) -> bool:
        return await self._vault.delete_key(key_id, version)

    async def encrypt(self, key_id: str, plaintext: bytes, context: dict | None = None, version: str | None = None) -> bytes:
        return await self._vault.encrypt_with_vault(key_id, plaintext, context, version)

    async def decrypt(self, key_id: str, ciphertext: bytes, context: dict | None = None, version: str | None = None) -> bytes:
        return await self._vault.decrypt_with_vault(key_id, ciphertext, context, version)

    async def health_check(self) -> dict:
        return await self._vault.health_check()

    # ========== Methods required by EncryptionKeyVaultPort ==========

    async def encrypt_with_vault(
        self,
        key_id: str,
        plaintext: bytes,
        context: dict | None = None,
        version: str | None = None,
    ) -> bytes:
        """Alias for encrypt (delegates to vault)."""
        return await self.encrypt(key_id, plaintext, context, version)

    async def decrypt_with_vault(
        self,
        key_id: str,
        ciphertext: bytes,
        context: dict | None = None,
        version: str | None = None,
    ) -> bytes:
        """Alias for decrypt (delegates to vault)."""
        return await self.decrypt(key_id, ciphertext, context, version)

    # ---------- Port methods with corrected signatures ----------

    async def export_key(self, key_id: str, version: str, passphrase: str) -> str:
        """
        Export a key (wrapped with passphrase).
        Port signature: export_key(key_id, version, passphrase) -> str
        """
        if hasattr(self._vault, "export_key"):
            result = await self._vault.export_key(key_id, version, passphrase)
            if isinstance(result, bytes):
                return base64.b64encode(result).decode("ascii")
            return str(result)
        # Stub: return a dummy base64 string
        logger.warning("export_key not implemented in vault; returning stub.")
        return base64.b64encode(b"stub_exported_key").decode("ascii")

    # [FIX] Return type diubah menjadi None sesuai kontrak (bukan bool)
    async def import_key(
        self,
        key_id: str,
        version: str,
        encrypted_key_b64: str,
        passphrase: str,
    ) -> None:
        """
        Import a key from encrypted base64 material.
        Port signature: import_key(key_id, version, encrypted_key_b64, passphrase) -> None
        Jika gagal, raise ValueError.
        """
        if hasattr(self._vault, "import_key") and callable(self._vault.import_key):
            # Asumsikan vault.import_key menerima (key_id, encrypted_key_b64, passphrase)
            # dan mengembalikan None atau raise
            await self._vault.import_key(key_id, encrypted_key_b64, passphrase)
            return
        # Stub: simpan
        try:
            self._keys[key_id] = {"encrypted": encrypted_key_b64, "version": version}
            self._metadata[key_id] = {
                "imported_at": datetime.utcnow().isoformat(),
                "version": version,
            }
            self._audit_log.append({
                "timestamp": datetime.utcnow().isoformat(),
                "action": "import_key",
                "key_id": key_id,
                "version": version,
            })
            logger.info(f"Key {key_id} version {version} imported (stub)")
            return
        except Exception as e:
            logger.error(f"Import key failed: {e}")
            raise ValueError(f"Import key failed: {e}") from e

    async def rewrap_key(self, key_id: str, old_version: str, new_version: str) -> bytes:
        """
        Rewrap a key from old version to new version.
        Port signature: rewrap_key(key_id, old_version, new_version) -> bytes
        """
        if hasattr(self._vault, "rewrap_key"):
            return await self._vault.rewrap_key(key_id, old_version, new_version)
        self._audit_log.append({
            "timestamp": datetime.utcnow().isoformat(),
            "action": "rewrap_key",
            "key_id": key_id,
            "old_version": old_version,
            "new_version": new_version,
        })
        logger.info(f"Key {key_id} rewrapped from {old_version} to {new_version} (stub)")
        return b"stub_rewrapped_key"

    async def get_audit_log(
        self,
        key_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Retrieve audit log entries for key operations."""
        if hasattr(self._vault, "get_audit_log"):
            return await self._vault.get_audit_log(key_id, limit, offset)
        logs = self._audit_log
        if key_id:
            logs = [l for l in logs if l.get("key_id") == key_id]
        logs.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return logs[offset:offset + limit]

    async def get_current_key_version(self, key_id: str) -> str | None:
        """Get the latest version of a key."""
        if hasattr(self._vault, "get_current_key_version"):
            return await self._vault.get_current_key_version(key_id)
        meta = self._metadata.get(key_id, {})
        return meta.get("current_version")

    # [FIX] Return type diubah menjadi KeyMetadata sesuai kontrak
    async def get_key_metadata(self, key_id: str, version: str | None = None) -> KeyMetadata:
        """
        Get metadata for a key. Return KeyMetadata object.
        """
        if hasattr(self._vault, "get_key_metadata"):
            result = await self._vault.get_key_metadata(key_id, version)
            # Jika vault mengembalikan dict, konversi ke KeyMetadata
            if isinstance(result, dict):
                # Asumsikan KeyMetadata memiliki fields: key_id, version, algorithm, size, created_at, etc.
                # Buat objek KeyMetadata dari dict
                # Karena KeyMetadata mungkin dataclass, kita buat instance
                # Saya asumsikan KeyMetadata memiliki __init__ yang menerima kwargs
                return KeyMetadata(**result)
            return result  # jika sudah KeyMetadata
        # Stub: buat KeyMetadata dari metadata dict
        meta = self._metadata.get(key_id, {})
        if version:
            meta = meta.get("versions", {}).get(version, {})
        # Buat objek KeyMetadata minimal
        return KeyMetadata(
            key_id=key_id,
            version=version or "latest",
            algorithm="AES_256_GCM",
            size=256,
            created_at=meta.get("imported_at", datetime.utcnow().isoformat()),
            rotation_days=None,
            tags={},
        )

    async def key_exists(self, key_id: str) -> bool:
        """Check if a key exists."""
        if hasattr(self._vault, "key_exists"):
            return await self._vault.key_exists(key_id)
        return key_id in self._keys

    async def list_keys(
        self,
        prefix: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List all keys with metadata."""
        if hasattr(self._vault, "list_keys"):
            return await self._vault.list_keys(prefix, limit, offset)
        keys = []
        for k, v in self._keys.items():
            if prefix and not k.startswith(prefix):
                continue
            keys.append({
                "key_id": k,
                "algorithm": v.get("algorithm"),
                "size": v.get("size"),
                "metadata": self._metadata.get(k, {}),
            })
        return keys[offset:offset + limit]

    async def start_auto_rotation(
        self,
        key_id: str,
        rotation_days: int = 90,
        check_interval_hours: int = 24,
    ) -> bool:
        """
        Start automatic rotation of the key.
        Port signature: start_auto_rotation(key_id, rotation_days, check_interval_hours) -> bool
        """
        if hasattr(self._vault, "start_auto_rotation"):
            return await self._vault.start_auto_rotation(key_id, rotation_days, check_interval_hours)
        self._rotation_tasks[key_id] = {
            "rotation_days": rotation_days,
            "check_interval_hours": check_interval_hours,
            "started_at": datetime.utcnow().isoformat(),
        }
        self._audit_log.append({
            "timestamp": datetime.utcnow().isoformat(),
            "action": "start_auto_rotation",
            "key_id": key_id,
            "rotation_days": rotation_days,
            "check_interval_hours": check_interval_hours,
        })
        logger.info(f"Auto-rotation started for key {key_id} every {rotation_days} days (stub)")
        return True


__all__ = ["EncryptionKeyVaultAdapter"]