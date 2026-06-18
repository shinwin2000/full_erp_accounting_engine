#!/usr/bin/env python3
"""
Module: compression_lz4.py
Layer: Infrastructure (Caching)
Responsibility: Menyediakan kompresi dan dekompresi data menggunakan algoritma
               LZ4 untuk cache. LZ4 sangat cepat (sekitar 500 MB/s) dengan
               rasio kompresi yang baik untuk data JSON/text. Digunakan untuk
               mengurangi ukuran data di Redis tanpa mengorbankan latency.
Dependencies:
- lz4.frame (optional, fallback ke zlib jika tidak tersedia)
- logging, zlib
- infrastructure.telemetry.structured_json_logging
Audit: Kompresi/dekompresi dicatat untuk monitoring performance.
       Kegagalan dekompresi memicu alert.
"""

from __future__ import annotations

import hashlib
import json
import zlib
from typing import Any

# Try to import lz4
try:
    import lz4.frame

    LZ4_AVAILABLE = True
except ImportError:
    LZ4_AVAILABLE = False

    # Create dummy for type hints
    class lz4:
        class frame:
            @staticmethod
            def compress(data):
                raise ImportError("lz4 not available")

            @staticmethod
            def decompress(data):
                raise ImportError("lz4 not available")


from infrastructure.telemetry.alert_manager_router import trigger_alert
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_COMPRESSION_LEVEL = 4  # 1-4 for lz4, 1-9 for zlib fallback
COMPRESSION_THRESHOLD = 256  # Minimum size to consider compression (bytes)

# Magic bytes for format detection
LZ4_MAGIC = b"\x04\x22\x4d\x18"  # LZ4 frame magic
ZLIB_MAGIC = b"\x78\x9c"  # zlib default header

# ============================================================================
# EXCEPTIONS
# ============================================================================


class CompressionError(Exception):
    """Base exception untuk compression."""

    pass


class DecompressionError(CompressionError):
    """Gagal melakukan dekompresi."""

    pass


class UnsupportedAlgorithmError(CompressionError):
    """Algoritma tidak didukung."""

    pass


# ============================================================================
# COMPRESSION MANAGER
# ============================================================================


class CompressionLZ4:
    """
    Kompresi data menggunakan LZ4 (fallback ke zlib jika tidak tersedia).

    Fitur:
    - Kompresi LZ4 cepat (default)
    - Fallback ke zlib jika LZ4 tidak tersedia
    - Deteksi otomatis algoritma saat dekompresi
    - Integrity check (hash) opsional
    - Statistik kompresi
    """

    def __init__(self, use_lz4: bool = True, level: int = DEFAULT_COMPRESSION_LEVEL):
        self.use_lz4 = use_lz4 and LZ4_AVAILABLE
        self.level = level
        self._stats = {
            "compressed_bytes": 0,
            "original_bytes": 0,
            "compression_count": 0,
            "decompression_count": 0,
            "errors": 0,
        }

        if self.use_lz4:
            logger.info("LZ4 compression enabled")
        else:
            if use_lz4 and not LZ4_AVAILABLE:
                logger.warning("LZ4 not available, falling back to zlib")
            self.use_lz4 = False

    def compress(self, data: bytes, include_hash: bool = False) -> bytes:
        """
        Compress data using LZ4 (or zlib fallback).

        Args:
            data: Raw bytes to compress
            include_hash: Include SHA-256 hash for integrity check

        Returns:
            Compressed bytes with algorithm header
        """
        if len(data) < COMPRESSION_THRESHOLD:
            # Don't compress small data, just add header
            return b"N" + data  # 'N' for no compression

        try:
            original_size = len(data)

            if self.use_lz4:
                # LZ4 compression
                compressed = lz4.frame.compress(data, compression_level=self.level)
                format_header = b"L"  # 'L' for LZ4
            else:
                # Fallback to zlib
                compressed = zlib.compress(data, self.level)
                format_header = b"Z"  # 'Z' for zlib

            compressed_size = len(compressed)

            # Build payload
            result = format_header + compressed

            if include_hash:
                data_hash = hashlib.sha256(data).digest()
                result += data_hash

            # Update stats
            self._stats["compressed_bytes"] += compressed_size
            self._stats["original_bytes"] += original_size
            self._stats["compression_count"] += 1

            ratio = compressed_size / original_size if original_size > 0 else 1
            logger.debug(
                f"Compressed {original_size} -> {compressed_size} bytes (ratio: {ratio:.2f})"
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
            data: Compressed bytes with header
            verify_hash: Verify integrity hash if present

        Returns:
            Decompressed original bytes
        """
        if not data:
            return b""

        try:
            # Check format header (first byte)
            if data[0:1] == b"N":
                # Not compressed
                return data[1:]

            # Extract hash if present (last 32 bytes)
            stored_hash = None
            if len(data) > 32:
                # Check if last 32 bytes look like a hash
                possible_hash = data[-32:]
                if len(possible_hash) == 32:
                    stored_hash = possible_hash
                    compressed_data = data[1:-32]
                else:
                    compressed_data = data[1:]
            else:
                compressed_data = data[1:]

            # Decompress based on format
            if data[0:1] == b"L":
                if not self.use_lz4:
                    # Try anyway, maybe it was compressed with LZ4 earlier
                    try:
                        decompressed = lz4.frame.decompress(compressed_data)
                    except Exception:
                        raise UnsupportedAlgorithmError("LZ4 decompression failed")
                else:
                    decompressed = lz4.frame.decompress(compressed_data)
            elif data[0:1] == b"Z":
                decompressed = zlib.decompress(compressed_data)
            else:
                # Try to detect by magic bytes
                if data.startswith(LZ4_MAGIC):
                    decompressed = lz4.frame.decompress(data)
                elif data.startswith(ZLIB_MAGIC):
                    decompressed = zlib.decompress(data)
                else:
                    # Assume uncompressed
                    decompressed = data

            # Verify hash if present
            if verify_hash and stored_hash:
                computed_hash = hashlib.sha256(decompressed).digest()
                if computed_hash != stored_hash:
                    logger.error("Hash mismatch during decompression")
                    # trigger_alert is assumed to be synchronous; call without await
                    trigger_alert(
                        title="Cache Decompression Hash Mismatch",
                        message="Hash verification failed during decompression",
                        severity="warning",
                        source="CompressionLZ4",
                    )
                    raise DecompressionError("Hash mismatch after decompression")

            self._stats["decompression_count"] += 1
            return decompressed

        except (lz4.frame.LZ4FrameError, zlib.error) as e:
            self._stats["errors"] += 1
            logger.error(f"Decompression failed: {e}")
            raise DecompressionError(f"Failed to decompress: {e}") from e
        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"Unexpected decompression error: {e}")
            raise DecompressionError(f"Decompression error: {e}") from e

    def compress_json(self, data: dict[str, Any], include_hash: bool = False) -> bytes:
        """
        Compress JSON-serializable data.
        """
        json_bytes = json.dumps(data, default=str).encode("utf-8")
        return self.compress(json_bytes, include_hash)

    def decompress_to_json(self, data: bytes, verify_hash: bool = True) -> dict[str, Any]:
        """
        Decompress and parse to JSON.
        """
        decompressed = self.decompress(data, verify_hash)
        return json.loads(decompressed.decode("utf-8"))

    def get_stats(self) -> dict[str, Any]:
        """
        Get compression statistics.
        """
        ratio = (
            (self._stats["compressed_bytes"] / self._stats["original_bytes"])
            if self._stats["original_bytes"] > 0
            else 1
        )
        return {
            "compression_count": self._stats["compression_count"],
            "decompression_count": self._stats["decompression_count"],
            "original_bytes": self._stats["original_bytes"],
            "compressed_bytes": self._stats["compressed_bytes"],
            "compression_ratio": ratio,
            "space_saved_percent": (1 - ratio) * 100 if ratio < 1 else 0,
            "errors": self._stats["errors"],
            "algorithm": "lz4" if self.use_lz4 else "zlib",
            "level": self.level,
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

    @property
    def is_available(self) -> bool:
        """Check if LZ4 compression is available."""
        return LZ4_AVAILABLE


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_compressor: CompressionLZ4 | None = None


def get_compressor() -> CompressionLZ4:
    """Get singleton instance of CompressionLZ4."""
    global _compressor
    if _compressor is None:
        _compressor = CompressionLZ4()
    return _compressor


def compress(data: bytes) -> bytes:
    """Convenience function to compress data."""
    return get_compressor().compress(data)


def decompress(data: bytes) -> bytes:
    """Convenience function to decompress data."""
    return get_compressor().decompress(data)


def compress_json(data: dict[str, Any]) -> bytes:
    """Convenience function to compress JSON."""
    return get_compressor().compress_json(data)


def decompress_to_json(data: bytes) -> dict[str, Any]:
    """Convenience function to decompress to JSON."""
    return get_compressor().decompress_to_json(data)


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "CompressionError",
    "CompressionLZ4",
    "DecompressionError",
    "UnsupportedAlgorithmError",
    "compress",
    "compress_json",
    "decompress",
    "decompress_to_json",
    "get_compressor",
]
