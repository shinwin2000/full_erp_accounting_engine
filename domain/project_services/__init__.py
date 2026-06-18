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
    # Aggregate
    "ProjectAggregate",
    "ProjectRepository",
    # Project Entity
    "Project",
    "ProjectEntity",
    "ProjectEntityRepository",
    "ProjectStatus",
    "ProjectType",
    # Cost Tracker
    "CostEntry",
    "CostType",
    "ProjectCostTracker",
    "ProjectCostTrackerRepository",
    # Revenue Recognizer
    "ProjectRevenueRecognizer",
    "ProjectRevenueRecognizerRepository",
    "RevenueMethod",
    "RevenueRecognitionEntry",
    "RevenueRecognitionMethod",
    "RevenueRecognitionStatus",
    # Billing Schedule
    "BillingMilestone",
    "BillingMilestoneStatus",
    "BillingType",
    "ProjectBillingSchedule",
    "ProjectBillingScheduleRepository",
    # Time Entry
    "TimeEntry",
    "TimeEntryEntity",
    "TimeEntryRepository",
    "TimeEntryStatus",
    "WorkType",
    # Retainer Contract
    "BillingPeriod",
    "RetainerContract",
    "RetainerContractEntity",
    "RetainerContractRepository",
    "RetainerStatus",
    # Domain Events
    "DomainEventType",
    "DomainEvent",
    "ProjectCreatedEvent",
    "ProjectActivatedEvent",
    "ProjectCompletedEvent",
    "RevenueRecognizedEvent",
    "ProjectBillingGeneratedEvent",
    "MilestoneReadyEvent",
    "MilestoneBilledEvent",
    "TimeEntrySubmittedEvent",
    "TimeEntryApprovedEvent",
    "RetainerContractActivatedEvent",
    "ProjectCreated",
    "ProjectCompleted",
    "RevenueRecognized",
    "TimeEntryRecorded",
    "ProjectBillingGenerated",
    "DomainEventPublisher",
    # Invariants
    "InvariantResult",
    "ProjectInvariants",
    "CostTrackerInvariants",
    "TimeEntryInvariants",
    "RevenueRecognitionInvariants",
    "RetainerContractInvariants",
    "ProjectServicesInvariantEnforcer",
    "ProjectInvariantsValidator",
]
