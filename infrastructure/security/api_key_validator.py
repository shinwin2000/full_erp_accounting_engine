#!/usr/bin/env python3
"""
Module: api_key_validator.py
Layer: Infrastructure / Security
Responsibility: Validasi API key untuk otentikasi CLI dan service-to-service.
"""

from __future__ import annotations

import logging
import os
from uuid import UUID

logger = logging.getLogger(__name__)


class APIKeyValidator:
    """
    Validator untuk API key.
    Untuk development, API key disimpan di environment variable atau file konfigurasi.
    Di production, bisa menggunakan database atau Vault.
    """

    def __init__(self):
        # Load valid API keys dari environment variable (contoh: ERP_API_KEYS="key1=user1,key2=user2")
        self._valid_keys: dict[str, UUID] = {}
        self._load_keys_from_env()

    def _load_keys_from_env(self) -> None:
        """Load API keys dari environment variable ERP_API_KEYS."""
        keys_str = os.environ.get("ERP_API_KEYS", "")
        if not keys_str:
            # Default key untuk development (jangan digunakan di production!)
            logger.warning("No API credentials configured, using development fallback")
            self._valid_keys["erp-dev-key-12345"] = UUID("00000000-0000-0000-0000-000000000001")
            return
        for pair in keys_str.split(","):
            if "=" not in pair:
                continue
            key, user_id_str = pair.split("=", 1)
            try:
                user_id = UUID(user_id_str)
                self._valid_keys[key] = user_id
            except ValueError:
                logger.error("Invalid user identifier for credential: %s", key[:8])

    async def validate_and_get_user(self, api_key: str) -> UUID:
        """
        Validasi API key dan kembalikan user_id yang terkait.
        Raises: ValueError jika key tidak valid.
        """
        if api_key in self._valid_keys:
            logger.info("API validation successful")
            return self._valid_keys[api_key]
        else:
            logger.warning("Invalid API credential")
            raise ValueError("Invalid API key")
