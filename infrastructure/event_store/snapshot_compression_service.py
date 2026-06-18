#!/usr/bin/env python3
"""
Module: snapshot_compression_service.py
Layer: Infrastructure (Event Store)
Responsibility: Menyediakan layanan kompresi dan dekompresi untuk snapshot data
               menggunakan algoritma zlib (default) atau LZ4 (alternatif).
               Kompresi mengurangi ukuran penyimpanan snapshot, terutama untuk
               aggregate dengan state yang besar. Layanan ini juga mendukung
               verifikasi integritas data setelah kompresi/dekompresi.
Dependencies:
- zlib, lz4 (optional), logging
- infrastructure.telemetry.structured_json_logging
Audit: Setiap operasi kompresi/dekompresi dicatat (opsional).
       Kegagalan dekompresi akan memicu alert.
"""

from __future__ import annotations

import base64
import hashlib
import json
import zlib
from typing import Any

# Internal dependencies
from infrastructure.telemetry.structured_json_logging import get_logger

# Optional LZ4 support
try:
    import lz4.frame

    LZ4_AVAILABLE = True
except ImportError:
    LZ4_AVAILABLE = False

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_COMPRESSION_LEVEL = 6  # zlib level (1-9)
DEFAULT_ALGORITHM = "zlib"  # "zlib" or "lz4"
COMPRESSION_ALGORITHMS = ["zlib", "lz4"]

# Magic bytes for format detection
MAGIC_ZLIB = b"\x78\x9c"  # zlib default header
MAGIC_LZ4 = b"\x04\x22\x4d\x18"  # LZ4 frame magic

# ============================================================================
# EXCEPTIONS
# ============================================================================


class CompressionError(Exception):
    """Base exception untuk compression service."""

    pass


class DecompressionError(CompressionError):
    """Gagal melakukan dekompresi data."""

    pass


class UnsupportedAlgorithmError(CompressionError):
    """Algoritma kompresi tidak didukung."""

    pass


class IntegrityCheckError(CompressionError):
    """Integrity check failed (hash mismatch)."""

    pass


# ============================================================================
# COMPRESSION SERVICE
# ============================================================================


class SnapshotCompressionService:
    """
    Layanan kompresi untuk snapshot data.

    Fitur:
    - Kompresi dengan zlib (default) atau LZ4 (optional)
    - Dekompresi dengan deteksi otomatis algoritma
    - Integrity check (hash) opsional
    - Base64 encoding untuk penyimpanan di database
    """

    def __init__(self, level: int = DEFAULT_COMPRESSION_LEVEL, algorithm: str = DEFAULT_ALGORITHM):
        self.level = level
        self.algorithm = algorithm
        self._stats = {
            "compressed_bytes": 0,
            "original_bytes": 0,
            "compression_count": 0,
            "decompression_count": 0,
            "errors": 0,
        }

        if algorithm == "lz4" and not LZ4_AVAILABLE:
            logger.warning("LZ4 not available, falling back to zlib")
            self.algorithm = "zlib"

    def compress(
        self, data: bytes, algorithm: str | None = None, include_hash: bool = True
    ) -> bytes:
        """
        Compress data using specified algorithm.

        Args:
            data: Raw bytes to compress
            algorithm: Override default algorithm
            include_hash: Whether to include integrity hash

        Returns:
            Compressed bytes (with optional header)
        """
        algo = algorithm or self.algorithm

        try:
            original_size = len(data)

            if algo == "zlib":
                compressed = zlib.compress(data, self.level)
                format_header = b"Z"  # Z for zlib
            elif algo == "lz4" and LZ4_AVAILABLE:
                compressed = lz4.frame.compress(data)
                format_header = b"L"  # L for LZ4
            else:
                raise UnsupportedAlgorithmError(f"Unsupported algorithm: {algo}")

            compressed_size = len(compressed)

            # Construct final payload: [format_header][compressed_data][optional_hash]
            result = format_header + compressed

            if include_hash:
                data_hash = hashlib.sha256(data).digest()
                result += data_hash

            # Update stats
            self._stats["compressed_bytes"] += compressed_size
            self._stats["original_bytes"] += original_size
            self._stats["compression_count"] += 1

            logger.debug(
                f"Compressed {original_size} -> {compressed_size} bytes ({algo}, ratio: {compressed_size / original_size:.2f})"
            )
            return result

        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"Compression failed: {e}")
            raise CompressionError(f"Failed to compress data: {e}") from e

    def decompress(self, data: bytes, verify_hash: bool = True) -> bytes:
        """
        Decompress data, auto-detecting algorithm from header.

        Args:
            data: Compressed bytes (with header)
            verify_hash: Whether to verify integrity hash

        Returns:
            Decompressed original bytes
        """
        try:
            if len(data) < 1:
                raise DecompressionError("Empty data")

            # Detect algorithm from first byte
            format_byte = data[0:1]

            if format_byte == b"Z":
                # zlib compressed, hash may be appended
                # Need to separate hash if present
                # Format: [b'Z'][zlib_data][hash(32 bytes)]
                if len(data) > 33:  # 1 + compressed + 32 hash
                    compressed_part = data[1:-32]
                    stored_hash = data[-32:]
                else:
                    compressed_part = data[1:]
                    stored_hash = None

                decompressed = zlib.decompress(compressed_part)

                if verify_hash and stored_hash:
                    computed_hash = hashlib.sha256(decompressed).digest()
                    if computed_hash != stored_hash:
                        raise IntegrityCheckError("Hash mismatch after decompression")

            elif format_byte == b"L":
                if not LZ4_AVAILABLE:
                    raise UnsupportedAlgorithmError("LZ4 not available")
                if len(data) > 33:
                    compressed_part = data[1:-32]
                    stored_hash = data[-32:]
                else:
                    compressed_part = data[1:]
                    stored_hash = None

                decompressed = lz4.frame.decompress(compressed_part)

                if verify_hash and stored_hash:
                    computed_hash = hashlib.sha256(decompressed).digest()
                    if computed_hash != stored_hash:
                        raise IntegrityCheckError("Hash mismatch after decompression")
            else:
                # Maybe uncompressed data? Try to detect
                if data.startswith(MAGIC_ZLIB):
                    decompressed = zlib.decompress(data)
                elif LZ4_AVAILABLE and data.startswith(MAGIC_LZ4):
                    decompressed = lz4.frame.decompress(data)
                else:
                    # Assume uncompressed
                    decompressed = data

            self._stats["decompression_count"] += 1
            logger.debug(f"Decompressed to {len(decompressed)} bytes")
            return decompressed

        except (zlib.error, lz4.frame.LZ4FrameError) as e:
            self._stats["errors"] += 1
            logger.error(f"Decompression failed: {e}")
            raise DecompressionError(f"Failed to decompress: {e}") from e
        except IntegrityCheckError:
            raise
        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"Unexpected decompression error: {e}")
            raise DecompressionError(f"Decompression error: {e}") from e

    def compress_json(
        self, data: dict[str, Any], algorithm: str | None = None, include_hash: bool = True
    ) -> bytes:
        """
        Compress JSON-serializable data.
        """
        json_bytes = json.dumps(data, default=str).encode("utf-8")
        return self.compress(json_bytes, algorithm, include_hash)

    def decompress_to_json(self, data: bytes, verify_hash: bool = True) -> dict[str, Any]:
        """
        Decompress and parse to JSON.
        """
        decompressed = self.decompress(data, verify_hash)
        return json.loads(decompressed.decode("utf-8"))

    def compress_base64(self, data: bytes, algorithm: str | None = None) -> str:
        """
        Compress and encode to base64 string (for database storage).
        """
        compressed = self.compress(data, algorithm, include_hash=True)
        return base64.b64encode(compressed).decode("ascii")

    def decompress_base64(self, data_b64: str, verify_hash: bool = True) -> bytes:
        """
        Decode from base64 and decompress.
        """
        compressed = base64.b64decode(data_b64)
        return self.decompress(compressed, verify_hash)

    def compress_json_base64(self, data: dict[str, Any], algorithm: str | None = None) -> str:
        """
        Compress JSON dict to base64 string.
        """
        compressed = self.compress_json(data, algorithm, include_hash=True)
        return base64.b64encode(compressed).decode("ascii")

    def decompress_json_base64(self, data_b64: str, verify_hash: bool = True) -> dict[str, Any]:
        """
        Decode from base64 and decompress to JSON dict.
        """
        compressed = base64.b64decode(data_b64)
        return self.decompress_to_json(compressed, verify_hash)

    def get_stats(self) -> dict[str, Any]:
        """
        Get compression statistics.
        """
        ratio = (
            (self._stats["compressed_bytes"] / self._stats["original_bytes"])
            if self._stats["original_bytes"] > 0
            else 0
        )
        return {
            "compression_count": self._stats["compression_count"],
            "decompression_count": self._stats["decompression_count"],
            "original_bytes": self._stats["original_bytes"],
            "compressed_bytes": self._stats["compressed_bytes"],
            "compression_ratio": ratio,
            "space_saved_percent": (1 - ratio) * 100 if ratio else 0,
            "errors": self._stats["errors"],
            "algorithm": self.algorithm,
            "level": self.level,
            "lz4_available": LZ4_AVAILABLE,
        }

    def reset_stats(self) -> None:
        """Reset compression statistics."""
        self._stats = {
            "compressed_bytes": 0,
            "original_bytes": 0,
            "compression_count": 0,
            "decompression_count": 0,
            "errors": 0,
        }
        logger.info("Compression stats reset")


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

_default_service = SnapshotCompressionService()


def compress(data: bytes) -> bytes:
    """Convenience function to compress using default service."""
    return _default_service.compress(data)


def decompress(data: bytes) -> bytes:
    """Convenience function to decompress using default service."""
    return _default_service.decompress(data)


def compress_json(data: dict[str, Any]) -> bytes:
    """Convenience function to compress JSON."""
    return _default_service.compress_json(data)


def decompress_to_json(data: bytes) -> dict[str, Any]:
    """Convenience function to decompress to JSON."""
    return _default_service.decompress_to_json(data)


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "CompressionError",
    "DecompressionError",
    "IntegrityCheckError",
    "SnapshotCompressionService",
    "UnsupportedAlgorithmError",
    "compress",
    "compress_json",
    "decompress",
    "decompress_to_json",
]
