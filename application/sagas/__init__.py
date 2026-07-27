# __init__.py - Complete exports for application.sagas package

from __future__ import annotations

"""
Package: application.sagas

Saga pattern implementation for distributed transactions across bounded contexts.

This package provides:
- Base classes for saga orchestrators
- State management with persistence
- Compensation handling for failed transactions
- Recovery mechanisms for interrupted sagas
- Concrete sagas for: Coretax submission, Payroll, Procurement, Sales, Manufacturing

Features:
- Step-by-step transaction orchestration
- Automatic compensation on failure
- State persistence with PostgreSQL and Redis cache
- Saga recovery after system restart
- Circuit breaker for resilience
- Comprehensive audit logging
"""

# Exceptions
# Coretax Saga
from application.sagas.coretax_submission_saga import CoretaxSubmissionSaga
from application.sagas.coretax_submission_saga_state import CoretaxSubmissionSagaState

# Manufacturing Saga
from application.sagas.manufacturing_saga import (
    ManufacturingSagaContext,
    ManufacturingSagaOrchestrator,
)

# Payroll Saga
from application.sagas.payroll_saga import (
    PayrollSaga,
    PayrollSagaContext,
    PayrollSagaOrchestrator,
    PayrollSagaStatus,
    PayrollStep,
    create_payroll_saga_orchestrator,
)
from application.sagas.payroll_saga_state import PayrollSagaState

# Procurement Saga
from application.sagas.procurement_saga import (
    IllegalStateException,
    ProcurementSaga,
    ProcurementSagaContext,
    ProcurementSagaOrchestrator,
    ProcurementSagaState,
    ProcurementSagaStepName,
    SecurityException,
    get_procurement_saga,
)
from application.sagas.procurement_saga_state import ProcurementSagaState as ProcurementSagaStateAlt
from application.sagas.saga_exceptions import (
    SagaAlreadyCompletedError,
    SagaCompensationError,
    SagaException,
    SagaNotFoundError,
    SagaStateStoreError,
    SagaStepExecutionError,
)

# Base classes
from application.sagas.saga_orchestrator_base import (
    SagaContext,
    SagaOrchestratorBase,
    SagaStatus,
)

# State Store
from application.sagas.saga_state_store import (
    DatabasePoolPort,
    InMemorySagaStateStore,
    RedisClientPort,
    SagaStateStore,
    create_saga_state_store,
)

# Sales Saga
from application.sagas.sales_saga import SalesSagaContext, SalesSagaOrchestrator

# ============================================================================
# Default instance for procurement saga (used by tests and orchestrator)
# ============================================================================
# Create a default in-memory state store for the procurement saga
_default_state_store = InMemorySagaStateStore()
procurement_saga = get_procurement_saga(state_store=_default_state_store)

# ============================================================================
# Exports
# ============================================================================

__all__ = [
    # Exceptions
    "SagaAlreadyCompletedError",
    "SagaCompensationError",
    "SagaException",
    "SagaNotFoundError",
    "SagaStateStoreError",
    "SagaStepExecutionError",
    # Base classes
    "SagaContext",
    "SagaOrchestratorBase",
    "SagaStatus",
    # Coretax Saga
    "CoretaxSubmissionSaga",
    "CoretaxSubmissionSagaState",
    # Payroll Saga
    "PayrollSaga",
    "PayrollSagaContext",
    "PayrollSagaOrchestrator",
    "PayrollSagaState",
    "PayrollSagaStatus",
    "PayrollStep",
    "create_payroll_saga_orchestrator",
    # Procurement Saga
    "IllegalStateException",
    "ProcurementSaga",
    "ProcurementSagaContext",
    "ProcurementSagaOrchestrator",
    "ProcurementSagaState",
    "ProcurementSagaStateAlt",
    "ProcurementSagaStepName",
    "SecurityException",
    "get_procurement_saga",
    "procurement_saga",  # Added default instance
    # Manufacturing Saga
    "ManufacturingSagaContext",
    "ManufacturingSagaOrchestrator",
    # Sales Saga
    "SalesSagaContext",
    "SalesSagaOrchestrator",
    # State Store
    "DatabasePoolPort",
    "InMemorySagaStateStore",
    "RedisClientPort",
    "SagaStateStore",
    "create_saga_state_store",
]