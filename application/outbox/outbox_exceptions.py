# outbox_exceptions.py - Hardened version with complete implementation

#!/usr/bin/env python3

"""
Module: outbox_exceptions.py

Layer: 8 - Application / Events / Outbox

Responsibility:
    Custom exceptions untuk transactional outbox pattern.
    Mendefinisikan hierarki exception yang digunakan oleh outbox_relay_service
    dan outbox_poller.
"""

from __future__ import annotations

# === 1. BASE EXCEPTIONS ===


class OutboxError(Exception):
    """Base exception untuk semua error yang terkait dengan outbox pattern."""

    pass


class OutboxConfigurationError(OutboxError):
    """Error konfigurasi outbox (missing required parameters, invalid settings)."""

    pass


# === 2. STORAGE ERRORS ===


class OutboxStorageError(OutboxError):
    """Error saat menyimpan atau membaca dari outbox table."""

    pass


class OutboxInsertError(OutboxStorageError):
    """Gagal insert record ke outbox table."""

    pass


class OutboxUpdateError(OutboxStorageError):
    """Gagal update status record outbox."""

    pass


class OutboxLockError(OutboxStorageError):
    """Gagal mengakuisisi lock untuk row outbox (optimistic/pessimistic lock)."""

    pass


class OutboxRecordNotFoundError(OutboxStorageError):
    """Record outbox tidak ditemukan."""

    pass


# === 3. PUBLISHING ERRORS ===


class OutboxPublishError(OutboxError):
    """Error saat mempublikasikan event ke message broker."""

    pass


class OutboxPublishRetryableError(OutboxPublishError):
    """
    Error yang bisa di-retry (misal network timeout, broker unavailable).
    Outbox poller akan mencoba lagi nanti.
    """

    pass


class OutboxPublishFatalError(OutboxPublishError):
    """
    Error yang tidak bisa di-retry (misal event malformed, topic tidak ada).
    Record akan ditandai sebagai FAILED dan dikirim ke dead letter.
    """

    pass


# === 4. RELAY ERRORS ===


class OutboxRelayError(OutboxError):
    """Error pada relay service (batch processing)."""

    pass


class OutboxRelayStoppedError(OutboxRelayError):
    """Relay service dihentikan secara paksa (shutdown)."""

    pass


# === 5. POLLER ERRORS ===


class OutboxPollerError(OutboxError):
    """Error pada poller saat mengambil atau memproses batch."""

    pass


class OutboxPollerStoppedError(OutboxPollerError):
    """Poller dihentikan saat sedang memproses."""

    pass


# === 6. CIRCUIT BREAKER ERRORS ===


class OutboxCircuitBreakerOpenError(OutboxPublishError):
    """Circuit breaker untuk outbox publisher terbuka."""

    pass


# === 7. IDEMPOTENCY ERRORS ===


class OutboxIdempotencyError(OutboxError):
    """Error terkait idempotency key (duplikat, invalid, dll)."""

    pass


class OutboxDuplicateEventError(OutboxIdempotencyError):
    """Event dengan idempotency key yang sama sudah pernah diproses."""

    pass


# === 8. VALIDATION ERRORS ===


class OutboxValidationError(OutboxError):
    """Error validasi payload event."""

    pass


class OutboxEventTooLargeError(OutboxValidationError):
    """Event payload melebihi ukuran maksimum."""

    pass


# === 9. EXPORTS ===

__all__ = [
    "OutboxCircuitBreakerOpenError",
    "OutboxConfigurationError",
    "OutboxDuplicateEventError",
    "OutboxError",
    "OutboxEventTooLargeError",
    "OutboxIdempotencyError",
    "OutboxInsertError",
    "OutboxLockError",
    "OutboxPollerError",
    "OutboxPollerStoppedError",
    "OutboxPublishError",
    "OutboxPublishFatalError",
    "OutboxPublishRetryableError",
    "OutboxRecordNotFoundError",
    "OutboxRelayError",
    "OutboxRelayStoppedError",
    "OutboxStorageError",
    "OutboxUpdateError",
    "OutboxValidationError",
]
