#!/usr/bin/env python3
"""
Adapter: Encryption Key Vault
Layer: Adapters (Secondary Implementation)

Adapter untuk manajemen kunci enkripsi menggunakan KeyManagementVault.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from infrastructure.security.securitykey_management_vault import KeyManagementVault
from infrastructure.telemetry.structured_json_logging import get_logger
from ports.primary.encryption_key_vault_port import EncryptionKeyVaultPort

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

    # ========== Existing methods ==========

    async def create_key(
        self,
        key_id: str,
        algorithm: str,
        key_size: int = 256,
        created_by=None,
        rotation_days=None,
        tags=None,
    ):
        return await self._vault.create_key(
            key_id, algorithm, key_size, created_by, rotation_days, tags
        )

    async def get_key(self, key_id: str, version: str | None = None) -> bytes:
        return await self._vault.get_key(key_id, version)

    async def rotate_key(self, key_id: str, created_by=None, new_algorithm=None) -> str:
        return await self._vault.rotate_key(key_id, created_by, new_algorithm)

    async def delete_key(self, key_id: str, version: str | None = None) -> bool:
        return await self._vault.delete_key(key_id, version)

    async def encrypt(self, key_id: str, plaintext: bytes, context=None, version=None) -> bytes:
        return await self._vault.encrypt_with_vault(key_id, plaintext, context, version)

    async def decrypt(self, key_id: str, ciphertext: bytes, context=None, version=None) -> bytes:
        return await self._vault.decrypt_with_vault(key_id, ciphertext, context, version)

    async def health_check(self) -> dict:
        return await self._vault.health_check()

    # ========== New methods required by EncryptionKeyVaultPort ==========

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

    async def export_key(
        self,
        key_id: str,
        version: str | None = None,
        wrapping_key_id: str | None = None,
    ) -> bytes:
        """Export a key (wrapped if wrapping_key_id provided)."""
        # If vault supports export, delegate; else stub.
        if hasattr(self._vault, "export_key"):
            return await self._vault.export_key(key_id, version, wrapping_key_id)
        logger.warning("export_key not implemented in vault; returning stub.")
        return b"stub_exported_key"

    async def get_audit_log(
        self,
        key_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Retrieve audit log entries for key operations."""
        # Use in-memory log or delegate if vault has method.
        if hasattr(self._vault, "get_audit_log"):
            return await self._vault.get_audit_log(key_id, limit, offset)
        # Stub: return from internal log
        logs = self._audit_log
        if key_id:
            logs = [l for l in logs if l.get("key_id") == key_id]
        logs.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return logs[offset:offset + limit]

    async def get_current_key_version(self, key_id: str) -> str | None:
        """Get the latest version of a key."""
        if hasattr(self._vault, "get_current_key_version"):
            return await self._vault.get_current_key_version(key_id)
        # Stub: use local metadata
        meta = self._metadata.get(key_id, {})
        return meta.get("current_version")

    async def get_key_metadata(self, key_id: str, version: str | None = None) -> dict[str, Any]:
        """Get metadata for a key."""
        if hasattr(self._vault, "get_key_metadata"):
            return await self._vault.get_key_metadata(key_id, version)
        # Stub: return local metadata
        meta = self._metadata.get(key_id, {})
        if version:
            return meta.get("versions", {}).get(version, {})
        return meta

    async def import_key(
        self,
        key_id: str,
        key_material: bytes,
        algorithm: str,
        key_size: int = 256,
        metadata: dict | None = None,
    ) -> bool:
        """Import a key from raw material."""
        if hasattr(self._vault, "import_key"):
            return await self._vault.import_key(key_id, key_material, algorithm, key_size, metadata)
        # Stub: store locally
        self._keys[key_id] = {"material": key_material, "algorithm": algorithm, "size": key_size}
        self._metadata[key_id] = metadata or {}
        self._metadata[key_id]["imported_at"] = datetime.utcnow().isoformat()
        self._audit_log.append({
            "timestamp": datetime.utcnow().isoformat(),
            "action": "import_key",
            "key_id": key_id,
        })
        logger.info(f"Key {key_id} imported (stub)")
        return True

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
        # Stub: list from local store
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

    async def rewrap_key(
        self,
        key_id: str,
        new_wrapping_key_id: str,
        version: str | None = None,
    ) -> bool:
        """Rewrap a key with a new wrapping key."""
        if hasattr(self._vault, "rewrap_key"):
            return await self._vault.rewrap_key(key_id, new_wrapping_key_id, version)
        # Stub: log and return success
        self._audit_log.append({
            "timestamp": datetime.utcnow().isoformat(),
            "action": "rewrap_key",
            "key_id": key_id,
            "new_wrapping_key": new_wrapping_key_id,
        })
        logger.info(f"Key {key_id} rewrapped with {new_wrapping_key_id} (stub)")
        return True

    async def start_auto_rotation(
        self,
        key_id: str,
        interval_days: int,
        created_by: str | None = None,
    ) -> bool:
        """Start automatic rotation of the key at the given interval."""
        if hasattr(self._vault, "start_auto_rotation"):
            return await self._vault.start_auto_rotation(key_id, interval_days, created_by)
        # Stub: simulate starting a rotation task
        self._rotation_tasks[key_id] = {
            "interval_days": interval_days,
            "started_at": datetime.utcnow().isoformat(),
            "created_by": created_by,
        }
        self._audit_log.append({
            "timestamp": datetime.utcnow().isoformat(),
            "action": "start_auto_rotation",
            "key_id": key_id,
            "interval_days": interval_days,
        })
        logger.info(f"Auto-rotation started for key {key_id} every {interval_days} days (stub)")
        return True


__all__ = ["EncryptionKeyVaultAdapter"]
