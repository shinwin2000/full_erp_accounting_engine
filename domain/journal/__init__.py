"""
Package: domain.journal
Journal domain layer - Double-entry accounting core.
"""

from __future__ import annotations

from domain.journal.aggregate_root import Journal, JournalAggregate, JournalRepository
from domain.journal.domain_events import (
    DomainEvent,
    DomainEventPublisher,
    DomainEventType,
    JournalAdjusted,
    JournalApproved,
    JournalArchived,
    JournalCreated,
    JournalPosted,
    JournalRejected,
    JournalReversed,
    JournalSubmitted,
    JournalVoided,
)
from domain.journal.invariants import (
    InvariantResult,
    JournalInvariantEnforcer,
    JournalInvariants,
    JournalInvariantsValidator,
)
from domain.journal.journal_entity import (
    JournalEntity,
    JournalEntityRepository,
    JournalEntry,
    JournalLine,
    JournalStatus,
    JournalType,
)
from domain.journal.journal_entry import JournalEntry as SimpleJournalEntry
from domain.journal.journal_entry import JournalEntryStatus
from domain.journal.journal_entry import JournalLine as SimpleJournalLine
from domain.journal.journal_line_vo import JournalLineRepository, JournalLineVO, JournalSide
from domain.journal.optimistic_lock import (
    OptimisticLockException,
    OptimisticLockManager,
    VersionedJournalMixin,
)
from domain.journal.state_machine import (
    ALLOWED_TRANSITIONS,
    TRANSITION_RULES,
    JournalStateMachine,
    StateTransitionRule,
)

__all__ = [
    # Aggregate
    "Journal",
    "JournalAggregate",
    "JournalRepository",
    # Events
    "DomainEvent",
    "DomainEventPublisher",
    "DomainEventType",
    "JournalAdjusted",
    "JournalApproved",
    "JournalArchived",
    "JournalCreated",
    "JournalPosted",
    "JournalRejected",
    "JournalReversed",
    "JournalSubmitted",
    "JournalVoided",
    # Invariants
    "InvariantResult",
    "JournalInvariantEnforcer",
    "JournalInvariants",
    "JournalInvariantsValidator",
    # Entity
    "JournalEntity",
    "JournalEntityRepository",
    "JournalEntry",
    "JournalLine",
    "JournalStatus",
    "JournalType",
    # Simple Entry
    "SimpleJournalEntry",
    "JournalEntryStatus",
    "SimpleJournalLine",
    # Line VO
    "JournalLineVO",
    "JournalLineRepository",
    "JournalSide",
    # Locking
    "OptimisticLockException",
    "OptimisticLockManager",
    "VersionedJournalMixin",
    # State Machine
    "ALLOWED_TRANSITIONS",
    "TRANSITION_RULES",
    "JournalStateMachine",
    "StateTransitionRule",
]
