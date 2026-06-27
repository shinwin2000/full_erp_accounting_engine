#!/usr/bin/env python3
"""
Module: aggregate_root.py
Layer: Domain / Fixed Asset
Responsibility: Aggregate root untuk Fixed Asset management dengan semua method entity dasar dan aggregate root.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, ClassVar
from uuid import UUID, uuid4

from domain.fixed_asset.asset_entity import (
    AssetStatus,
    AssetType,
    FixedAsset,
)
from domain.fixed_asset.depreciation_schedule_engine import (
    DepreciationScheduleEngine,
)
from domain.fixed_asset.disposal_entity import DisposalEntity
from domain.fixed_asset.domain_events import (
    AssetAcquiredEvent,
    AssetDepreciationPostedEvent,
    AssetDisposedEvent,
    AssetFullyDepreciatedEvent,
    AssetRevaluatedEvent,
    AssetTransferredEvent,
    AssetUpdatedEvent,
    DomainEvent,
)
from domain.fixed_asset.revaluation_entity import (
    RevaluationEntity,
)
from domain.fixed_asset.transfer_entity import TransferEntity

logger = logging.getLogger(__name__)


# ============================================================================
# Fixed Asset Collection Aggregate
# ============================================================================


@dataclass
class FixedAssetCollection:
    asset_id: UUID
    legal_entity_id: UUID
    assets: dict[UUID, FixedAsset] = field(default_factory=dict)
    revaluations: list[RevaluationEntity] = field(default_factory=list)
    disposals: list[DisposalEntity] = field(default_factory=list)
    transfers: list[TransferEntity] = field(default_factory=list)
    depreciation_engine: DepreciationScheduleEngine = field(
        default_factory=DepreciationScheduleEngine
    )
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    version: int = 1

    # ==================== EVENT CONTRACT ====================
    _events: list[DomainEvent] = field(default_factory=list, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def register_event(self, event: DomainEvent) -> None:
        """Register a domain event."""
        self._events.append(event)

    def get_events(self) -> list[DomainEvent]:
        """Get all registered events."""
        return self._events.copy()

    def pull_events(self) -> list[DomainEvent]:
        """Pull and clear all events."""
        events = self._events.copy()
        self._events.clear()
        return events

    def clear_events(self) -> None:
        """Clear all events."""
        self._events.clear()

    # ==================== END EVENT CONTRACT ====================

    def __post_init__(self) -> None:
        self._take_snapshot()

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self.version,
            "asset_id": str(self.asset_id),
            "total_assets": len(self.assets),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self._snapshots.append(snapshot)
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        entry = {
            "action": action,
            "performed_by": performed_by,
            "timestamp": datetime.now(UTC).isoformat(),
            "version": self.version,
            "aggregate_id": str(self.asset_id),
            "details": details,
        }
        self._audit_trail.append(entry)

    # ==================== COMPATIBILITY ====================
    # Method _register_event (internal) dan property domain_events untuk backward compatibility

    def _register_event(self, event: DomainEvent) -> None:
        """Internal helper (kept for compatibility)."""
        self.register_event(event)

    @property
    def domain_events(self) -> list[DomainEvent]:
        """Compatibility property for code that uses self.domain_events."""
        return self.get_events()

    # ==================== ENTITY DASAR METHODS ====================

    def create(self, created_by: str) -> FixedAssetCollection:
        self._record_audit("CREATE", created_by, {"legal_entity_id": str(self.legal_entity_id)})
        return self

    def update(self, updated_by: str, **kwargs) -> FixedAssetCollection:
        data = self.to_dict()
        for key, value in kwargs.items():
            if key not in ("asset_id", "created_at", "version"):
                data[key] = value
        new_collection = FixedAssetCollection(
            asset_id=self.asset_id,
            legal_entity_id=self.legal_entity_id,
            assets=self.assets,
            revaluations=self.revaluations,
            disposals=self.disposals,
            transfers=self.transfers,
            depreciation_engine=self.depreciation_engine,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=updated_by,
            version=self.version + 1,
        )
        new_collection._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_collection

    def delete(self, deleted_by: str, reason: str | None = None) -> FixedAssetCollection:
        if len(self.assets) > 0:
            raise ValueError("Cannot delete collection with existing assets")
        new_collection = self._copy()
        new_collection.updated_at = datetime.now(UTC)
        new_collection.version = self.version + 1
        new_collection._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_collection

    def restore(self, restored_by: str) -> FixedAssetCollection:
        new_collection = self._copy()
        new_collection.updated_at = datetime.now(UTC)
        new_collection.version = self.version + 1
        new_collection._record_audit("RESTORE", restored_by, {})
        return new_collection

    def activate(self, activated_by: str) -> FixedAssetCollection:
        new_collection = self._copy()
        new_collection.updated_at = datetime.now(UTC)
        new_collection.version = self.version + 1
        new_collection._record_audit("ACTIVATE", activated_by, {})
        return new_collection

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> FixedAssetCollection:
        new_collection = self._copy()
        new_collection.updated_at = datetime.now(UTC)
        new_collection.version = self.version + 1
        new_collection._record_audit("DEACTIVATE", deactivated_by, {"reason": reason})
        return new_collection

    def lock(self, locked_by: str, reason: str) -> FixedAssetCollection:
        new_collection = self._copy()
        new_collection.updated_at = datetime.now(UTC)
        new_collection.version = self.version + 1
        new_collection._record_audit("LOCK", locked_by, {"reason": reason})
        return new_collection

    def unlock(self, unlocked_by: str) -> FixedAssetCollection:
        new_collection = self._copy()
        new_collection.updated_at = datetime.now(UTC)
        new_collection.version = self.version + 1
        new_collection._record_audit("UNLOCK", unlocked_by, {})
        return new_collection

    def validate(self) -> dict[str, Any]:
        errors = []
        codes = {}
        for asset in self.assets.values():
            if asset.asset_code in codes:
                errors.append(f"Duplicate asset code: {asset.asset_code}")
            codes[asset.asset_code] = asset.id
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "aggregate_id": str(self.asset_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": str(self.asset_id),
            "legal_entity_id": str(self.legal_entity_id),
            "total_assets": len(self.assets),
            "active_assets": len(self.get_active_assets()),
            "total_cost": str(self.get_total_cost()),
            "total_accumulated_depreciation": str(self.get_total_accumulated_depreciation()),
            "total_nbv": str(self.get_total_nbv()),
            "revaluations_count": len(self.revaluations),
            "disposals_count": len(self.disposals),
            "transfers_count": len(self.transfers),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": self.created_by,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FixedAssetCollection:
        assets = {}
        for asset_data in data.get("assets", []):
            asset = FixedAsset.from_dict(asset_data)
            assets[asset.id] = asset
        revaluations = [RevaluationEntity.from_dict(r) for r in data.get("revaluations", [])]
        disposals = [DisposalEntity.from_dict(d) for d in data.get("disposals", [])]
        transfers = [TransferEntity.from_dict(t) for t in data.get("transfers", [])]
        return cls(
            asset_id=UUID(data["asset_id"]),
            legal_entity_id=UUID(data["legal_entity_id"]),
            assets=assets,
            revaluations=revaluations,
            disposals=disposals,
            transfers=transfers,
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            created_by=data.get("created_by", "system"),
            version=data.get("version", 1),
        )

    def clone(self) -> FixedAssetCollection:
        new_id = uuid4()
        new_collection = FixedAssetCollection(
            asset_id=new_id,
            legal_entity_id=self.legal_entity_id,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            version=1,
        )
        for asset in self.assets.values():
            cloned_asset = asset.clone()
            new_collection = new_collection.add_asset(cloned_asset)
        new_collection._record_audit("CLONE", self.created_by, {"source": str(self.asset_id)})
        return new_collection

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "aggregate_id": str(self.asset_id),
            "total_assets": len(self.assets),
            "total_nbv": str(self.get_total_nbv()),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> FixedAssetCollection:
        new_collection = self._copy()
        new_collection.updated_at = datetime.now(UTC)
        new_collection.version = self.version + 1
        new_collection._record_audit("TOUCH", touched_by, {})
        return new_collection

    # ==================== AGGREGATE ROOT METHODS ====================

    def add_child(self, asset: FixedAsset, created_by: str) -> FixedAssetCollection:
        return self.add_asset(asset)

    def remove_child(self, asset_id: UUID, removed_by: str) -> FixedAssetCollection:
        return self.remove_asset(asset_id, removed_by)

    def can_post(self, asset_id: UUID) -> bool:
        asset = self.assets.get(asset_id)
        return asset is not None and asset.status == AssetStatus.ACTIVE

    def post(
        self,
        asset_id: UUID,
        amount: Decimal,
        posted_by: str,
        transaction_type: str = "depreciation",
    ) -> FixedAssetCollection:
        if transaction_type == "depreciation":
            return self.post_depreciation(
                asset_id, str(datetime.now(UTC).date()), amount, posted_by
            )
        elif transaction_type == "disposal":
            raise NotImplementedError("Use add_disposal for disposal posting")
        else:
            raise ValueError(f"Unknown transaction type: {transaction_type}")

    def can_approve(self, asset_id: UUID, user_role: str = "user") -> bool:
        asset = self.assets.get(asset_id)
        return asset is not None and user_role in ("finance_manager", "admin")

    def approve(self, asset_id: UUID, approved_by: str) -> FixedAssetCollection:
        if not self.can_approve(asset_id, "finance_manager"):
            raise ValueError(f"Cannot approve asset {asset_id}")
        return self

    def can_reject(self, asset_id: UUID, user_role: str = "user") -> bool:
        asset = self.assets.get(asset_id)
        return asset is not None

    def reject(self, asset_id: UUID, rejected_by: str, reason: str) -> FixedAssetCollection:
        return self

    def can_cancel(self, asset_id: UUID) -> bool:
        asset = self.assets.get(asset_id)
        return asset is not None and asset.status in (AssetStatus.UNDER_CONSTRUCTION,)

    def cancel(self, asset_id: UUID, cancelled_by: str, reason: str) -> FixedAssetCollection:
        if not self.can_cancel(asset_id):
            raise ValueError(f"Cannot cancel asset {asset_id}")
        return self

    def can_reverse(self, asset_id: UUID) -> bool:
        return False

    def reverse(self, asset_id: UUID, reversed_by: str, reason: str) -> FixedAssetCollection:
        raise NotImplementedError("Reverse not applicable for fixed asset")

    def can_close(self, asset_id: UUID) -> bool:
        asset = self.assets.get(asset_id)
        return asset is not None and asset.status == AssetStatus.DISPOSED

    def close(self, asset_id: UUID, closed_by: str, reason: str) -> FixedAssetCollection:
        if not self.can_close(asset_id):
            raise ValueError(f"Cannot close asset {asset_id}")
        return self

    def can_reopen(self, asset_id: UUID) -> bool:
        asset = self.assets.get(asset_id)
        return asset is not None and asset.status == AssetStatus.DISPOSED

    def reopen(self, asset_id: UUID, reopened_by: str, reason: str) -> FixedAssetCollection:
        if not self.can_reopen(asset_id):
            raise ValueError(f"Cannot reopen asset {asset_id}")
        return self

    def can_archive(self) -> bool:
        return len(self.assets) == 0

    def archive(self, archived_by: str, reason: str | None = None) -> FixedAssetCollection:
        if not self.can_archive():
            raise ValueError("Cannot archive collection with assets")
        new_collection = self._copy()
        new_collection.updated_at = datetime.now(UTC)
        new_collection.version = self.version + 1
        new_collection._record_audit("ARCHIVE", archived_by, {"reason": reason})
        return new_collection

    def can_unarchive(self) -> bool:
        return True

    def unarchive(self, unarchived_by: str) -> FixedAssetCollection:
        new_collection = self._copy()
        new_collection.updated_at = datetime.now(UTC)
        new_collection.version = self.version + 1
        new_collection._record_audit("UNARCHIVE", unarchived_by, {})
        return new_collection

    # ==================== QUERY METHODS ====================

    def get_asset(self, asset_id: UUID) -> FixedAsset | None:
        return self.assets.get(asset_id)

    def get_asset_by_code(self, asset_code: str) -> FixedAsset | None:
        for asset in self.assets.values():
            if asset.asset_code == asset_code:
                return asset
        return None

    def get_all_assets(self) -> list[FixedAsset]:
        return list(self.assets.values())

    def get_active_assets(self) -> list[FixedAsset]:
        return [a for a in self.assets.values() if a.status == AssetStatus.ACTIVE]

    def get_disposed_assets(self) -> list[FixedAsset]:
        return [a for a in self.assets.values() if a.status == AssetStatus.DISPOSED]

    def get_fully_depreciated_assets(self) -> list[FixedAsset]:
        return [a for a in self.assets.values() if a.is_fully_depreciated]

    def get_assets_by_type(self, asset_type: AssetType) -> list[FixedAsset]:
        return [a for a in self.assets.values() if a.asset_type == asset_type]

    def get_assets_by_category(self, category: str) -> list[FixedAsset]:
        return [a for a in self.assets.values() if a.category == category]

    def get_total_cost(self) -> Decimal:
        return sum(
            a.acquisition_cost for a in self.assets.values() if a.status != AssetStatus.DISPOSED
        )

    def get_total_accumulated_depreciation(self) -> Decimal:
        return sum(
            a.accumulated_depreciation
            for a in self.assets.values()
            if a.status != AssetStatus.DISPOSED
        )

    def get_total_nbv(self) -> Decimal:
        return sum(
            a.net_book_value for a in self.assets.values() if a.status != AssetStatus.DISPOSED
        )

    def get_revaluations_for_asset(self, asset_id: UUID) -> list[RevaluationEntity]:
        return [r for r in self.revaluations if r.asset_id == asset_id]

    def get_disposals_for_asset(self, asset_id: UUID) -> list[DisposalEntity]:
        return [d for d in self.disposals if d.asset_id == asset_id]

    def get_transfers_for_asset(self, asset_id: UUID) -> list[TransferEntity]:
        return [t for t in self.transfers if t.asset_id == asset_id]

    # ==================== COMMAND METHODS ====================

    def add_asset(self, asset: FixedAsset) -> FixedAssetCollection:
        if asset.id in self.assets:
            raise ValueError(f"Asset {asset.id} already exists")
        if self.get_asset_by_code(asset.asset_code):
            raise ValueError(f"Asset code {asset.asset_code} already exists")
        new_assets = self.assets.copy()
        new_assets[asset.id] = asset
        self.register_event(
            AssetAcquiredEvent(
                aggregate_id=self.asset_id,
                aggregate_version=self.version + 1,
                asset=asset,
                acquired_by=self.created_by,
            )
        )
        return FixedAssetCollection(
            asset_id=self.asset_id,
            legal_entity_id=self.legal_entity_id,
            assets=new_assets,
            revaluations=self.revaluations,
            disposals=self.disposals,
            transfers=self.transfers,
            depreciation_engine=self.depreciation_engine,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            version=self.version + 1,
        )

    def remove_asset(self, asset_id: UUID, removed_by: str) -> FixedAssetCollection:
        if asset_id not in self.assets:
            raise ValueError(f"Asset {asset_id} not found")
        asset = self.assets[asset_id]
        if asset.status != AssetStatus.DISPOSED:
            raise ValueError(f"Cannot remove non-disposed asset {asset.asset_code}")
        new_assets = {k: v for k, v in self.assets.items() if k != asset_id}
        return FixedAssetCollection(
            asset_id=self.asset_id,
            legal_entity_id=self.legal_entity_id,
            assets=new_assets,
            revaluations=self.revaluations,
            disposals=self.disposals,
            transfers=self.transfers,
            depreciation_engine=self.depreciation_engine,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=removed_by,
            version=self.version + 1,
        )

    def update_asset(self, asset: FixedAsset) -> FixedAssetCollection:
        if asset.id not in self.assets:
            raise ValueError(f"Asset {asset.id} not found")
        new_assets = self.assets.copy()
        new_assets[asset.id] = asset
        self.register_event(
            AssetUpdatedEvent(
                aggregate_id=self.asset_id,
                aggregate_version=self.version + 1,
                asset=asset,
                changes={"updated": True},
                updated_by=self.created_by,
            )
        )
        return FixedAssetCollection(
            asset_id=self.asset_id,
            legal_entity_id=self.legal_entity_id,
            assets=new_assets,
            revaluations=self.revaluations,
            disposals=self.disposals,
            transfers=self.transfers,
            depreciation_engine=self.depreciation_engine,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            version=self.version + 1,
        )

    def calculate_depreciation(self, asset_id: UUID, as_of_date: datetime) -> Decimal:
        asset = self.assets.get(asset_id)
        if not asset:
            raise ValueError(f"Asset {asset_id} not found")
        return self.depreciation_engine.calculate_depreciation_as_of(asset, as_of_date.date())

    def post_depreciation(
        self, asset_id: UUID, period: str, amount: Decimal, posted_by: str
    ) -> FixedAssetCollection:
        asset = self.assets.get(asset_id)
        if not asset:
            raise ValueError(f"Asset {asset_id} not found")
        if amount <= 0:
            raise ValueError("Depreciation amount must be positive")
        updated_asset = asset.record_depreciation(period, amount, UUID(int=0))
        self.register_event(
            AssetDepreciationPostedEvent(
                aggregate_id=self.asset_id,
                aggregate_version=self.version + 1,
                asset=updated_asset,
                period=period,
                amount=amount,
                posted_by=posted_by,
            )
        )
        if updated_asset.is_fully_depreciated and not asset.is_fully_depreciated:
            self.register_event(
                AssetFullyDepreciatedEvent(
                    aggregate_id=self.asset_id,
                    aggregate_version=self.version + 1,
                    asset=updated_asset,
                )
            )
        return self.update_asset(updated_asset)

    def add_revaluation(
        self, asset_id: UUID, revaluation: RevaluationEntity
    ) -> FixedAssetCollection:
        asset = self.assets.get(asset_id)
        if not asset:
            raise ValueError(f"Asset {asset_id} not found")
        updated_asset = asset.apply_revaluation(
            revaluation.new_value, revaluation.revaluation_method.value, revaluation.approved_by
        )
        new_assets = self.assets.copy()
        new_assets[asset_id] = updated_asset
        new_revaluations = self.revaluations + [revaluation]
        self.register_event(
            AssetRevaluatedEvent(
                aggregate_id=self.asset_id,
                aggregate_version=self.version + 1,
                asset=updated_asset,
                old_value=revaluation.old_value,
                new_value=revaluation.new_value,
                revaluation_surplus=updated_asset.revaluation_surplus,
                revaluation_method=revaluation.revaluation_method.value,
                approved_by=str(revaluation.approved_by) if revaluation.approved_by else "",
            )
        )
        return FixedAssetCollection(
            asset_id=self.asset_id,
            legal_entity_id=self.legal_entity_id,
            assets=new_assets,
            revaluations=new_revaluations,
            disposals=self.disposals,
            transfers=self.transfers,
            depreciation_engine=self.depreciation_engine,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            version=self.version + 1,
        )

    def add_disposal(self, asset_id: UUID, disposal: DisposalEntity) -> FixedAssetCollection:
        asset = self.assets.get(asset_id)
        if not asset:
            raise ValueError(f"Asset {asset_id} not found")
        if asset.is_disposed:
            raise ValueError(f"Asset {asset.asset_code} is already disposed")
        updated_asset = asset.dispose(
            disposal.disposal_date,
            disposal.disposal_type.value,
            disposal.proceeds,
            disposal.reason,
            disposal.disposed_by,
        )
        new_assets = self.assets.copy()
        new_assets[asset_id] = updated_asset
        new_disposals = self.disposals + [disposal]
        self.register_event(
            AssetDisposedEvent(
                aggregate_id=self.asset_id,
                aggregate_version=self.version + 1,
                asset=updated_asset,
                disposal_date=disposal.disposal_date,
                disposal_type=disposal.disposal_type.value,
                proceeds=disposal.proceeds,
                gain_loss=disposal.gain_loss,
                disposed_by=str(disposal.disposed_by) if disposal.disposed_by else "system",
            )
        )
        return FixedAssetCollection(
            asset_id=self.asset_id,
            legal_entity_id=self.legal_entity_id,
            assets=new_assets,
            revaluations=self.revaluations,
            disposals=new_disposals,
            transfers=self.transfers,
            depreciation_engine=self.depreciation_engine,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            version=self.version + 1,
        )

    def add_transfer(self, asset_id: UUID, transfer: TransferEntity) -> FixedAssetCollection:
        asset = self.assets.get(asset_id)
        if not asset:
            raise ValueError(f"Asset {asset_id} not found")
        updated_asset = asset.transfer(transfer.destination, transfer.completed_by or UUID(int=0))
        new_assets = self.assets.copy()
        new_assets[asset_id] = updated_asset
        new_transfers = self.transfers + [transfer]
        self.register_event(
            AssetTransferredEvent(
                aggregate_id=self.asset_id,
                aggregate_version=self.version + 1,
                source=transfer.source,
                asset=updated_asset,
                transfer_type=transfer.transfer_type.value,
                destination=transfer.destination,
                transferred_by=str(transfer.completed_by) if transfer.completed_by else "system",
            )
        )
        return FixedAssetCollection(
            asset_id=self.asset_id,
            legal_entity_id=self.legal_entity_id,
            assets=new_assets,
            revaluations=self.revaluations,
            disposals=self.disposals,
            transfers=new_transfers,
            depreciation_engine=self.depreciation_engine,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            version=self.version + 1,
        )

    # ==================== STATISTICS ====================

    def get_summary(self) -> dict[str, Any]:
        return {
            "total_assets": len(self.assets),
            "active_assets": len(self.get_active_assets()),
            "disposed_assets": len(self.get_disposed_assets()),
            "fully_depreciated": len(self.get_fully_depreciated_assets()),
            "total_cost": str(self.get_total_cost()),
            "total_accumulated_depreciation": str(self.get_total_accumulated_depreciation()),
            "total_nbv": str(self.get_total_nbv()),
            "revaluations_count": len(self.revaluations),
            "disposals_count": len(self.disposals),
            "transfers_count": len(self.transfers),
        }

    # ==================== PRIVATE HELPERS ====================

    def _copy(self) -> FixedAssetCollection:
        return FixedAssetCollection(
            asset_id=self.asset_id,
            legal_entity_id=self.legal_entity_id,
            assets=self.assets.copy(),
            revaluations=self.revaluations.copy(),
            disposals=self.disposals.copy(),
            transfers=self.transfers.copy(),
            depreciation_engine=self.depreciation_engine,
            created_at=self.created_at,
            updated_at=self.updated_at,
            created_by=self.created_by,
            version=self.version,
        )


# ============================================================================
# Single Asset Aggregate (for Service Layer)
# ============================================================================


class FixedAssetAggregate:
    """Aggregate root for a single fixed asset."""

    def __init__(self, asset: FixedAsset | None = None):
        self._asset = asset
        self._events: list[DomainEvent] = []

    # ==================== EVENT CONTRACT ====================

    def register_event(self, event: DomainEvent) -> None:
        self._events.append(event)

    def get_events(self) -> list[DomainEvent]:
        return self._events.copy()

    def pull_events(self) -> list[DomainEvent]:
        events = self._events.copy()
        self._events.clear()
        return events

    def clear_events(self) -> None:
        self._events.clear()

    # ==================== END EVENT CONTRACT ====================

    @property
    def asset(self) -> FixedAsset:
        if self._asset is None:
            raise ValueError("Asset not loaded")
        return self._asset

    @property
    def id(self) -> UUID:
        return self._asset.id if self._asset else uuid4()

    @property
    def domain_events(self) -> list[DomainEvent]:
        """Compatibility property."""
        return self.get_events()

    def pop_events(self) -> list[DomainEvent]:
        """Alias for pull_events (compatibility)."""
        return self.pull_events()

    def load(self, asset: FixedAsset) -> None:
        self._asset = asset

    def create(self, asset: FixedAsset, created_by: str) -> None:
        self._asset = asset
        self.register_event(
            AssetAcquiredEvent(
                aggregate_id=asset.id,
                aggregate_version=1,
                asset=asset,
                acquired_by=created_by,
            )
        )

    def update_name(self, new_name: str, user_id: UUID) -> None:
        if not self._asset:
            raise ValueError("No asset loaded")
        self._asset = self._asset.update_name(new_name, user_id)
        self.register_event(
            AssetUpdatedEvent(
                aggregate_id=self._asset.id,
                aggregate_version=self._asset.version,
                asset=self._asset,
                changes={"name": new_name},
                updated_by=str(user_id),
            )
        )

    def update_description(self, new_description: str | None, user_id: UUID) -> None:
        if not self._asset:
            raise ValueError("No asset loaded")
        self._asset = self._asset.update_description(new_description, user_id)
        self.register_event(
            AssetUpdatedEvent(
                aggregate_id=self._asset.id,
                aggregate_version=self._asset.version,
                asset=self._asset,
                changes={"description": new_description},
                updated_by=str(user_id),
            )
        )

    def update_location(self, new_location: str, user_id: UUID) -> None:
        if not self._asset:
            raise ValueError("No asset loaded")
        self._asset = self._asset.transfer(new_location, user_id)
        self.register_event(
            AssetUpdatedEvent(
                aggregate_id=self._asset.id,
                aggregate_version=self._asset.version,
                asset=self._asset,
                changes={"location": new_location},
                updated_by=str(user_id),
            )
        )

    def update_responsible_person(self, person_id: UUID | None, user_id: UUID) -> None:
        if not self._asset:
            raise ValueError("No asset loaded")
        self._asset = self._asset.change_responsible_person(person_id, user_id)
        self.register_event(
            AssetUpdatedEvent(
                aggregate_id=self._asset.id,
                aggregate_version=self._asset.version,
                asset=self._asset,
                changes={"responsible_person": str(person_id) if person_id else None},
                updated_by=str(user_id),
            )
        )

    def record_depreciation(self, period: str, amount: Decimal, posted_by: UUID) -> None:
        if not self._asset:
            raise ValueError("No asset loaded")
        self._asset = self._asset.record_depreciation(period, amount, posted_by)
        self.register_event(
            AssetDepreciationPostedEvent(
                aggregate_id=self._asset.id,
                aggregate_version=self._asset.version,
                asset=self._asset,
                period=period,
                amount=amount,
                posted_by=str(posted_by),
            )
        )

    def apply_revaluation(self, new_value: Decimal, method: str, approved_by: UUID) -> None:
        if not self._asset:
            raise ValueError("No asset loaded")
        self._asset = self._asset.apply_revaluation(new_value, method, approved_by)
        self.register_event(
            AssetRevaluatedEvent(
                aggregate_id=self._asset.id,
                aggregate_version=self._asset.version,
                asset=self._asset,
                old_value=Decimal("0"),
                new_value=new_value,
                revaluation_surplus=self._asset.revaluation_surplus,
                revaluation_method=method,
                approved_by=str(approved_by),
            )
        )

    def dispose(
        self,
        disposal_date: date,
        disposal_type: str,
        proceeds: Decimal,
        reason: str,
        user_id: UUID,
        gain_loss: Decimal,
    ) -> None:
        if not self._asset:
            raise ValueError("No asset loaded")
        self._asset = self._asset.dispose(disposal_date, disposal_type, proceeds, reason, user_id)
        self.register_event(
            AssetDisposedEvent(
                aggregate_id=self._asset.id,
                aggregate_version=self._asset.version,
                asset=self._asset,
                disposal_date=disposal_date,
                disposal_type=disposal_type,
                proceeds=proceeds,
                gain_loss=gain_loss,
                disposed_by=str(user_id),
            )
        )


# ============================================================================
# Repository Implementation
# ============================================================================


class FixedAssetRepository:
    _storage: ClassVar[dict[UUID, FixedAssetCollection]] = {}

    @classmethod
    async def get_by_legal_entity(cls, legal_entity_id: UUID) -> FixedAssetCollection | None:
        for collection in cls._storage.values():
            if collection.legal_entity_id == legal_entity_id:
                return collection
        return None

    @classmethod
    async def get_by_id(cls, collection_id: UUID) -> FixedAssetCollection | None:
        return cls._storage.get(collection_id)

    @classmethod
    async def get_asset_by_id(cls, asset_id: UUID, legal_entity_id: UUID) -> FixedAsset | None:
        collection = await cls.get_by_legal_entity(legal_entity_id)
        if not collection:
            return None
        return collection.get_asset(asset_id)

    @classmethod
    async def get_asset_by_code(cls, asset_code: str, legal_entity_id: UUID) -> FixedAsset | None:
        collection = await cls.get_by_legal_entity(legal_entity_id)
        if not collection:
            return None
        return collection.get_asset_by_code(asset_code)

    @classmethod
    async def get_all(cls) -> list[FixedAssetCollection]:
        return list(cls._storage.values())

    @classmethod
    async def save(cls, collection: FixedAssetCollection) -> None:
        cls._storage[collection.asset_id] = collection

    @classmethod
    async def delete(cls, collection_id: UUID) -> None:
        cls._storage.pop(collection_id, None)

    @classmethod
    async def exists(cls, collection_id: UUID) -> bool:
        return collection_id in cls._storage

    @classmethod
    async def count(cls) -> int:
        return len(cls._storage)

    @classmethod
    async def list(cls, limit: int = 100, offset: int = 0) -> list[FixedAssetCollection]:
        collections = list(cls._storage.values())
        return collections[offset : offset + limit]

    @classmethod
    async def clear(cls) -> None:
        cls._storage.clear()


__all__ = [
    "FixedAssetAggregate",
    "FixedAssetCollection",
    "FixedAssetRepository",
]
