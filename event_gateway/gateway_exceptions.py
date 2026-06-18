#!/usr/bin/env python3
"""
Module: gateway_exceptions.py
Layer: Event Gateway
Responsibility: Mendefinisikan semua exception yang terkait dengan Event Gateway.
"""

from __future__ import annotations

from typing import Any


class EventGatewayException(Exception):
    """Base exception untuk semua error di Event Gateway."""

    def __init__(
        self, message: str, code: str | None = None, details: dict[str, Any] | None = None
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}


# Schema Validation
class SchemaValidationError(EventGatewayException):
    def __init__(
        self, message: str, event_type: str | None = None, errors: list | None = None, **kwargs
    ):
        super().__init__(message, code="SCHEMA_VALIDATION_ERROR", **kwargs)
        self.event_type = event_type
        self.errors = errors or []


class SchemaNotFoundError(SchemaValidationError):
    def __init__(self, event_type: str, **kwargs):
        super().__init__(
            f"Schema not found for event type: {event_type}",
            event_type=event_type,
            code="SCHEMA_NOT_FOUND",
            **kwargs,
        )


class SchemaLoadError(EventGatewayException):
    def __init__(self, message: str, schema_path: str | None = None, **kwargs):
        super().__init__(message, code="SCHEMA_LOAD_ERROR", **kwargs)
        self.schema_path = schema_path


# Normalization
class NormalizationError(EventGatewayException):
    def __init__(self, message: str, event_type: str | None = None, **kwargs):
        super().__init__(message, code="NORMALIZATION_ERROR", **kwargs)
        self.event_type = event_type


class UnsupportedFieldTypeError(NormalizationError):
    def __init__(self, field_name: str, field_type: str, **kwargs):
        super().__init__(
            f"Cannot normalize field '{field_name}' of type '{field_type}'",
            code="UNSUPPORTED_FIELD_TYPE",
            **kwargs,
        )
        self.field_name = field_name
        self.field_type = field_type


# Deduplication
class DuplicateEventError(EventGatewayException):
    def __init__(
        self,
        event_id: str,
        event_type: str | None = None,
        reason: str = "Event already processed",
        **kwargs,
    ):
        super().__init__(
            f"Duplicate event detected: {event_id} - {reason}", code="DUPLICATE_EVENT", **kwargs
        )
        self.event_id = event_id
        self.event_type = event_type
        self.reason = reason


class IdempotencyKeyError(EventGatewayException):
    def __init__(self, message: str, key: str | None = None, **kwargs):
        super().__init__(message, code="IDEMPOTENCY_KEY_ERROR", **kwargs)
        self.key = key


# Routing
class RoutingError(EventGatewayException):
    def __init__(self, message: str, event_type: str | None = None, **kwargs):
        super().__init__(message, code="ROUTING_ERROR", **kwargs)
        self.event_type = event_type


class TransformerNotFoundError(RoutingError):
    def __init__(self, event_type: str, **kwargs):
        super().__init__(
            f"No transformer registered for event type: {event_type}",
            event_type=event_type,
            code="TRANSFORMER_NOT_FOUND",
            **kwargs,
        )


class TransformerExecutionError(RoutingError):
    def __init__(
        self,
        message: str,
        transformer_name: str | None = None,
        event_id: str | None = None,
        **kwargs,
    ):
        super().__init__(message, code="TRANSFORMER_EXECUTION_ERROR", **kwargs)
        self.transformer_name = transformer_name
        self.event_id = event_id


class QueueFullError(RoutingError):
    def __init__(self, queue_size: int, max_size: int, **kwargs):
        super().__init__(
            f"Event queue is full: {queue_size}/{max_size}", code="QUEUE_FULL", **kwargs
        )
        self.queue_size = queue_size
        self.max_size = max_size


# Dead Letter Queue
class DeadLetterQueueError(EventGatewayException):
    def __init__(self, message: str, item_id: str | None = None, **kwargs):
        super().__init__(message, code="DLQ_ERROR", **kwargs)
        self.item_id = item_id


class DLQItemNotFoundError(DeadLetterQueueError):
    def __init__(self, item_id: str, **kwargs):
        super().__init__(
            f"DLQ item not found: {item_id}", item_id=item_id, code="DLQ_ITEM_NOT_FOUND", **kwargs
        )


class DLQFullError(DeadLetterQueueError):
    def __init__(self, current_size: int, max_size: int, **kwargs):
        super().__init__(
            f"Dead Letter Queue is full: {current_size}/{max_size}", code="DLQ_FULL", **kwargs
        )
        self.current_size = current_size
        self.max_size = max_size


class DLQReplayError(DeadLetterQueueError):
    def __init__(self, message: str, item_id: str, **kwargs):
        super().__init__(message, item_id=item_id, code="DLQ_REPLAY_ERROR", **kwargs)


# Event Gate
class EventGateError(EventGatewayException):
    def __init__(self, message: str, **kwargs):
        super().__init__(message, code="EVENT_GATE_ERROR", **kwargs)


class EventGateShutdownError(EventGateError):
    def __init__(self, message: str = "Event Gate is shutting down", **kwargs):
        super().__init__(message, code="EVENT_GATE_SHUTDOWN", **kwargs)


class EventProcessingError(EventGateError):
    def __init__(
        self, message: str, event_id: str | None = None, event_type: str | None = None, **kwargs
    ):
        super().__init__(message, code="EVENT_PROCESSING_ERROR", **kwargs)
        self.event_id = event_id
        self.event_type = event_type


# Transformer
class TransformerError(EventGatewayException):
    def __init__(
        self,
        message: str,
        transformer_name: str | None = None,
        event_type: str | None = None,
        **kwargs,
    ):
        super().__init__(message, code="TRANSFORMER_ERROR", **kwargs)
        self.transformer_name = transformer_name
        self.event_type = event_type
