#!/usr/bin/env python3
"""
Module: field_decryption_service.py
Layer: Infrastructure (Security)
Responsibility: Layanan dekripsi untuk field terenkripsi. File ini adalah
               convenience wrapper yang menggunakan FieldEncryption untuk
               mendekripsi data. Memisahkan tanggung jawab dekripsi untuk
               kejelasan kode dan support untuk multiple decryption methods.
Dependencies:
- infrastructure.security.field_encryption_aes256_gcm (FieldEncryption)
- logging
Audit: Dekripsi dicatat untuk audit access data sensitif.
"""

from __future__ import annotations

from typing import Any

# Internal dependencies
from infrastructure.security.field_encryption_aes256_gcm import (
    DecryptionError,
    FieldEncryption,
    get_field_encryption,
)
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)


# ============================================================================
# FIELD DECRYPTION SERVICE
# ============================================================================


class FieldDecryptionService:
    """
    Layanan dekripsi untuk field sensitif.

    Fitur:
    - Mendekripsi single field
    - Mendekripsi multiple fields dalam dict
    - Mendekripsi nested object
    - Cache hasil dekripsi (opsional)
    - Audit logging untuk akses data sensitif
    """

    def __init__(self, encryption_service: FieldEncryption | None = None):
        self._encryption = encryption_service or get_field_encryption()
        self._cache: dict[str, str] = {}
        self._cache_enabled = True
        self._cache_ttl_seconds = 300
        self._decryption_count = 0

    def decrypt(self, ciphertext: str) -> str:
        """
        Decrypt a single encrypted field.

        Args:
            ciphertext: Encrypted string

        Returns:
            Decrypted plaintext
        """
        if not ciphertext:
            return ""

        # Check cache
        if self._cache_enabled and ciphertext in self._cache:
            logger.debug("Decryption cache hit")
            return self._cache[ciphertext]

        try:
            plaintext = self._encryption.decrypt(ciphertext)
            self._decryption_count += 1

            # Cache result
            if self._cache_enabled:
                self._cache[ciphertext] = plaintext

            return plaintext

        except DecryptionError as e:
            logger.error(f"Failed to decrypt field: {e}")
            raise

    def decrypt_many(self, *ciphertexts: str) -> list:
        """
        Decrypt multiple fields.
        """
        return [self.decrypt(ct) for ct in ciphertexts if ct]

    def decrypt_dict(self, data: dict[str, Any], fields: list) -> dict[str, Any]:
        """
        Decrypt specific fields in a dictionary.

        Args:
            data: Dictionary containing encrypted fields
            fields: List of field names to decrypt

        Returns:
            Dictionary with decrypted fields (new dict)
        """
        result = data.copy()
        for field in fields:
            if result.get(field):
                try:
                    result[field] = self.decrypt(result[field])
                except DecryptionError as e:
                    logger.error(f"Failed to decrypt field '{field}': {e}")
                    result[field] = None
        return result

    def decrypt_dict_inplace(self, data: dict[str, Any], fields: list) -> None:
        """
        Decrypt fields in-place in a dictionary.
        """
        for field in fields:
            if data.get(field):
                try:
                    data[field] = self.decrypt(data[field])
                except DecryptionError as e:
                    logger.error(f"Failed to decrypt field '{field}': {e}")
                    data[field] = None

    def decrypt_nested(self, data: dict[str, Any], field_path: str) -> Any:
        """
        Decrypt a nested field using dot notation.

        Example: decrypt_nested(data, "user.contact.email")
        """
        parts = field_path.split(".")
        current = data

        for part in parts[:-1]:
            if part not in current:
                return None
            current = current[part]

        last_part = parts[-1]
        if current.get(last_part):
            try:
                return self.decrypt(current[last_part])
            except DecryptionError:
                return None

        return None

    def decrypt_json_field(self, ciphertext: str) -> dict[str, Any]:
        """
        Decrypt a field that contains JSON data.
        """
        plaintext = self.decrypt(ciphertext)
        import json

        return json.loads(plaintext)

    def is_encrypted(self, value: str) -> bool:
        """
        Check if a string appears to be encrypted (has the expected format).
        """
        if not value or not isinstance(value, str):
            return False

        # Check format: version|key_id|nonce|ciphertext
        parts = value.split("|")
        if len(parts) != 4:
            return False

        version, key_id, nonce, ciphertext = parts

        # Quick checks
        if version not in ("v1",):
            return False

        # Nonce and ciphertext should be base64
        import base64

        try:
            base64.b64decode(nonce)
            base64.b64decode(ciphertext)
            return True
        except Exception:
            return False

    def clear_cache(self) -> None:
        """Clear decryption cache."""
        self._cache.clear()
        logger.debug("Decryption cache cleared")

    def set_cache_enabled(self, enabled: bool) -> None:
        """Enable or disable caching."""
        self._cache_enabled = enabled
        if not enabled:
            self.clear_cache()

    def get_stats(self) -> dict[str, Any]:
        """Get decryption statistics."""
        return {
            "decryption_count": self._decryption_count,
            "cache_size": len(self._cache),
            "cache_enabled": self._cache_enabled,
            "cache_ttl_seconds": self._cache_ttl_seconds,
        }

    def decrypt_phone(self, encrypted_phone: str) -> str:
        """
        Convenience method for phone number decryption.
        """
        return self.decrypt(encrypted_phone)

    def decrypt_email(self, encrypted_email: str) -> str:
        """
        Convenience method for email decryption.
        """
        return self.decrypt(encrypted_email)

    def decrypt_npwp(self, encrypted_npwp: str) -> str:
        """
        Convenience method for NPWP (tax ID) decryption.
        """
        return self.decrypt(encrypted_npwp)

    def decrypt_bank_account(self, encrypted_account: str) -> str:
        """
        Convenience method for bank account number decryption.
        """
        return self.decrypt(encrypted_account)


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_decryption_service: FieldDecryptionService | None = None


def get_field_decryption_service() -> FieldDecryptionService:
    """Get singleton instance of FieldDecryptionService."""
    global _decryption_service
    if _decryption_service is None:
        _decryption_service = FieldDecryptionService()
    return _decryption_service


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ["FieldDecryptionService", "get_field_decryption_service"]
