#!/usr/bin/env python3

"""
Module: application.commands_cqrs.__init__

Layer: Application / Commands & Queries (CQRS)

Ekspor komponen inti untuk command-query separation:
- Command bus, query bus
- Registri handler
- Executor dengan audit
- Validator
- Envelope hasil (result envelope)

Tidak ada ketergantungan pada event_gateway – semua event handling dilakukan
melalui dependency injection dan port abstraksi.
"""

from __future__ import annotations

# Command & Query Buses
from application.commands_cqrs.command_bus_unified import UnifiedCommandBus

# Command Executor with Audit
from application.commands_cqrs.command_executor_with_audit import (
    CommandExecutionError,
    CommandExecutionResult,
    CommandExecutorWithAudit,
)

# Command & Query Handler Registries
from application.commands_cqrs.command_handler_registry import (
    CommandHandlerRegistry,
    command_handler_registry,
    get_command_handler,
    register_command_handler,
    unregister_command_handler,
)

# Command Result Envelope
from application.commands_cqrs.command_result_envelope import (
    CommandResultEnvelope,
    CommandStatus,
)

# Command Validator
from application.commands_cqrs.command_validator import (
    CommandValidator,
    ValidationError,
)
from application.commands_cqrs.query_bus_unified import UnifiedQueryBus

# Query Executor (read‑only)
from application.commands_cqrs.query_executor_readonly import (
    QueryExecutionError,
    QueryExecutionResult,
    QueryExecutorReadOnly,
)
from application.commands_cqrs.query_handler_registry import (
    QueryHandlerRegistry,
    get_query_handler,
    query_handler_registry,
    register_query_handler,
    unregister_query_handler,
)

# ============================================================================
# BACKWARD COMPATIBILITY ALIASES
# ============================================================================

# Alias untuk nama yang digunakan oleh router
CommandBusUnified = UnifiedCommandBus
QueryBusUnified = UnifiedQueryBus


# ============================================================================
# EKSPOR SEMUA KOMPONEN
# ============================================================================

__all__ = [
    # Buses
    "UnifiedCommandBus",
    "UnifiedQueryBus",
    "CommandBusUnified",
    "QueryBusUnified",
    # Registries
    "CommandHandlerRegistry",
    "command_handler_registry",
    "get_command_handler",
    "register_command_handler",
    "unregister_command_handler",
    "QueryHandlerRegistry",
    "query_handler_registry",
    "get_query_handler",
    "register_query_handler",
    "unregister_query_handler",
    # Executors
    "CommandExecutorWithAudit",
    "CommandExecutionError",
    "CommandExecutionResult",
    "QueryExecutorReadOnly",
    "QueryExecutionError",
    "QueryExecutionResult",
    # Validator
    "CommandValidator",
    "ValidationError",
    # Result Envelope
    "CommandResultEnvelope",
    "CommandStatus",
]
