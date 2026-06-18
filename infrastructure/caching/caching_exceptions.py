#!/usr/bin/env python3
"""
Module: caching_exceptions.py
Layer: Infrastructure (Caching)
Responsibility: Mendefinisikan semua exception yang terkait dengan caching system.
               Exception dibagi dalam kategori: connection, operation,
               serialization, compression, namespace, dan invalidation.
               Setiap exception membawa metadata untuk debugging.
Dependencies:
- none (standalone module)
Audit: Exception yang terjadi di caching layer dicatat di log.
"""

from __future__ import annotations

from typing import Any

# ============================================================================
# BASE EXCEPTION
# ============================================================================


class CachingError(Exception):
    """
    Base exception untuk semua error di caching layer.
    """

    def __init__(
        self, message: str, code: str | None = None, details: dict[str, Any] | None = None
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}


# ============================================================================
# CONNECTION EXCEPTIONS
# ============================================================================


class RedisManagerError(CachingError):
    """Error di Redis manager."""

    pass


class RedisConnectionError(RedisManagerError):
    """Gagal terhubung ke Redis server."""

    def __init__(self, message: str, host: str | None = None, port: int | None = None, **kwargs):
        super().__init__(message, code="REDIS_CONNECTION_ERROR", **kwargs)
        self.host = host
        self.port = port


class RedisOperationError(RedisManagerError):
    """Error saat operasi Redis (GET, SET, dll)."""

    def __init__(
        self, message: str, operation: str | None = None, key: str | None = None, **kwargs
    ):
        super().__init__(message, code="REDIS_OPERATION_ERROR", **kwargs)
        self.operation = operation
        self.key = key


# ============================================================================
# SERIALIZATION EXCEPTIONS
# ============================================================================


class SerializationError(CachingError):
    """Error saat serialisasi/deserialisasi data."""

    pass


class SerializationVersionError(SerializationError):
    """Versi serialisasi tidak dikenal atau tidak kompatibel."""

    def __init__(self, version: int, expected_version: int = 1, **kwargs):
        super().__init__(
            f"Unsupported serialization version: {version}. Expected: {expected_version}",
            code="SERIALIZATION_VERSION_ERROR",
            **kwargs,
        )
        self.version = version
        self.expected_version = expected_version


class SerializationTypeError(SerializationError):
    """Tipe data tidak dapat diserialisasi."""

    def __init__(self, type_name: str, **kwargs):
        super().__init__(
            f"Cannot serialize type: {type_name}", code="SERIALIZATION_TYPE_ERROR", **kwargs
        )
        self.type_name = type_name


# ============================================================================
# COMPRESSION EXCEPTIONS
# ============================================================================


class CompressionError(CachingError):
    """Base exception untuk compression."""

    pass


class DecompressionError(CompressionError):
    """Gagal melakukan dekompresi data."""

    def __init__(self, message: str, algorithm: str | None = None, **kwargs):
        super().__init__(message, code="DECOMPRESSION_ERROR", **kwargs)
        self.algorithm = algorithm


class UnsupportedAlgorithmError(CompressionError):
    """Algoritma kompresi tidak didukung."""

    def __init__(self, algorithm: str, **kwargs):
        super().__init__(
            f"Unsupported compression algorithm: {algorithm}",
            code="UNSUPPORTED_ALGORITHM",
            **kwargs,
        )
        self.algorithm = algorithm


# ============================================================================
# NAMESPACE EXCEPTIONS
# ============================================================================


class NamespaceError(CachingError):
    """Error terkait namespace isolation."""

    pass


class InvalidNamespaceError(NamespaceError):
    """Namespace tidak valid atau tidak dikenal."""

    def __init__(self, namespace: str, **kwargs):
        super().__init__(f"Invalid namespace: {namespace}", code="INVALID_NAMESPACE", **kwargs)
        self.namespace = namespace


class NamespaceMismatchError(NamespaceError):
    """Namespace tidak cocok untuk operasi yang diminta."""

    def __init__(self, expected: str, got: str, **kwargs):
        super().__init__(
            f"Namespace mismatch: expected {expected}, got {got}",
            code="NAMESPACE_MISMATCH",
            **kwargs,
        )
        self.expected = expected
        self.got = got


# ============================================================================
# CACHE OPERATION EXCEPTIONS
# ============================================================================


class CacheOperationError(CachingError):
    """Error saat operasi cache (GET, SET, DELETE)."""

    def __init__(self, message: str, operation: str, key: str | None = None, **kwargs):
        super().__init__(message, code="CACHE_OPERATION_ERROR", **kwargs)
        self.operation = operation
        self.key = key


class CacheMissError(CacheOperationError):
    """Cache miss (key tidak ditemukan)."""

    def __init__(self, key: str, **kwargs):
        super().__init__(
            f"Cache miss for key: {key}", operation="GET", key=key, code="CACHE_MISS", **kwargs
        )


class CacheExpiredError(CacheOperationError):
    """Cache entry sudah expired."""

    def __init__(self, key: str, expired_at: str | None = None, **kwargs):
        msg = f"Cache entry expired for key: {key}"
        if expired_at:
            msg += f" at {expired_at}"
        super().__init__(msg, operation="GET", key=key, code="CACHE_EXPIRED", **kwargs)
        self.expired_at = expired_at


# ============================================================================
# CACHE WARMER EXCEPTIONS
# ============================================================================


class CacheWarmerError(CachingError):
    """Error saat cache warming."""

    pass


class WarmingJobNotFoundError(CacheWarmerError):
    """Job warming tidak ditemukan."""

    def __init__(self, job_name: str, **kwargs):
        super().__init__(
            f"Warming job not found: {job_name}", code="WARMING_JOB_NOT_FOUND", **kwargs
        )
        self.job_name = job_name


class WarmingJobFailedError(CacheWarmerError):
    """Job warming gagal dieksekusi."""

    def __init__(self, job_name: str, reason: str, **kwargs):
        super().__init__(
            f"Warming job {job_name} failed: {reason}", code="WARMING_JOB_FAILED", **kwargs
        )
        self.job_name = job_name
        self.reason = reason


# ============================================================================
# CACHE INVALIDATION EXCEPTIONS
# ============================================================================


class CacheInvalidationError(CachingError):
    """Error saat invalidasi cache."""

    pass


class InvalidationPatternError(CacheInvalidationError):
    """Pattern invalidasi tidak valid."""

    def __init__(self, pattern: str, **kwargs):
        super().__init__(
            f"Invalid invalidation pattern: {pattern}", code="INVALIDATION_PATTERN_ERROR", **kwargs
        )
        self.pattern = pattern


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    # Base
    "CachingError",
    # Connection
    "RedisManagerError",
    "RedisConnectionError",
    "RedisOperationError",
    # Serialization
    "SerializationError",
    "SerializationVersionError",
    "SerializationTypeError",
    # Compression
    "CompressionError",
    "DecompressionError",
    "UnsupportedAlgorithmError",
    # Namespace
    "NamespaceError",
    "InvalidNamespaceError",
    "NamespaceMismatchError",
    # Cache operations
    "CacheOperationError",
    "CacheMissError",
    "CacheExpiredError",
    # Cache warmer
    "CacheWarmerError",
    "WarmingJobNotFoundError",
    "WarmingJobFailedError",
    # Cache invalidation
    "CacheInvalidationError",
    "InvalidationPatternError",
]
