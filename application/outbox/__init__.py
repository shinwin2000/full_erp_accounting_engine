"""
Package: application.outbox

Transactional outbox pattern for reliable event publishing.

This package provides:
- Outbox repository abstraction for storing events
- Relay service for publishing events to message broker
- Poller for periodic batch processing
- Circuit breaker for resilience
- Retry policies with exponential backoff
- Dead letter queue support

Features:
- Transactional outbox pattern (write to database first, then publish)
- Idempotency support
- Batch processing with configurable batch size
- Advisory lock for multiple poller instances
- Automatic dead letter handling after max retries
- Health check endpoints
- Comprehensive statistics
"""

# __init__.py - Complete exports for application.outbox package
from __future__ import annotations

# Exceptions
from application.outbox.outbox_exceptions import (
    OutboxCircuitBreakerOpenError,
    OutboxConfigurationError,
    OutboxDuplicateEventError,
    OutboxError,
    OutboxEventTooLargeError,
    OutboxIdempotencyError,
    OutboxInsertError,
    OutboxLockError,
    OutboxPollerError,
    OutboxPollerStoppedError,
    OutboxPublishError,
    OutboxPublishFatalError,
    OutboxPublishRetryableError,
    OutboxRecordNotFoundError,
    OutboxRelayError,
    OutboxRelayStoppedError,
    OutboxStorageError,
    OutboxUpdateError,
    OutboxValidationError,
)

# Poller
from application.outbox.outbox_poller import (
    DatabaseLockPort,
    MemoryLockPort,
    OutboxPoller,
    OutboxPollerConfig,
    run_outbox_poller_simple,
)

# Relay Service
from application.outbox.outbox_relay_service import (
    MessageBrokerPort,
    OutboxRecordStatus,
    OutboxRelayConfig,
    OutboxRelayService,
    OutboxRepositoryPort,
)

__all__ = [
    # Poller
    "DatabaseLockPort",
    "MemoryLockPort",
    # Relay Service
    "MessageBrokerPort",
    # Exceptions
    "OutboxCircuitBreakerOpenError",
    "OutboxConfigurationError",
    "OutboxDuplicateEventError",
    "OutboxError",
    "OutboxEventTooLargeError",
    "OutboxIdempotencyError",
    "OutboxInsertError",
    "OutboxLockError",
    "OutboxPoller",
    "OutboxPollerConfig",
    "OutboxPollerError",
    "OutboxPollerStoppedError",
    "OutboxPublishError",
    "OutboxPublishFatalError",
    "OutboxPublishRetryableError",
    "OutboxRecordNotFoundError",
    "OutboxRecordStatus",
    "OutboxRelayConfig",
    "OutboxRelayError",
    "OutboxRelayService",
    "OutboxRelayStoppedError",
    "OutboxRepositoryPort",
    "OutboxStorageError",
    "OutboxUpdateError",
    "OutboxValidationError",
    "run_outbox_poller_simple",
]
