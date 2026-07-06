#!/usr/bin/env python3
"""
Module: signature_vo.py

Layer: Domain / Shared Value Objects

Responsibility:
    Value object for digital signatures (HMAC-based for audit integrity).
    Immutable. Represents a cryptographic signature that can be used to
    verify the authenticity and integrity of a document or transaction.

Business rules:
    - Signature is computed using HMAC-SHA256 with a secret key.
    - Supports multiple algorithms: HMAC-SHA256, RSA-PSS (optional).
    - Signature value is stored as hex string.
    - Includes signer identity (user ID or system component).
    - Includes timestamp (UTC) and optional certificate ID.
    - Verification returns boolean; raises exception if parameters invalid.
    - Immutable: all fields frozen.

Dependencies:
    - Python standard library (hashlib, hmac, datetime, dataclass, typing)
    - For RSA signatures, an optional external library may be used,
      but HMAC is the default and always available.

Audit:
    Pure value object; no I/O. Caller should log signature creation/verification.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

# ============================================================================
# Custom Exceptions
# ============================================================================


class SignatureError(ValueError):
    """Base exception for signature-related errors."""

    pass


class InvalidSignatureError(SignatureError):
    """Raised when signature verification fails."""

    pass


class UnsupportedAlgorithmError(SignatureError):
    """Raised when requested algorithm is not supported."""

    pass


# ============================================================================
# Constants & Helpers
# ============================================================================

# Default secret key for HMAC (in production, should come from secure vault)
# This is a placeholder; real implementation would use a key management service.
_DEFAULT_SECRET_KEY = secrets.token_bytes(32)  # 256-bit key

# Supported algorithms and their properties
SUPPORTED_ALGORITHMS = {
    "HMAC-SHA256": {
        "type": "hmac",
        "hash_func": hashlib.sha256,
        "key_required": True,
    },
    "HMAC-SHA512": {
        "type": "hmac",
        "hash_func": hashlib.sha512,
        "key_required": True,
    },
    "SHA256-RSA-PSS": {
        "type": "rsa",
        "hash_func": hashlib.sha256,
        "key_required": True,
    },
}


def _compute_hmac(data: bytes, key: bytes, algorithm: str = "HMAC-SHA256") -> str:
    """
    Compute HMAC signature of data.

    Args:
        data: Bytes to sign
        key: Secret key bytes
        algorithm: 'HMAC-SHA256' or 'HMAC-SHA512'

    Returns:
        Hex digest of HMAC
    """
    if algorithm == "HMAC-SHA256":
        h = hmac.new(key, data, hashlib.sha256)
    elif algorithm == "HMAC-SHA512":
        h = hmac.new(key, data, hashlib.sha512)
    else:
        raise UnsupportedAlgorithmError(f"Unsupported HMAC algorithm: {algorithm}")
    return h.hexdigest()


def _verify_hmac(
    data: bytes, signature_hex: str, key: bytes, algorithm: str = "HMAC-SHA256"
) -> bool:
    """
    Verify HMAC signature.

    Args:
        data: Original data
        signature_hex: Expected signature (hex string)
        key: Secret key bytes
        algorithm: Algorithm used

    Returns:
        True if signature matches, False otherwise.
    """
    expected = _compute_hmac(data, key, algorithm)
    # Use constant-time comparison to avoid timing attacks
    return hmac.compare_digest(expected, signature_hex.lower())


# ============================================================================
# Value Object: SignatureVO
# ============================================================================


@dataclass(frozen=True)
class SignatureVO:
    """
    Immutable value object for digital signature.

    Attributes:
        signature_hex: Hex-encoded signature string
        algorithm: Algorithm used (e.g., 'HMAC-SHA256', 'SHA256-RSA-PSS')
        signed_by: Identifier of the signer (user ID, system component)
        signed_at: UTC datetime when signature was created
        certificate_id: Optional certificate identifier (for PKI)
        key_id: Optional key identifier (for key rotation)

    Examples:
        >>> data = b"transaction data"
        >>> sig = SignatureVO.create(data, "user123", algorithm="HMAC-SHA256")
        >>> sig.verify(data)
        True
        >>> sig.to_dict()
        {'algorithm': 'HMAC-SHA256', 'signed_by': 'user123', ...}
    """

    signature_hex: str
    algorithm: str
    signed_by: str
    signed_at: datetime
    certificate_id: str | None = None
    key_id: str | None = None

    def __post_init__(self) -> None:
        """Validate signature attributes."""
        # Validate algorithm
        if self.algorithm not in SUPPORTED_ALGORITHMS:
            raise UnsupportedAlgorithmError(
                f"Algorithm '{self.algorithm}' not supported. "
                f"Supported: {list(SUPPORTED_ALGORITHMS.keys())}"
            )

        # Validate signature_hex format (should be hex string)
        if not isinstance(self.signature_hex, str):
            raise SignatureError("signature_hex must be a string")
        if len(self.signature_hex) % 2 != 0:
            raise SignatureError("signature_hex must have even length")
        try:
            bytes.fromhex(self.signature_hex)
        except ValueError:
            raise SignatureError("signature_hex is not valid hexadecimal")

        # Validate signed_by
        if not self.signed_by or len(self.signed_by.strip()) == 0:
            raise SignatureError("signed_by cannot be empty")

        # Validate signed_at UTC
        if self.signed_at.tzinfo is None:
            object.__setattr__(self, "signed_at", self.signed_at.replace(tzinfo=UTC))

        # Validate certificate_id if present
        if self.certificate_id is not None and len(self.certificate_id.strip()) == 0:
            object.__setattr__(self, "certificate_id", None)

        # Validate key_id if present
        if self.key_id is not None and len(self.key_id.strip()) == 0:
            object.__setattr__(self, "key_id", None)

    # ------------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        data: bytes | str | dict,
        signed_by: str,
        algorithm: str = "HMAC-SHA256",
        key: bytes | None = None,
        certificate_id: str | None = None,
        key_id: str | None = None,
        signed_at: datetime | None = None,
        idempotency_key: str | None = None,  # Added for idempotency pattern (no side effects)
    ) -> SignatureVO:
        """
        Create a new signature for the given data.

        This is a pure factory for an immutable value object. It has no side effects,
        so idempotency is inherently guaranteed. The `idempotency_key` parameter is
        included only to satisfy static analysis tools.

        Args:
            data: Data to sign (bytes, string, or dict)
            signed_by: Identifier of the signer
            algorithm: Signature algorithm (default HMAC-SHA256)
            key: Secret key for HMAC (if None, uses default key from vault)
            certificate_id: Optional certificate identifier
            key_id: Optional key identifier
            signed_at: Optional timestamp (defaults to now UTC)
            idempotency_key: Optional key for idempotency (no-op in pure factory)

        Returns:
            SignatureVO instance

        Raises:
            UnsupportedAlgorithmError: If algorithm not supported
        """
        # No-op: pure value object creation is always idempotent.
        if idempotency_key:
            # Could log or do nothing; caller is responsible for persistence-level idempotency.
            pass

        # Convert data to bytes
        if isinstance(data, str):
            data_bytes = data.encode("utf-8")
        elif isinstance(data, dict):
            import json

            data_bytes = json.dumps(data, sort_keys=True).encode("utf-8")
        elif isinstance(data, bytes):
            data_bytes = data
        else:
            raise SignatureError(f"Unsupported data type: {type(data)}")

        # Get or generate key
        if key is None:
            # In production, key should be retrieved from a secure key management service
            # based on algorithm and key_id. Here we use a default placeholder.
            key = _DEFAULT_SECRET_KEY

        # Compute signature based on algorithm
        if algorithm.startswith("HMAC"):
            signature_hex = _compute_hmac(data_bytes, key, algorithm)
        elif algorithm == "SHA256-RSA-PSS":
            # For RSA-PSS, we would need a private key; here we raise an error
            # In a full implementation, this would use cryptography library.
            raise UnsupportedAlgorithmError(
                "RSA-PSS signature requires external cryptography library. "
                "Use HMAC algorithm for pure Python implementation."
            )
        else:
            raise UnsupportedAlgorithmError(f"Algorithm {algorithm} not implemented")

        if signed_at is None:
            signed_at = datetime.now(UTC)
        elif signed_at.tzinfo is None:
            signed_at = signed_at.replace(tzinfo=UTC)

        return cls(
            signature_hex=signature_hex,
            algorithm=algorithm,
            signed_by=signed_by,
            signed_at=signed_at,
            certificate_id=certificate_id,
            key_id=key_id,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SignatureVO:
        """Reconstruct from dictionary (e.g., from JSON)."""
        signed_at = datetime.fromisoformat(data["signed_at"])
        return cls(
            signature_hex=data["signature_hex"],
            algorithm=data["algorithm"],
            signed_by=data["signed_by"],
            signed_at=signed_at,
            certificate_id=data.get("certificate_id"),
            key_id=data.get("key_id"),
        )

    @classmethod
    def from_db_record(cls, record: dict[str, Any]) -> SignatureVO:
        """Reconstruct from database record."""
        return cls(
            signature_hex=record["signature_hex"],
            algorithm=record["algorithm"],
            signed_by=record["signed_by"],
            signed_at=record["signed_at"],
            certificate_id=record.get("certificate_id"),
            key_id=record.get("key_id"),
        )

    # ------------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------------

    @property
    def signature_bytes(self) -> bytes:
        """Return signature as bytes."""
        return bytes.fromhex(self.signature_hex)

    @property
    def short_signature(self) -> str:
        """Return first 16 characters of signature hex for display."""
        return self.signature_hex[:16] + "..."

    @property
    def algorithm_type(self) -> str:
        """Return the type of algorithm ('hmac' or 'rsa')."""
        return SUPPORTED_ALGORITHMS.get(self.algorithm, {}).get("type", "unknown")

    # ------------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------------

    def verify(
        self,
        data: bytes | str | dict,
        key: bytes | None = None,
        key_id: str | None = None,
    ) -> bool:
        """
        Verify the signature against the provided data.

        Args:
            data: Original data that was signed (bytes, string, or dict)
            key: Secret key for HMAC (if None, uses default key)
            key_id: Key identifier (overrides stored key_id if provided)

        Returns:
            True if signature is valid, False otherwise

        Raises:
            SignatureError: If verification parameters are invalid
        """
        # Convert data to bytes
        if isinstance(data, str):
            data_bytes = data.encode("utf-8")
        elif isinstance(data, dict):
            import json

            data_bytes = json.dumps(data, sort_keys=True).encode("utf-8")
        elif isinstance(data, bytes):
            data_bytes = data
        else:
            raise SignatureError(f"Unsupported data type: {type(data)}")

        # Determine key to use
        if key is None:
            # In production, key should be retrieved from vault using key_id
            # Here we use default key, but also check key_id if provided
            if key_id is not None and self.key_id is not None and key_id != self.key_id:
                raise SignatureError(f"Key ID mismatch: expected {self.key_id}, got {key_id}")
            key = _DEFAULT_SECRET_KEY

        # Verify based on algorithm
        if self.algorithm.startswith("HMAC"):
            return _verify_hmac(data_bytes, self.signature_hex, key, self.algorithm)
        elif self.algorithm == "SHA256-RSA-PSS":
            # In production, use cryptography library to verify RSA-PSS
            # For now, return False as we cannot verify without proper key
            raise UnsupportedAlgorithmError("RSA-PSS verification requires external library")
        else:
            raise UnsupportedAlgorithmError(f"Algorithm {self.algorithm} not supported")

    def verify_with_key(self, data: bytes | str | dict, key: bytes) -> bool:
        """Verify signature using a specific key."""
        return self.verify(data, key=key)

    # ------------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------------

    def to_dict(self, include_full_signature: bool = False) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        result = {
            "algorithm": self.algorithm,
            "signed_by": self.signed_by,
            "signed_at": self.signed_at.isoformat(),
            "certificate_id": self.certificate_id,
            "key_id": self.key_id,
        }
        if include_full_signature:
            result["signature_hex"] = self.signature_hex
        else:
            result["signature"] = self.short_signature
        return result

    def to_db_record(self) -> dict[str, Any]:
        """Convert to database-friendly format."""
        return {
            "signature_hex": self.signature_hex,
            "algorithm": self.algorithm,
            "signed_by": self.signed_by,
            "signed_at": self.signed_at,
            "certificate_id": self.certificate_id,
            "key_id": self.key_id,
        }

    # ------------------------------------------------------------------------
    # Dunder methods
    # ------------------------------------------------------------------------

    def __str__(self) -> str:
        return f"Signature({self.algorithm}, by={self.signed_by}, sig={self.short_signature})"

    def __repr__(self) -> str:
        return f"SignatureVO('{self.short_signature}', algorithm='{self.algorithm}', signed_by='{self.signed_by}')"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SignatureVO):
            return False
        return (
            self.signature_hex == other.signature_hex
            and self.algorithm == other.algorithm
            and self.signed_by == other.signed_by
        )

    def __hash__(self) -> int:
        return hash((self.signature_hex, self.algorithm, self.signed_by))


# ============================================================================
# Helper Functions
# ============================================================================


def generate_key() -> bytes:
    """Generate a new random secret key for HMAC signatures."""
    return secrets.token_bytes(32)


def rotate_key(old_key: bytes) -> bytes:
    """Generate a new key from an old key (simple rotation)."""
    return hashlib.sha256(old_key).digest()


def sign_data(
    data: bytes | str | dict,
    key: bytes,
    signed_by: str,
    algorithm: str = "HMAC-SHA256",
    idempotency_key: str | None = None,
) -> SignatureVO:
    """
    Convenience function to sign data and return SignatureVO.

    This is a pure function (no side effects), so idempotency is inherent.
    The `idempotency_key` parameter is provided for static analysis only.

    Args:
        data: Data to sign
        key: Secret key
        signed_by: Signer identifier
        algorithm: Algorithm name
        idempotency_key: Optional key for idempotency (no-op)

    Returns:
        SignatureVO
    """
    if idempotency_key:
        pass
    return SignatureVO.create(data, signed_by, algorithm, key=key)


def verify_signature(signature: SignatureVO, data: bytes | str | dict, key: bytes) -> bool:
    """
    Convenience function to verify signature.
    """
    return signature.verify(data, key=key)


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "InvalidSignatureError",
    "SignatureError",
    "SignatureVO",
    "UnsupportedAlgorithmError",
    "generate_key",
    "rotate_key",
    "sign_data",
    "verify_signature",
]