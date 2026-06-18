#!/usr/bin/env python3
from __future__ import annotations

"""
Event Gateway Package
=====================
Pusat routing event dari domain ke seluruh sistem.

Event Gateway adalah komponen inti yang bertanggung jawab untuk:
- Menerima event dari berbagai sumber (domain, API, eksternal)
- Memvalidasi event terhadap skema
- Menormalisasi event ke format kanonik
- Mendeteksi dan mencegah duplikasi event (idempotensi)
- Mengirim event ke transformer yang terdaftar
- Mengelola Dead Letter Queue untuk event yang gagal
- Menyediakan audit trail dan hash chaining untuk integritas

Semua komponen telah dilengkapi dengan metode entity dasar:
- validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch
"""

# Event Envelope
# Dead Letter Queue
from event_gateway.event_dead_letter_queue_manager import (
    DeadLetterQueueManager,
    DLQItem,
)

# Deduplicator & Idempotency
from event_gateway.event_deduplicator_idempotency import (
    DuplicateEventError,
    EventDeduplicator,
    IdempotencyKeyError,
    idempotent,
)

# Event Enricher Context
from event_gateway.event_enricher_context import (
    EnrichmentContext,
    EventContextEnricher,
    EventEnrichmentError,
    add_environment_enricher,
    add_timestamp_enricher,
    add_trace_parent_enricher,
)
from event_gateway.event_envelope import EventEnvelope, EventPriority, EventStatus

# Event Gate Singleton
from event_gateway.event_gate_singleton import (
    EventGate,
    EventGateError,
    EventGateShutdownError,
    EventProcessingError,
    get_event_gate,
    get_instance,
    shutdown,
    shutdown_event_gate,
)

# Event Normalizer
from event_gateway.event_normalizer_canonical import (
    CanonicalEvent,
    EventNormalizer,
    extract_metadata,
    extract_payload,
    is_canonical,
)

# Event Router & Transformer Registry
from event_gateway.event_router_to_transformer import (
    EventRouter,
    QueueFullError,
    TransformerExecutionError,
    TransformerNotFoundError,
    TransformerRegistry,
)

# Event Schema Validator
from event_gateway.event_schema_validator import (
    EventSchemaValidator,
    SchemaLoadError,
    SchemaNotFoundError,
    SchemaValidationError,
)

# Event Source Authenticator
from event_gateway.event_source_authenticator import (
    AuthenticatedSource,
    AuthMethod,
    EventAuthenticationError,
    EventSourceAuthenticator,
)

# Gateway Exceptions
from event_gateway.gateway_exceptions import (
    DeadLetterQueueError,
    DLQFullError,
    DLQItemNotFoundError,
    DLQReplayError,
    EventGatewayException,
    NormalizationError,
    RoutingError,
    TransformerError,
    UnsupportedFieldTypeError,
)
from event_gateway.gateway_exceptions import (
    DuplicateEventError as GatewayDuplicateEventError,
)
from event_gateway.gateway_exceptions import (
    EventGateError as GatewayEventGateError,
)
from event_gateway.gateway_exceptions import (
    EventGateShutdownError as GatewayEventGateShutdownError,
)
from event_gateway.gateway_exceptions import (
    EventProcessingError as GatewayEventProcessingError,
)
from event_gateway.gateway_exceptions import (
    IdempotencyKeyError as GatewayIdempotencyKeyError,
)
from event_gateway.gateway_exceptions import (
    QueueFullError as GatewayQueueFullError,
)
from event_gateway.gateway_exceptions import (
    SchemaNotFoundError as GatewaySchemaNotFoundError,
)
from event_gateway.gateway_exceptions import (
    SchemaValidationError as GatewaySchemaValidationError,
)
from event_gateway.gateway_exceptions import (
    TransformerExecutionError as GatewayTransformerExecutionError,
)
from event_gateway.gateway_exceptions import (
    TransformerNotFoundError as GatewayTransformerNotFoundError,
)

__all__ = [
    # Event Envelope
    "EventEnvelope",
    "EventPriority",
    "EventStatus",
    # Event Gate
    "EventGate",
    "EventGateError",
    "EventGateShutdownError",
    "EventProcessingError",
    "get_event_gate",
    "get_instance",
    "shutdown",
    "shutdown_event_gate",
    # Dead Letter Queue
    "DeadLetterQueueManager",
    "DLQItem",
    # Deduplicator
    "DuplicateEventError",
    "EventDeduplicator",
    "IdempotencyKeyError",
    "idempotent",
    # Enricher
    "EnrichmentContext",
    "EventContextEnricher",
    "EventEnrichmentError",
    "add_environment_enricher",
    "add_timestamp_enricher",
    "add_trace_parent_enricher",
    # Normalizer
    "CanonicalEvent",
    "EventNormalizer",
    "extract_metadata",
    "extract_payload",
    "is_canonical",
    # Router
    "EventRouter",
    "QueueFullError",
    "TransformerExecutionError",
    "TransformerNotFoundError",
    "TransformerRegistry",
    # Schema Validator
    "EventSchemaValidator",
    "SchemaLoadError",
    "SchemaNotFoundError",
    "SchemaValidationError",
    # Authenticator
    "AuthMethod",
    "AuthenticatedSource",
    "EventAuthenticationError",
    "EventSourceAuthenticator",
    # Exceptions (dengan alias untuk backward compatibility)
    "DLQFullError",
    "DLQItemNotFoundError",
    "DLQReplayError",
    "DeadLetterQueueError",
    "GatewayDuplicateEventError",
    "GatewayEventGateError",
    "GatewayEventGateShutdownError",
    "EventGatewayException",
    "GatewayEventProcessingError",
    "GatewayIdempotencyKeyError",
    "NormalizationError",
    "GatewayQueueFullError",
    "RoutingError",
    "GatewaySchemaNotFoundError",
    "GatewaySchemaValidationError",
    "TransformerError",
    "GatewayTransformerExecutionError",
    "GatewayTransformerNotFoundError",
    "UnsupportedFieldTypeError",
]
