#!/usr/bin/env python3
"""
Module: hashing_service_sha3_256.py
Layer: Infrastructure (Security)
Responsibility: Menyediakan fungsi hashing menggunakan SHA3-256 (Secure Hash Algorithm 3)
               untuk checksum data, integrity verification, dan non-cryptographic
               use cases (bukan untuk password). Password hashing menggunakan bcrypt
               terpisah (di IAM). SHA3-256 lebih aman dari SHA2 terhadap collision
               attacks.
Dependencies:
- hashlib (pyca/cryptography optional)
- base64, json, logging
- infrastructure.telemetry.structured_json_logging
Audit: Hashing digunakan untuk integrity verification, bukan untuk secret storage.
       Hash yang dihasilkan dapat diverifikasi ulang.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

# Internal dependencies
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

HASH_ALGORITHM = "sha3-256"
HASH_LENGTH_BYTES = 32  # 256 bits

# ============================================================================
# EXCEPTIONS
# ============================================================================


class HashingError(Exception):
    """Base exception untuk hashing service."""

    pass


class HashVerificationError(HashingError):
    """Hash verification failed."""

    pass


# ============================================================================
# HASHING SERVICE
# ============================================================================


class HashingServiceSHA3_256:
    """
    Layanan hashing menggunakan SHA3-256.

    Fitur:
    - Hash data (string, bytes, JSON)
    - HMAC (Hash-based Message Authentication Code)
    - Merkle tree hash untuk batch data
    - Hash verification
    - Salted hash (opsional)
    """

    def __init__(self):
        self._hash_count = 0

    def hash(self, data: str | bytes) -> str:
        """
        Compute SHA3-256 hash of data.

        Args:
            data: String or bytes to hash

        Returns:
            Hexadecimal hash string (64 characters)
        """
        if isinstance(data, str):
            data = data.encode("utf-8")

        hash_obj = hashlib.sha3_256()
        hash_obj.update(data)
        result = hash_obj.hexdigest()

        self._hash_count += 1
        return result

    def hash_json(self, data: dict[str, Any], sort_keys: bool = True) -> str:
        """
        Hash JSON-serializable data.

        Args:
            data: Dictionary to hash
            sort_keys: Sort keys for deterministic JSON

        Returns:
            Hexadecimal hash string
        """
        json_str = json.dumps(data, sort_keys=sort_keys, default=str)
        return self.hash(json_str)

    def hash_with_salt(self, data: str | bytes, salt: str | bytes) -> str:
        """
        Compute hash with salt (for additional security).

        Args:
            data: Data to hash
            salt: Salt value

        Returns:
            Hexadecimal hash string
        """
        if isinstance(data, str):
            data = data.encode("utf-8")
        if isinstance(salt, str):
            salt = salt.encode("utf-8")

        combined = salt + data
        return self.hash(combined)

    def hmac(self, key: str | bytes, message: str | bytes) -> str:
        """
        Compute HMAC-SHA3-256.

        Args:
            key: Secret key
            message: Message to authenticate

        Returns:
            Hexadecimal HMAC string
        """
        if isinstance(key, str):
            key = key.encode("utf-8")
        if isinstance(message, str):
            message = message.encode("utf-8")

        h = hmac.new(key, message, hashlib.sha3_256)
        result = h.hexdigest()

        return result

    def verify(self, data: str | bytes, expected_hash: str) -> bool:
        """
        Verify that data matches expected hash.

        Args:
            data: Data to verify
            expected_hash: Expected hash value

        Returns:
            True if hash matches, False otherwise
        """
        computed_hash = self.hash(data)
        return hmac.compare_digest(computed_hash, expected_hash)

    def verify_json(self, data: dict[str, Any], expected_hash: str) -> bool:
        """
        Verify that JSON data matches expected hash.
        """
        computed_hash = self.hash_json(data)
        return hmac.compare_digest(computed_hash, expected_hash)

    def merkle_root(self, hashes: list[str]) -> str:
        """
        Compute Merkle tree root from list of hashes.

        Args:
            hashes: List of hexadecimal hash strings

        Returns:
            Root hash of the Merkle tree
        """
        if not hashes:
            return self.hash(b"empty")

        if len(hashes) == 1:
            return hashes[0]

        # Build next level
        next_level = []
        for i in range(0, len(hashes), 2):
            if i + 1 < len(hashes):
                combined = hashes[i] + hashes[i + 1]
            else:
                combined = hashes[i] + hashes[i]  # Duplicate if odd number
            next_level.append(self.hash(combined))

        return self.merkle_root(next_level)

    def merkle_proof(self, hashes: list[str], index: int) -> dict[str, Any]:
        """
        Generate Merkle proof for a leaf at given index.

        Args:
            hashes: List of leaf hashes
            index: Index of the leaf to prove

        Returns:
            Dictionary containing proof path and root
        """
        proof = []
        current_level = hashes.copy()
        current_index = index

        while len(current_level) > 1:
            # Determine sibling
            if current_index % 2 == 0:
                sibling = (
                    current_level[current_index + 1]
                    if current_index + 1 < len(current_level)
                    else None
                )
                direction = "right"
            else:
                sibling = current_level[current_index - 1]
                direction = "left"

            if sibling:
                proof.append({"hash": sibling, "direction": direction})

            # Build next level
            next_level = []
            for i in range(0, len(current_level), 2):
                if i + 1 < len(current_level):
                    combined = current_level[i] + current_level[i + 1]
                else:
                    combined = current_level[i] + current_level[i]
                next_level.append(self.hash(combined))

            current_level = next_level
            current_index = current_index // 2

        return {
            "leaf_index": index,
            "leaf_hash": hashes[index] if index < len(hashes) else None,
            "proof": proof,
            "root": current_level[0] if current_level else None,
        }

    def verify_merkle_proof(
        self, leaf_hash: str, proof: list[dict[str, Any]], expected_root: str
    ) -> bool:
        """
        Verify a Merkle proof.

        Args:
            leaf_hash: Hash of the leaf
            proof: Merkle proof path
            expected_root: Expected root hash

        Returns:
            True if proof is valid
        """
        current_hash = leaf_hash

        for step in proof:
            sibling = step["hash"]
            direction = step["direction"]

            if direction == "left":
                combined = sibling + current_hash
            else:
                combined = current_hash + sibling

            current_hash = self.hash(combined)

        return hmac.compare_digest(current_hash, expected_root)

    def hash_file(self, file_path: str, chunk_size: int = 8192) -> str:
        """
        Compute hash of a file (chunk by chunk).

        Args:
            file_path: Path to file
            chunk_size: Size of chunks to read

        Returns:
            Hexadecimal hash string
        """
        hash_obj = hashlib.sha3_256()

        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(chunk_size), b""):
                hash_obj.update(chunk)

        return hash_obj.hexdigest()

    def hash_combine(self, hash1: str, hash2: str) -> str:
        """
        Combine two hashes (for Merkle tree construction).
        """
        combined = hash1 + hash2
        return self.hash(combined)

    def get_hash_length(self) -> int:
        """
        Get hash length in bytes.
        """
        return HASH_LENGTH_BYTES

    def get_stats(self) -> dict[str, Any]:
        """
        Get hashing statistics.
        """
        return {
            "algorithm": HASH_ALGORITHM,
            "hash_length_bytes": HASH_LENGTH_BYTES,
            "total_hashes": self._hash_count,
        }

    def reset_stats(self) -> None:
        """Reset hashing statistics."""
        self._hash_count = 0


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_hashing_service: HashingServiceSHA3_256 | None = None


def get_hashing_service() -> HashingServiceSHA3_256:
    """Get singleton instance of HashingServiceSHA3_256."""
    global _hashing_service
    if _hashing_service is None:
        _hashing_service = HashingServiceSHA3_256()
    return _hashing_service


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================


def hash_data(data: str | bytes) -> str:
    """Convenience function to hash data."""
    return get_hashing_service().hash(data)


def hash_json(data: dict[str, Any]) -> str:
    """Convenience function to hash JSON."""
    return get_hashing_service().hash_json(data)


def hmac_hash(key: str | bytes, message: str | bytes) -> str:
    """Convenience function to compute HMAC."""
    return get_hashing_service().hmac(key, message)


def verify_hash(data: str | bytes, expected_hash: str) -> bool:
    """Convenience function to verify hash."""
    return get_hashing_service().verify(data, expected_hash)


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "HashVerificationError",
    "HashingError",
    "HashingServiceSHA3_256",
    "get_hashing_service",
    "hash_data",
    "hash_json",
    "hmac_hash",
    "verify_hash",
]
