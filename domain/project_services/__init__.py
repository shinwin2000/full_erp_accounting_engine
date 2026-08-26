"""Package: domain.project_services - Project & Services domain layer.

Exports all public components for project management bounded context.
"""

from domain.project_services.aggregate_root import ProjectAggregate, ProjectRepository
from domain.project_services.domain_events import (
    DomainEvent,
    DomainEventPublisher,
    DomainEventType,
    MilestoneBilledEvent,
    MilestoneReadyEvent,
    ProjectActivatedEvent,
    ProjectBillingGenerated,
    ProjectBillingGeneratedEvent,
    ProjectCompleted,
    ProjectCompletedEvent,
    ProjectCreated,
    ProjectCreatedEvent,
    RetainerContractActivatedEvent,
    RevenueRecognized,
    RevenueRecognizedEvent,
    TimeEntryApprovedEvent,
    TimeEntryRecorded,
    TimeEntrySubmittedEvent,
)
from domain.project_services.invariants import (
    CostTrackerInvariants,
    InvariantResult,
    ProjectInvariants,
    ProjectInvariantsValidator,
    ProjectServicesInvariantEnforcer,
    RetainerContractInvariants,
    RevenueRecognitionInvariants,
    TimeEntryInvariants,
)
from domain.project_services.project_billing_schedule import (
    BillingMilestone,
    BillingMilestoneStatus,
    BillingType,
    ProjectBillingSchedule,
    ProjectBillingScheduleRepository,
)
from domain.project_services.project_cost_tracker import (
    CostEntry,
    CostType,
    ProjectCostTracker,
    ProjectCostTrackerRepository,
)
from domain.project_services.project_entity import (
    Project,
    ProjectEntity,
    ProjectEntityRepository,
    ProjectStatus,
    ProjectType,
)
from domain.project_services.project_revenue_recognizer import (
    ProjectRevenueRecognizer,
    ProjectRevenueRecognizerRepository,
    RevenueMethod,
    RevenueRecognitionEntry,
    RevenueRecognitionMethod,
    RevenueRecognitionStatus,
)
from domain.project_services.retainer_contract_entity import (
    BillingPeriod,
    RetainerContract,
    RetainerContractEntity,
    RetainerContractRepository,
    RetainerStatus,
)
from domain.project_services.time_entry_entity import (
    TimeEntry,
    TimeEntryEntity,
    TimeEntryRepository,
    TimeEntryStatus,
    WorkType,
)

__all__ = [
    # Billing Schedule
    "BillingMilestone",
    "BillingMilestoneStatus",
    # Retainer Contract
    "BillingPeriod",
    "BillingType",
    # Cost Tracker
    "CostEntry",
    "CostTrackerInvariants",
    "CostType",
    "DomainEvent",
    "DomainEventPublisher",
    # Domain Events
    "DomainEventType",
    # Invariants
    "InvariantResult",
    "MilestoneBilledEvent",
    "MilestoneReadyEvent",
    # Project Entity
    "Project",
    "ProjectActivatedEvent",
    # Aggregate
    "ProjectAggregate",
    "ProjectBillingGenerated",
    "ProjectBillingGeneratedEvent",
    "ProjectBillingSchedule",
    "ProjectBillingScheduleRepository",
    "ProjectCompleted",
    "ProjectCompletedEvent",
    "ProjectCostTracker",
    "ProjectCostTrackerRepository",
    "ProjectCreated",
    "ProjectCreatedEvent",
    "ProjectEntity",
    "ProjectEntityRepository",
    "ProjectInvariants",
    "ProjectInvariantsValidator",
    "ProjectRepository",
    # Revenue Recognizer
    "ProjectRevenueRecognizer",
    "ProjectRevenueRecognizerRepository",
    "ProjectServicesInvariantEnforcer",
    "ProjectStatus",
    "ProjectType",
    "RetainerContract",
    "RetainerContractActivatedEvent",
    "RetainerContractEntity",
    "RetainerContractInvariants",
    "RetainerContractRepository",
    "RetainerStatus",
    "RevenueMethod",
    "RevenueRecognitionEntry",
    "RevenueRecognitionInvariants",
    "RevenueRecognitionMethod",
    "RevenueRecognitionStatus",
    "RevenueRecognized",
    "RevenueRecognizedEvent",
    # Time Entry
    "TimeEntry",
    "TimeEntryApprovedEvent",
    "TimeEntryEntity",
    "TimeEntryInvariants",
    "TimeEntryRecorded",
    "TimeEntryRepository",
    "TimeEntryStatus",
    "TimeEntrySubmittedEvent",
    "WorkType",
]
