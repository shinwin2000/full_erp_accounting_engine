# __init__.py - Complete exports for application.events package

from __future__ import annotations

"""
Package: application.events

Event publisher, subscriber, and handler registry for application layer events.
Supports domain events and integration events with transactional outbox pattern.

Features:
- Priority-based handler execution
- Wildcard handlers for all events
- Multiple publish modes (SYNC, ASYNC, HYBRID)
- Idempotency support
- Dead letter queue support
- Worker-based parallel processing
- Circuit breaker for resilience
"""

# Handler Registry
# Global Event Subscribers (generic handler)
from application.events.global_event_subscribers import handle_any_event
from application.events.handler_registry import (
    AsyncEventHandler,
    EventHandler,
    EventHandlerRegistry,
    HandlerAlreadyRegisteredError,
    HandlerEntry,
    HandlerNotFoundError,
    HandlerPriority,
    HandlerRegistryError,
    InvalidHandlerSignatureError,
    SyncEventHandler,
    event_handler_registry,
    get_handlers,
    has_handlers,
    register_default_logging_handler,
    register_handler,
    register_wildcard,
)

# Event Publisher
from application.events.publisher_application import (
    ApplicationEventPublisher,
    CachePort,
    CircuitBreakerOpenError,
    EventEnvelope,
    EventPublishError,
    EventPublishFatalError,
    EventPublishRetryableError,
    EventPublishStatus,
    MessageBrokerPort,
    OutboxPort,
    PublishMode,
    PublishResult,
    create_event_publisher,
)

# Event Subscriber
from application.events.subscriber_application import (
    ApplicationEventSubscriber,
    DeadLetterStorePort,
    DuplicateEventError,
    EventProcessingError,
    EventProcessingFatalError,
    EventProcessingRetryableError,
    IdempotencyChecker,
    KafkaConsumerPort,
    MetricsPort,
    ProcessingStatus,
    RedisClientPort,
    SubscriptionConfig,
    SubscriptionMode,
    create_event_subscriber,
)

__all__ = [
    # Handler Registry
    "AsyncEventHandler",
    "EventHandler",
    "EventHandlerRegistry",
    "HandlerAlreadyRegisteredError",
    "HandlerEntry",
    "HandlerNotFoundError",
    "HandlerPriority",
    "HandlerRegistryError",
    "InvalidHandlerSignatureError",
    "SyncEventHandler",
    "event_handler_registry",
    "get_handlers",
    "has_handlers",
    "register_default_logging_handler",
    "register_handler",
    "register_wildcard",
    # Global Event Subscribers
    "handle_any_event",
    # Event Publisher
    "ApplicationEventPublisher",
    "CachePort",
    "CircuitBreakerOpenError",
    "EventEnvelope",
    "EventPublishError",
    "EventPublishFatalError",
    "EventPublishRetryableError",
    "EventPublishStatus",
    "MessageBrokerPort",
    "OutboxPort",
    "PublishMode",
    "PublishResult",
    "create_event_publisher",
    # Event Subscriber
    "ApplicationEventSubscriber",
    "DeadLetterStorePort",
    "DuplicateEventError",
    "EventProcessingError",
    "EventProcessingFatalError",
    "EventProcessingRetryableError",
    "IdempotencyChecker",
    "KafkaConsumerPort",
    "MetricsPort",
    "ProcessingStatus",
    "RedisClientPort",
    "SubscriptionConfig",
    "SubscriptionMode",
    "create_event_subscriber",
]
