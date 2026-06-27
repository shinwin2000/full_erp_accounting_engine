#!/usr/bin/env python3
"""
Module: cryptographic_signer.py
Layer: 5 - Reality, Intent, Causality / Intent
Responsibility: Menandatangani intent secara kriptografis (non-repudiation).
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import threading
from typing import Any

# ============================================================================
# Lazy helper untuk menghindari AST drift (domain -> kernel)
# ============================================================================


def _get_current_user() -> str | None:
    """Lazy import kernel.context_holder.get_current_user."""
    try:
        import importlib

        mod = importlib.import_module("kernel.context_holder")
        get_current_user = mod.get_current_user
        return get_current_user()
    except Exception:
        return None


# ============================================================================
# Cryptography availability
# ============================================================================

try:
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False

logger = logging.getLogger(__name__)

if not CRYPTO_AVAILABLE:
    logger.warning(
        "cryptography library not available, using fallback signing (INSECURE FOR PRODUCTION)"
    )

SIGNATURE_ALGORITHM = "RSASSA-PSS-SHA256"
FALLBACK_SIGNATURE_PREFIX = "FALLBACK_SIG:"
DEFAULT_KEY_SIZE = 2048
DEFAULT_PUBLIC_EXPONENT = 65537


class CryptographicSigner:
    """
    Signer untuk intent kriptografis.
    Business context: Memastikan non-repudiation dan integritas intent.
    Thread-safety: Menggunakan lock untuk inisialisasi kunci.
    """

    _instance: CryptographicSigner | None = None
    _private_key: rsa.RSAPrivateKey | None = None
    _public_key_pem: str | None = None

    def __new__(cls) -> CryptographicSigner:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._lock = threading.RLock()
        self._init_keys()

    def _init_keys(self) -> None:
        """Inisialisasi kunci untuk signing (dalam produksi dari Vault/HSM)."""
        global CRYPTO_AVAILABLE

        if not CRYPTO_AVAILABLE:
            logger.warning(
                "Cryptography not available, using fallback mode. Production requires cryptography library."
            )
            return

        try:
            self._private_key = rsa.generate_private_key(
                public_exponent=DEFAULT_PUBLIC_EXPONENT,
                key_size=DEFAULT_KEY_SIZE,
                backend=default_backend(),
            )
            public_key = self._private_key.public_key()
            self._public_key_pem = public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            ).decode("utf-8")
            logger.info("Cryptographic signer initialized with key size %d", DEFAULT_KEY_SIZE)
        except Exception as e:
            logger.error("Failed to initialize cryptographic keys: %s", e)
            CRYPTO_AVAILABLE = False

    def load_private_key_from_pem(self, pem_data: str, password: bytes | None = None) -> bool:
        """Load private key dari PEM string (untuk production dengan Vault/HSM)."""
        if not CRYPTO_AVAILABLE:
            logger.error("Cannot load private key: cryptography not available")
            return False

        try:
            if password:
                private_key = serialization.load_pem_private_key(
                    pem_data.encode(),
                    password=password,
                    backend=default_backend(),
                )
            else:
                private_key = serialization.load_pem_private_key(
                    pem_data.encode(),
                    password=None,
                    backend=default_backend(),
                )

            if isinstance(private_key, rsa.RSAPrivateKey):
                with self._lock:
                    self._private_key = private_key
                    public_key = private_key.public_key()
                    self._public_key_pem = public_key.public_bytes(
                        encoding=serialization.Encoding.PEM,
                        format=serialization.PublicFormat.SubjectPublicKeyInfo,
                    ).decode("utf-8")
                logger.info("Private key loaded successfully")
                return True
            else:
                logger.error("Loaded key is not RSA private key")
                return False
        except Exception as e:
            logger.error("Failed to load private key: %s", e)
            return False

    def sign(self, content: str, user_id: str | None = None) -> str:
        """Menandatangani content dengan kunci privat."""
        if not content:
            raise ValueError("Content cannot be empty")

        if user_id is None:
            user_id = _get_current_user() or "system"

        with self._lock:
            if not CRYPTO_AVAILABLE or not self._private_key:
                content_hash = hashlib.sha3_256(content.encode()).hexdigest()
                fallback_sig = f"{FALLBACK_SIGNATURE_PREFIX}{content_hash[:32]}"
                logger.warning("Using fallback signature for user %s (crypto unavailable)", user_id)
                return fallback_sig

            try:
                signature = self._private_key.sign(
                    content.encode(),
                    padding.PSS(
                        mgf=padding.MGF1(hashes.SHA256()),
                        salt_length=padding.PSS.MAX_LENGTH,
                    ),
                    hashes.SHA256(),
                )
                encoded_sig = base64.b64encode(signature).decode("ascii")
                logger.debug("Content signed for user %s", user_id)
                return encoded_sig
            except Exception as e:
                logger.error("Failed to sign content for user %s: %s", user_id, e)
                content_hash = hashlib.sha3_256(content.encode()).hexdigest()
                return f"{FALLBACK_SIGNATURE_PREFIX}{content_hash[:32]}"

    def verify(self, content: str, signature: str, public_key_pem: str | None = None) -> bool:
        """Memverifikasi tanda tangan."""
        if not content or not signature:
            return False

        if signature.startswith(FALLBACK_SIGNATURE_PREFIX):
            expected_hash = hashlib.sha3_256(content.encode()).hexdigest()
            provided_hash = signature[len(FALLBACK_SIGNATURE_PREFIX) :]
            return expected_hash.startswith(provided_hash)

        if not CRYPTO_AVAILABLE:
            logger.warning("Cannot verify signature: cryptography not available, assuming valid")
            return True

        try:
            if public_key_pem:
                pub_key = serialization.load_pem_public_key(
                    public_key_pem.encode(),
                    backend=default_backend(),
                )
            elif self._public_key_pem:
                pub_key = serialization.load_pem_public_key(
                    self._public_key_pem.encode(),
                    backend=default_backend(),
                )
            else:
                logger.error("No public key available for verification")
                return False

            signature_bytes = base64.b64decode(signature)
            pub_key.verify(
                signature_bytes,
                content.encode(),
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH,
                ),
                hashes.SHA256(),
            )
            return True
        except Exception as e:
            logger.error("Signature verification failed: %s", e)
            return False

    def sign_intent_data(self, data: dict[str, Any], user_id: str | None = None) -> str:
        """Menandatangani data intent."""
        if not isinstance(data, dict):
            raise ValueError("data must be a dictionary")
        normalized = json.dumps(data, sort_keys=True, default=str)
        return self.sign(normalized, user_id)

    def verify_intent_data(self, data: dict[str, Any], signature: str) -> bool:
        """Memverifikasi signature data intent."""
        if not isinstance(data, dict):
            return False
        normalized = json.dumps(data, sort_keys=True, default=str)
        return self.verify(normalized, signature)

    def get_public_key(self) -> str | None:
        """Mendapatkan public key dalam format PEM."""
        with self._lock:
            return self._public_key_pem

    def is_available(self) -> bool:
        """Memeriksa apakah cryptographic signing tersedia."""
        return CRYPTO_AVAILABLE and self._private_key is not None

    def get_key_info(self) -> dict[str, Any]:
        """Mendapatkan informasi tentang kunci yang digunakan."""
        with self._lock:
            return {
                "crypto_available": CRYPTO_AVAILABLE,
                "key_loaded": self._private_key is not None,
                "public_key_available": self._public_key_pem is not None,
                "algorithm": SIGNATURE_ALGORITHM if CRYPTO_AVAILABLE else "FALLBACK_SHA3_256",
            }

    # ==================== ENTITY DASAR METHODS (untuk konsistensi) ====================
    def create(self, created_by: str) -> CryptographicSigner:
        return self

    def update(self, updated_by: str, **kwargs) -> CryptographicSigner:
        return self

    def delete(self, deleted_by: str, reason: str | None = None) -> CryptographicSigner:
        return self

    def restore(self, restored_by: str) -> CryptographicSigner:
        return self

    def activate(self, activated_by: str) -> CryptographicSigner:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> CryptographicSigner:
        return self

    def lock(self, locked_by: str, reason: str) -> CryptographicSigner:
        return self

    def unlock(self, unlocked_by: str) -> CryptographicSigner:
        return self

    def validate(self) -> dict[str, Any]:
        errors = []
        if not self.is_available():
            errors.append("Cryptographic signing not available")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return self.get_key_info()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CryptographicSigner:
        return cls()

    def clone(self) -> CryptographicSigner:
        new_signer = CryptographicSigner()
        # Keys are regenerated in new instance (no copy)
        return new_signer

    def snapshot(self) -> dict[str, Any]:
        return self.get_key_info()

    def version(self) -> int:
        return 1

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return []

    def touch(self, touched_by: str) -> CryptographicSigner:
        return self

    def reset(self) -> None:
        """Reset signer (untuk testing)."""
        global CRYPTO_AVAILABLE
        with self._lock:
            self._private_key = None
            self._public_key_pem = None
            CRYPTO_AVAILABLE = True  # Reset to True before reinitializing
            self._init_keys()
        logger.info("CryptographicSigner reset")


def get_cryptographic_signer() -> CryptographicSigner:
    """Mendapatkan instance singleton CryptographicSigner."""
    global _cryptographic_signer_instance
    if _cryptographic_signer_instance is None:
        _cryptographic_signer_instance = CryptographicSigner()
    return _cryptographic_signer_instance


_cryptographic_signer_instance: CryptographicSigner | None = None

__all__ = [
    "CRYPTO_AVAILABLE",
    "CryptographicSigner",
    "get_cryptographic_signer",
]
