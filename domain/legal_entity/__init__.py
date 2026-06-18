"""
Package: domain.legal_entity
Legal Entity domain layer - Company, Tax Profile, and Entity Management.
"""

from __future__ import annotations

from domain.legal_entity.aggregate_root import (
    EntityStatus,
    EntityType,
    FiscalYearType,
    LegalEntity,
    LegalEntityAggregate,
    LegalEntityRepository,
    LegalEntityStatus,
    LegalEntityType,
)
from domain.legal_entity.company_entity import (
    Company,
    CompanyEntity,
    CompanyEntityRepository,
)
from domain.legal_entity.company_tax_profile_vo import (
    CompanyTaxProfile,
    CompanyTaxProfileVO,
    TaxPaymentMethod,
    TaxRegime,
)
from domain.legal_entity.domain_events import (
    CompanyAddressUpdatedEvent,
    CompanyContactUpdatedEvent,
    CompanyDissolvedEvent,
    CompanyReactivatedEvent,
    CompanyRegisteredEvent,
    CompanySuspendedEvent,
    DomainEvent,
    DomainEventPublisher,
    DomainEventType,
    PKPStatusChangedEvent,
    TaxProfileUpdatedEvent,
)
from domain.legal_entity.invariants import (
    CompanyEntityInvariants,
    InvariantResult,
    LegalEntityInvariantEnforcer,
    LegalEntityInvariants,
)

__all__ = [
    # Aggregate
    "EntityStatus",
    "EntityType",
    "FiscalYearType",
    "LegalEntity",
    "LegalEntityAggregate",
    "LegalEntityRepository",
    "LegalEntityStatus",
    "LegalEntityType",
    # Company
    "Company",
    "CompanyEntity",
    "CompanyEntityRepository",
    # Tax Profile VO
    "CompanyTaxProfile",
    "CompanyTaxProfileVO",
    "TaxPaymentMethod",
    "TaxRegime",
    # Events
    "CompanyAddressUpdatedEvent",
    "CompanyContactUpdatedEvent",
    "CompanyDissolvedEvent",
    "CompanyReactivatedEvent",
    "CompanyRegisteredEvent",
    "CompanySuspendedEvent",
    "DomainEvent",
    "DomainEventPublisher",
    "DomainEventType",
    "PKPStatusChangedEvent",
    "TaxProfileUpdatedEvent",
    # Invariants
    "CompanyEntityInvariants",
    "InvariantResult",
    "LegalEntityInvariantEnforcer",
    "LegalEntityInvariants",
]
