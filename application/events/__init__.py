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
# Global Event Subscribers (for P57)
from application.events.global_event_subscribers import (
    handle_account_reactivated_event,
    handle_bank_account_updated_event,
    handle_dividend_paid_event,
    handle_faktur_rejected_event,
    handle_intangible_asset_revaluated_event,
    handle_production_completed_event,
    handle_project_activated_event,
    handle_role_revoked_event,
    handle_time_entry_approved_event,
    handle_work_order_completed_event,
    register_global_subscribers,
)
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
    # Global Event Subscribers
    "handle_account_reactivated_event",
    "handle_bank_account_updated_event",
    "handle_dividend_paid_event",
    "handle_faktur_rejected_event",
    "handle_intangible_asset_revaluated_event",
    "handle_production_completed_event",
    "handle_project_activated_event",
    "handle_role_revoked_event",
    "handle_time_entry_approved_event",
    "handle_work_order_completed_event",
    "register_global_subscribers",
]
