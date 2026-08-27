#!/usr/bin/env python3
"""
Package: domain.fixed_asset

Fixed Asset domain module.

Exports all public classes, enums, value objects, entities,
aggregates, events, validators, and repository protocols.
"""

from domain.fixed_asset.aggregate_root import (
    FixedAssetAggregate,
    FixedAssetCollection,
    FixedAssetRepository,
)
from domain.fixed_asset.asset_entity import (
    AssetCategory,
    AssetStatus,
    AssetType,
    FixedAsset,
    FixedAssetEntity,
)
from domain.fixed_asset.asset_entity import (
    FixedAssetRepository as FixedAssetEntityRepository,
)
from domain.fixed_asset.asset_group_entity import (
    AssetGroup,
    AssetGroupEntity,
    AssetGroupRepository,
    AssetGroupService,
    AssetGroupSummary,
)
from domain.fixed_asset.depreciation_schedule_engine import (
    DepreciationEntry,
    DepreciationMethod,
    DepreciationSchedule,
    DepreciationScheduleEngine,
)
from domain.fixed_asset.disposal_entity import (
    AssetDisposal,
    DisposalEntity,
    DisposalRepository,
    DisposalStatus,
    DisposalType,
)
from domain.fixed_asset.domain_events import (
    AssetAcquired,
    AssetAcquiredEvent,
    AssetDepreciated,
    AssetDepreciationPostedEvent,
    AssetDisposed,
    AssetDisposedEvent,
    AssetFullyDepreciated,
    AssetFullyDepreciatedEvent,
    AssetImpairedEvent,
    AssetImpairmentRecognized,
    AssetRevaluatedEvent,
    AssetRevalued,
    AssetTransferred,
    AssetTransferredEvent,
    AssetUpdated,
    AssetUpdatedEvent,
    DomainEvent,
    DomainEventPublisher,
    DomainEventType,
)
from domain.fixed_asset.impairment_tester import (
    ImpairmentIndicator,
    ImpairmentTest,
    ImpairmentTester,
    ImpairmentTestResult,
)
from domain.fixed_asset.invariants import (
    FixedAssetInvariantEnforcer,
    FixedAssetInvariants,
    FixedAssetInvariantsValidator,
    InvariantResult,
)
from domain.fixed_asset.revaluation_entity import (
    AssetRevaluation,
    RevaluationEntity,
    RevaluationMethod,
    RevaluationRepository,
    RevaluationStatus,
    RevaluationType,
)
from domain.fixed_asset.transfer_entity import (
    AssetTransfer,
    TransferEntity,
    TransferRepository,
    TransferStatus,
    TransferType,
)

# ============================================================================
# Ekspor modul asset_entity untuk keperluan testing dan mocking
# ============================================================================
from . import asset_entity as asset_entity

__all__ = [
    "AssetAcquired",
    "AssetAcquiredEvent",
    "AssetCategory",
    "AssetDepreciated",
    "AssetDepreciationPostedEvent",
    "AssetDisposal",
    "AssetDisposed",
    "AssetDisposedEvent",
    "AssetFullyDepreciated",
    "AssetFullyDepreciatedEvent",
    "AssetGroup",
    # asset_group_entity
    "AssetGroupEntity",
    "AssetGroupRepository",
    "AssetGroupService",
    "AssetGroupSummary",
    "AssetImpairedEvent",
    "AssetImpairmentRecognized",
    "AssetRevaluatedEvent",
    "AssetRevaluation",
    "AssetRevalued",
    # asset_entity
    "AssetStatus",
    "AssetTransfer",
    "AssetTransferred",
    "AssetTransferredEvent",
    "AssetType",
    "AssetUpdated",
    "AssetUpdatedEvent",
    "DepreciationEntry",
    # depreciation_schedule_engine
    "DepreciationMethod",
    "DepreciationSchedule",
    "DepreciationScheduleEngine",
    "DisposalEntity",
    "DisposalRepository",
    "DisposalStatus",
    # disposal_entity
    "DisposalType",
    "DomainEvent",
    "DomainEventPublisher",
    # domain_events
    "DomainEventType",
    "FixedAsset",
    "FixedAssetAggregate",
    # aggregate_root
    "FixedAssetCollection",
    "FixedAssetEntity",
    "FixedAssetEntityRepository",
    "FixedAssetInvariantEnforcer",
    "FixedAssetInvariants",
    "FixedAssetInvariantsValidator",
    "FixedAssetRepository",
    "ImpairmentIndicator",
    "ImpairmentTest",
    # impairment_tester
    "ImpairmentTestResult",
    "ImpairmentTester",
    # invariants
    "InvariantResult",
    "RevaluationEntity",
    "RevaluationMethod",
    "RevaluationRepository",
    "RevaluationStatus",
    # revaluation_entity
    "RevaluationType",
    "TransferEntity",
    "TransferRepository",
    # transfer_entity
    "TransferStatus",
    "TransferType",
    "asset_entity",  # tambahkan agar checker tidak melaporkan error
]
