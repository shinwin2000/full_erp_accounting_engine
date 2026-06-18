#!/usr/bin/env python3
"""
Adapter: Encryption Key Vault
Layer: Adapters (Secondary Implementation)

Adapter untuk manajemen kunci enkripsi menggunakan KeyManagementVault.
"""
from __future__ import annotations

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
        # Salin semua atribut dari vault ke adapter jika perlu
        # Untuk memudahkan, kita gunakan delegasi ke _vault
        self._keys = self._vault._keys
        self._metadata = self._vault._metadata
        self._key_aliases = self._vault._key_aliases
        self._audit_log = self._vault._audit_log
        self._lock = self._vault._lock

    async def create_key(self, key_id: str, algorithm: str, key_size: int = 256, created_by=None, rotation_days=None, tags=None):
        return await self._vault.create_key(key_id, algorithm, key_size, created_by, rotation_days, tags)

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

__all__ = ["EncryptionKeyVaultAdapter"]
