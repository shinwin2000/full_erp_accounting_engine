#!/usr/bin/env python3
"""
Module: hsm_pkcs11_signing_adapter.py
Layer: Adapters (Secondary Implementation)
Responsibility: Menandatangani data menggunakan HSM via PKCS#11.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class HSMSigner:
    """
    Adapter untuk signing via HSM (PKCS#11).
    Stub, return dummy signature.
    """

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        logger.info("HSMSigner initialized (stub)")

    def sign(self, data: bytes) -> bytes:
        """Sign data."""
        logger.info(f"Signing {len(data)} bytes with HSM")
        return b"dummy_signature_from_hsm"

    def get_certificate(self) -> bytes:
        """Return dummy certificate."""
        return b"-----BEGIN CERTIFICATE-----\nDUMMY\n-----END CERTIFICATE-----"
