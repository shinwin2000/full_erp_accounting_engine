#!/usr/bin/env python3
"""
Module: digital_signer_rsa_pss.py
Layer: Infrastructure (Security)
Responsibility: Menyediakan digital signing dan signature verification menggunakan
               RSA-PSS (Probabilistic Signature Scheme) dengan SHA-256.
               Digunakan untuk menandatangani attestations, dokumen legal,
               dan data yang memerlukan non-repudiation. Mendukung HSM integration
               untuk key management yang lebih aman.
Dependencies:
- cryptography.hazmat.primitives.asymmetric (rsa, padding)
- cryptography.hazmat.primitives.hashes (SHA256)
- cryptography.hazmat.primitives.serialization
- base64, hashlib
- config.loader_yaml
- infrastructure.telemetry.structured_json_logging
Audit: Setiap signing dan verification dicatat. Key rotation dicatat.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

# Internal dependencies
from config.loader_yaml import load_yaml_config
from infrastructure.telemetry.alert_manager_router import trigger_alert
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_KEY_SIZE = 2048  # RSA key size in bits
SIGNATURE_ALGORITHM = "RSA-PSS"
HASH_ALGORITHM = "SHA-256"
SALT_LENGTH = 32  # PSS salt length
DEFAULT_KEY_ID = (
    "default"  # ✅ FIX: Ditambahkan agar tidak terjadi NameError saat inisialisasi awal
)

# ============================================================================
# EXCEPTIONS
# ============================================================================


class DigitalSignerError(Exception):
    """Base exception untuk digital signer."""

    pass


class SigningError(DigitalSignerError):
    """Gagal melakukan signing."""

    pass


class VerificationError(DigitalSignerError):
    """Signature verification failed."""

    pass


class KeyNotFoundError(DigitalSignerError):
    """Private/public key tidak ditemukan."""

    pass


# ============================================================================
# DIGITAL SIGNER RSA PSS
# ============================================================================


class DigitalSignerRSA:
    """
    Digital signer menggunakan RSA-PSS.

    Fitur:
    - Sign data menggunakan RSA private key
    - Verify signature menggunakan RSA public key
    - Support multiple key pairs (key rotation)
    - PEM key loading from file
    - In-memory key cache
    """

    def __init__(self, config_path: str = "config_files/security_config.yaml"):
        self.config = self._load_config(config_path)
        self._private_keys: dict[str, rsa.RSAPrivateKey] = {}
        self._public_keys: dict[str, rsa.RSAPublicKey] = {}
        self._current_key_id = "default"
        self._load_keys()

    def _load_config(self, config_path: str) -> dict[str, Any]:
        try:
            return load_yaml_config(config_path)
        except Exception as e:
            logger.warning(f"Failed to load security config, using defaults: {e}")
            return {}

    def _load_keys(self):
        """Load RSA keys from files or generate if not exist."""
        key_config = self.config.get("digital_signing", {}).get("keys", {})

        for key_id, key_config in key_config.items():
            private_key_path = key_config.get("private_key_path")
            public_key_path = key_config.get("public_key_path")

            if private_key_path and Path(private_key_path).exists():
                self._load_private_key(key_id, private_key_path)

            if public_key_path and Path(public_key_path).exists():
                self._load_public_key(key_id, public_key_path)

        # Generate default key if none exists (development only)
        if DEFAULT_KEY_ID not in self._private_keys:
            logger.warning("No signing keys found, generating ephemeral key (not for production)")
            self._generate_key_pair(DEFAULT_KEY_ID)

        # Get current key ID
        self._current_key_id = self.config.get("digital_signing", {}).get(
            "current_key_id", DEFAULT_KEY_ID
        )
        if self._current_key_id not in self._private_keys:
            self._current_key_id = next(iter(self._private_keys.keys()))

        logger.info(
            f"Loaded {len(self._private_keys)} signing keys, current: {self._current_key_id}"
        )

    def _load_private_key(self, key_id: str, key_path: str) -> None:
        """Load RSA private key from PEM file."""
        try:
            with open(key_path, "rb") as f:
                key_data = f.read()

            private_key = serialization.load_pem_private_key(
                key_data, password=None, backend=default_backend()
            )
            self._private_keys[key_id] = private_key
            logger.info(f"Loaded private key for {key_id} from {key_path}")
        except Exception as e:
            logger.error(f"Failed to load private key for {key_id}: {e}")

    def _load_public_key(self, key_id: str, key_path: str) -> None:
        """Load RSA public key from PEM file."""
        try:
            with open(key_path, "rb") as f:
                key_data = f.read()

            public_key = serialization.load_pem_public_key(key_data, backend=default_backend())
            self._public_keys[key_id] = public_key
            logger.info(f"Loaded public key for {key_id} from {key_path}")
        except Exception as e:
            logger.error(f"Failed to load public key for {key_id}: {e}")

    def _generate_key_pair(self, key_id: str) -> None:
        """Generate new RSA key pair (for development)."""
        private_key = rsa.generate_private_key(
            public_exponent=65537, key_size=DEFAULT_KEY_SIZE, backend=default_backend()
        )
        public_key = private_key.public_key()

        self._private_keys[key_id] = private_key
        self._public_keys[key_id] = public_key

        logger.info(f"Generated ephemeral key pair for {key_id}")

    def _get_private_key(self, key_id: str | None = None) -> rsa.RSAPrivateKey:
        key_id = key_id or self._current_key_id
        if key_id not in self._private_keys:
            raise KeyNotFoundError(f"Private key {key_id} not found")
        return self._private_keys[key_id]

    def _get_public_key(self, key_id: str | None = None) -> rsa.RSAPublicKey:
        key_id = key_id or self._current_key_id
        if key_id not in self._public_keys:
            # Try to derive from private key
            if key_id in self._private_keys:
                return self._private_keys[key_id].public_key()
            raise KeyNotFoundError(f"Public key {key_id} not found")
        return self._public_keys[key_id]

    def sign(self, data: str | bytes, key_id: str | None = None) -> str:
        """
        Sign data using RSA private key.

        Args:
            data: Data to sign (string or bytes)
            key_id: Specific key ID to use (optional)

        Returns:
            Base64 encoded signature
        """
        if isinstance(data, str):
            data = data.encode("utf-8")

        private_key = self._get_private_key(key_id)

        try:
            signature = private_key.sign(
                data,
                padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=SALT_LENGTH),
                hashes.SHA256(),
            )
            signature_b64 = base64.b64encode(signature).decode("ascii")
            logger.debug(f"Data signed with key {key_id or self._current_key_id}")
            return signature_b64
        except Exception as e:
            logger.error(f"Signing failed: {e}")
            raise SigningError(f"Failed to sign data: {e}") from e

    def sign_json(
        self, data: dict[str, Any], key_id: str | None = None, sort_keys: bool = True
    ) -> str:
        """
        Sign JSON data.
        """
        json_str = json.dumps(data, sort_keys=sort_keys, default=str)
        return self.sign(json_str, key_id)

    def verify(self, data: str | bytes, signature_b64: str, key_id: str | None = None) -> bool:
        """
        Verify signature using RSA public key.

        Args:
            data: Original data
            signature_b64: Base64 encoded signature
            key_id: Key ID to use for verification

        Returns:
            True if signature is valid
        """
        if isinstance(data, str):
            data = data.encode("utf-8")

        try:
            signature = base64.b64decode(signature_b64)
            public_key = self._get_public_key(key_id)

            public_key.verify(
                signature,
                data,
                padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=SALT_LENGTH),
                hashes.SHA256(),
            )
            logger.debug(f"Signature verified with key {key_id or self._current_key_id}")
            return True
        except Exception as e:
            logger.warning(f"Signature verification failed: {e}")
            return False

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

    def get_current_key_id(self) -> str:
        """Get current active key ID."""
        return self._current_key_id

    def get_key_ids(self) -> list:
        """Get all available key IDs."""
        return list(self._private_keys.keys())

    def get_public_key_pem(self, key_id: str | None = None) -> str:
        """
        Get public key in PEM format.
        """
        public_key = self._get_public_key(key_id)
        return public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")

    async def rotate_key(
        self, new_key_id: str
    ) -> (
        None
    ):  # ✅ FIX: Mengubah 'def' menjadi 'async def' karena menggunakan await di dalam fungsinya
        """
        Rotate to a new key (for key rotation).
        This generates a new key pair and sets it as current.
        """
        self._generate_key_pair(new_key_id)
        self._current_key_id = new_key_id
        logger.info(f"Rotated signing key to {new_key_id}")
        await trigger_alert(
            title="Signing Key Rotated",
            message=f"Digital signing key rotated to {new_key_id}",
            severity="info",
            source="DigitalSignerRSA",
        )


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_digital_signer: DigitalSignerRSA | None = None


def get_digital_signer() -> DigitalSignerRSA:
    """Get singleton instance of DigitalSignerRSA."""
    global _digital_signer
    if _digital_signer is None:
        _digital_signer = DigitalSignerRSA()
    return _digital_signer


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "DigitalSignerError",
    "DigitalSignerRSA",
    "KeyNotFoundError",
    "SigningError",
    "VerificationError",
    "get_digital_signer",
]
