#!/usr/bin/env python3
"""
Event Gateway Package
=====================
Pusat routing event dari domain ke seluruh sistem.
"""

from __future__ import annotations

from event_gateway.event_dead_letter_queue_manager import DeadLetterQueueManager
from event_gateway.event_deduplicator_idempotency import EventDeduplicator
from event_gateway.event_enricher_context import EventContextEnricher
from event_gateway.event_envelope import EventEnvelope, EventPriority, EventStatus
from event_gateway.event_gate_singleton import EventGate, get_event_gate, shutdown_event_gate
from event_gateway.event_normalizer_canonical import EventNormalizer
from event_gateway.event_router_to_transformer import EventRouter
from event_gateway.event_schema_validator import EventSchemaValidator
from event_gateway.event_source_authenticator import EventSourceAuthenticator
from event_gateway.gateway_exceptions import (
    DeadLetterQueueError,
    DuplicateEventError,
    EventGateError,
    EventGatewayException,
    QueueFullError,
    RoutingError,
    SchemaNotFoundError,
    SchemaValidationError,
    TransformerNotFoundError,
)

__all__ = [
    "DeadLetterQueueError",
    "DeadLetterQueueManager",
    "DuplicateEventError",
    "EventContextEnricher",
    "EventDeduplicator",
    "EventEnvelope",
    "EventGate",
    "EventGateError",
    "EventGatewayException",
    "EventNormalizer",
    "EventPriority",
    "EventRouter",
    "EventSchemaValidator",
    "EventSourceAuthenticator",
    "EventStatus",
    "QueueFullError",
    "RoutingError",
    "SchemaNotFoundError",
    "SchemaValidationError",
    "TransformerNotFoundError",
    "get_event_gate",
    "shutdown_event_gate",
]
