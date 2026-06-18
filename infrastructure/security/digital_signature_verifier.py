#!/usr/bin/env python3
"""
Module: digital_signature_verifier.py
Layer: Infrastructure (Security)
Responsibility: Layanan verifikasi tanda tangan digital. File ini adalah
               convenience wrapper yang menggunakan DigitalSignerRSA untuk
               memverifikasi signature. Memisahkan tanggung jawab verifikasi
               untuk kejelasan kode dan mendukung verifikasi massal.
Dependencies:
- infrastructure.security.digital_signer_rsa_pss (DigitalSignerRSA)
- base64, json, logging
- infrastructure.telemetry.structured_json_logging
Audit: Verifikasi signature dicatat untuk audit non-repudiation.
"""

from __future__ import annotations

import json
from typing import Any

# Internal dependencies
from infrastructure.security.digital_signer_rsa_pss import (
    DigitalSignerRSA,
    get_digital_signer,
)
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)


# ============================================================================
# DIGITAL SIGNATURE VERIFIER
# ============================================================================


class DigitalSignatureVerifier:
    """
    Layanan verifikasi tanda tangan digital.

    Fitur:
    - Verifikasi signature tunggal
    - Verifikasi massal (batch)
    - Verifikasi dengan multiple keys
    - Cache public keys (optional)
    - Audit logging
    """

    def __init__(self, signer: DigitalSignerRSA | None = None):
        self._signer = signer or get_digital_signer()
        self._verification_count = 0
        self._success_count = 0
        self._failure_count = 0

    def verify(self, data: str | bytes, signature_b64: str, key_id: str | None = None) -> bool:
        """
        Verify a single signature.

        Args:
            data: Original data
            signature_b64: Base64 encoded signature
            key_id: Key ID to use for verification

        Returns:
            True if signature is valid
        """
        self._verification_count += 1
        result = self._signer.verify(data, signature_b64, key_id)

        if result:
            self._success_count += 1
        else:
            self._failure_count += 1

        logger.debug(f"Signature verification {'successful' if result else 'failed'}")
        return result

    def verify_json(
        self,
        data: dict[str, Any],
        signature_b64: str,
        key_id: str | None = None,
        sort_keys: bool = True,
    ) -> bool:
        """
        Verify signature of JSON data.
        """
        json_str = json.dumps(data, sort_keys=sort_keys, default=str)
        return self.verify(json_str, signature_b64, key_id)

    def verify_batch(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Verify multiple signatures in batch.

        Args:
            items: List of dict with keys: data, signature, key_id

        Returns:
            Summary with results for each item
        """
        results = []
        for item in items:
            data = item.get("data")
            signature = item.get("signature")
            key_id = item.get("key_id")

            if isinstance(data, dict):
                is_valid = self.verify_json(data, signature, key_id)
            else:
                is_valid = self.verify(data, signature, key_id)

            results.append({"index": item.get("index"), "is_valid": is_valid, "key_id": key_id})

        return {
            "total": len(items),
            "valid_count": sum(1 for r in results if r["is_valid"]),
            "invalid_count": sum(1 for r in results if not r["is_valid"]),
            "results": results,
        }

    def verify_with_multiple_keys(
        self, data: str | bytes, signature_b64: str, key_ids: list[str]
    ) -> str | None:
        """
        Try to verify signature with multiple keys.

        Args:
            data: Original data
            signature_b64: Base64 encoded signature
            key_ids: List of key IDs to try

        Returns:
            Key ID that successfully verified, or None if none
        """
        for key_id in key_ids:
            if self.verify(data, signature_b64, key_id):
                return key_id
        return None

    def verify_with_auto_detect(
        self, data: str | bytes, signature_b64: str, known_key_ids: list[str]
    ) -> str | None:
        """
        Auto-detect which key was used to sign.
        """
        return self.verify_with_multiple_keys(data, signature_b64, known_key_ids)

    def verify_attestation(self, attestation: dict[str, Any]) -> bool:
        """
        Verify an integrity attestation.

        Attestation format:
        {
            "id": "...",
            "version": "...",
            "generated_at": "...",
            "store_root_hash": "...",
            "total_events": ...,
            "total_streams": ...,
            "signature": "..."
        }
        """
        signature = attestation.pop("signature", None)
        if not signature:
            logger.warning("Attestation has no signature")
            return False

        # Extract key_id from attestation if present
        key_id = attestation.get("key_id")

        # Remove signature-related fields before verification
        verification_data = {
            k: v for k, v in attestation.items() if k not in ["key_id", "signer_info"]
        }

        is_valid = self.verify_json(verification_data, signature, key_id)

        # Restore signature
        attestation["signature"] = signature

        return is_valid

    def get_stats(self) -> dict[str, Any]:
        """Get verification statistics."""
        return {
            "total_verifications": self._verification_count,
            "successful": self._success_count,
            "failed": self._failure_count,
            "success_rate": self._success_count / self._verification_count
            if self._verification_count > 0
            else 0,
        }

    def reset_stats(self) -> None:
        """Reset verification statistics."""
        self._verification_count = 0
        self._success_count = 0
        self._failure_count = 0
        logger.info("Verification stats reset")


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_verifier: DigitalSignatureVerifier | None = None


def get_digital_signature_verifier() -> DigitalSignatureVerifier:
    """Get singleton instance of DigitalSignatureVerifier."""
    global _verifier
    if _verifier is None:
        _verifier = DigitalSignatureVerifier()
    return _verifier


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================


def verify_signature(data: str | bytes, signature_b64: str, key_id: str | None = None) -> bool:
    """Convenience function to verify signature."""
    return get_digital_signature_verifier().verify(data, signature_b64, key_id)


def verify_json_signature(
    data: dict[str, Any], signature_b64: str, key_id: str | None = None
) -> bool:
    """Convenience function to verify JSON signature."""
    return get_digital_signature_verifier().verify_json(data, signature_b64, key_id)


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "DigitalSignatureVerifier",
    "get_digital_signature_verifier",
    "verify_json_signature",
    "verify_signature",
]
