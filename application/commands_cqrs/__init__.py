#!/usr/bin/env python3
# -*- coding: utf-8 -*-

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
from application.commands_cqrs.query_bus_unified import UnifiedQueryBus

# Command & Query Handler Registries
from application.commands_cqrs.command_handler_registry import (
    CommandHandlerRegistry,
    command_handler_registry,
    get_command_handler,
    register_command_handler,
    unregister_command_handler,
)
from application.commands_cqrs.query_handler_registry import (
    QueryHandlerRegistry,
    query_handler_registry,
    get_query_handler,
    register_query_handler,
    unregister_query_handler,
)

# Command Executor with Audit
from application.commands_cqrs.command_executor_with_audit import (
    CommandExecutorWithAudit,
    CommandExecutionError,
    CommandExecutionResult,
)

# Query Executor (read‑only)
from application.commands_cqrs.query_executor_readonly import (
    QueryExecutorReadOnly,
    QueryExecutionError,
    QueryExecutionResult,
)

# Command Validator
from application.commands_cqrs.command_validator import (
    CommandValidator,
    ValidationError,
)

# Command Result Envelope
from application.commands_cqrs.command_result_envelope import (
    CommandResultEnvelope,
    CommandStatus,
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