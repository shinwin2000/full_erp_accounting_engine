#!/usr/bin/env python3
from __future__ import annotations

"""
Package: domain.coa

Chart of Accounts domain module.

Exports all public classes, enums, value objects, aggregates,
events, validators, state machine, and optimistic lock utilities.

Layered architecture: This module belongs to Domain layer (layer 6),
depends only on axioms, constitution, shared_value_objects, and standard library.
"""

from domain.coa.account_code_vo import (
    ALLOWED_SEPARATORS,
    DEFAULT_CODE_PATTERN,
    AccountCode,
    AccountCodeFormatError,
    AccountCodeVO,
)
from domain.coa.account_entity import (
    Account,
    AccountEntity,
    AccountRepository,
    AccountStatus,
)
from domain.coa.account_hierarchy_tree import (
    AccountHierarchyTree,
    HierarchyNode,
)
from domain.coa.account_normal_balance_vo import (
    AccountNormalBalanceVO,
    NormalBalance,
)
from domain.coa.account_type_enum import (
    AccountType,
)
from domain.coa.aggregate_root import (
    AccountAggregate,
    ChartOfAccounts,
    ChartOfAccountsAggregate,
    COAAggregate,
    COARepository,
    COAStatus,
    InMemoryCOARepository,
)
from domain.coa.domain_events import (
    AccountCreated,
    AccountCreatedEvent,
    AccountDeactivated,
    AccountDeactivatedEvent,
    AccountLocked,
    AccountLockedEvent,
    AccountMerged,
    AccountMergedEvent,
    AccountReactivated,
    AccountReactivatedEvent,
    AccountSplit,
    AccountSplitEvent,
    AccountUnlocked,
    AccountUnlockedEvent,
    AccountUpdated,
    AccountUpdatedEvent,
    COAArchived,
    COAArchivedEvent,
    COACreated,
    COACreatedEvent,
    COALocked,
    COALockedEvent,
    COAUnlocked,
    COAUnlockedEvent,
    DomainEvent,
    DomainEventPublisher,
    DomainEventType,
    HierarchyChanged,
    HierarchyChangedEvent,
    deserialize_event,
    event_type_from_name,
)
from domain.coa.invariants_validator import (
    COAInvariantsValidator,
    InvariantViolationError,
    ValidationResult,
    validate_account_code,
    validate_account_name,
)
from domain.coa.optimistic_lock import (
    DeadlockDetectedError,
    DeadlockDetector,
    OptimisticLockException,
    OptimisticLockManager,
    OptimisticLockRetryExhausted,
    OptimisticLockUtils,
    RetryConfig,
    RetryStrategy,
    VersionedEntity,
    retry_on_conflict,
    with_retry,
    with_retry_async,
)
from domain.coa.state_machine import (
    ALLOWED_TRANSITIONS,
    AccountStateMachine,
    COAStateMachine,
    StatusTransitionRecord,
    TransitionHistory,
    get_allowed_transitions,
    get_required_roles,
    get_status_display_name,
    is_active_to_status,
    is_transition_allowed,
    status_from_is_active,
)
from domain.coa.state_machine import (
    AccountStatus as StateMachineAccountStatus,
)
from domain.coa.state_machine import (
    COAStatus as COAStateMachineStatus,
)

__all__ = [
    # AccountCodeVO
    "AccountCodeVO",
    "AccountCode",
    "AccountCodeFormatError",
    "DEFAULT_CODE_PATTERN",
    "ALLOWED_SEPARATORS",
    # AccountNormalBalanceVO
    "AccountNormalBalanceVO",
    "NormalBalance",
    # AccountType
    "AccountType",
    # AccountEntity
    "AccountEntity",
    "Account",
    "AccountStatus",
    "AccountRepository",
    # AccountHierarchyTree
    "AccountHierarchyTree",
    "HierarchyNode",
    # StateMachine
    "AccountStateMachine",
    "StateMachineAccountStatus",
    "ALLOWED_TRANSITIONS",
    "COAStateMachine",
    "COAStateMachineStatus",
    "StatusTransitionRecord",
    "TransitionHistory",
    "get_allowed_transitions",
    "get_required_roles",
    "get_status_display_name",
    "is_active_to_status",
    "is_transition_allowed",
    "status_from_is_active",
    # OptimisticLock
    "OptimisticLockException",
    "OptimisticLockManager",
    "OptimisticLockRetryExhausted",
    "OptimisticLockUtils",
    "RetryConfig",
    "RetryStrategy",
    "VersionedEntity",
    "retry_on_conflict",
    "with_retry",
    "with_retry_async",
    "DeadlockDetector",
    "DeadlockDetectedError",
    # InvariantsValidator
    "COAInvariantsValidator",
    "InvariantViolationError",
    "ValidationResult",
    "validate_account_code",
    "validate_account_name",
    # DomainEvents
    "DomainEventType",
    "DomainEvent",
    "DomainEventPublisher",
    "AccountCreatedEvent",
    "AccountUpdatedEvent",
    "AccountDeactivatedEvent",
    "AccountReactivatedEvent",
    "AccountLockedEvent",
    "AccountUnlockedEvent",
    "AccountMergedEvent",
    "AccountSplitEvent",
    "HierarchyChangedEvent",
    "COACreatedEvent",
    "COALockedEvent",
    "COAUnlockedEvent",
    "COAArchivedEvent",
    "AccountCreated",
    "AccountUpdated",
    "AccountDeactivated",
    "AccountReactivated",
    "AccountLocked",
    "AccountUnlocked",
    "AccountMerged",
    "AccountSplit",
    "HierarchyChanged",
    "COACreated",
    "COALocked",
    "COAUnlocked",
    "COAArchived",
    "event_type_from_name",
    "deserialize_event",
    # AggregateRoot
    "COAStatus",
    "ChartOfAccounts",
    "ChartOfAccountsAggregate",
    "AccountAggregate",
    "COAAggregate",
    "COARepository",
    "InMemoryCOARepository",
]
