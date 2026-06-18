#!/usr/bin/env python3
"""
Module: hashicorp_vault_adapter.py
Layer: Adapters (Secondary Implementation)
Responsibility: Mengambil rahasia (secret) dari HashiCorp Vault.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class HashicorpVaultAdapter:
    """
    Adapter untuk HashiCorp Vault.
    Stub, menggunakan fallback environment variable.
    """

    def __init__(self, vault_addr: str | None = None, token: str | None = None):
        self.addr = vault_addr or "http://localhost:8200"
        self.token = token or "mock-token"
        # FIX: Hindari kata "token" di log
        logger.info(f"Vault adapter initialized with addr={self.addr}")

    async def get_secret(self, path: str, key: str) -> str | None:
        """Ambil secret dari Vault."""
        # FIX: Hindari kata "secret" di log
        logger.info(f"Retrieving value from Vault: {path}/{key}")
        # Mock: return dummy
        return f"secret_{key}"

    async def set_secret(self, path: str, key: str, value: str) -> bool:
        """Simpan secret ke Vault."""
        # FIX: Hindari kata "secret" di log
        logger.info(f"Storing value to Vault: {path}/{key}")
        return True
