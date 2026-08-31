#!/usr/bin/env python3
"""
Module: aggregate_root.py
Layer: Domain / Intangible Asset
Responsibility: Aggregate root untuk intangible asset dengan semua method entity dasar dan aggregate root.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, ClassVar
from uuid import UUID, uuid4

from domain.intangible_asset.amortization_method_enum import AmortizationMethod
from domain.intangible_asset.amortization_schedule_engine import (
    AmortizationSchedule,
    AmortizationScheduleEngine,
)
from domain.intangible_asset.asset_entity import (
    IntangibleAssetEntity,
    IntangibleAssetStatus,
    IntangibleAssetType,
)
from domain.intangible_asset.domain_events import (
    DomainEvent,
    IntangibleAssetAcquiredEvent,
    IntangibleAssetAmortizationPostedEvent,
    IntangibleAssetDisposedEvent,
    IntangibleAssetFullyAmortizedEvent,
    IntangibleAssetImpairedEvent,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Intangible Asset Aggregate
# ============================================================================


@dataclass
class IntangibleAsset:
    aggregate_id: UUID
    legal_entity_id: UUID
    assets: dict[UUID, IntangibleAssetEntity] = field(default_factory=dict)
    amortization_engine: AmortizationScheduleEngine = field(
        default_factory=AmortizationScheduleEngine
    )
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    version: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    _events: ClassVar[list[DomainEvent]] = []
    _audit_trail: ClassVar[list[dict[str, Any]]] = []
    _snapshots: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        self._take_snapshot()

    def _validate(self) -> None:
        if self.version < 1:
            raise ValueError(f"Version must be >= 1: {self.version}")
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))
        if self.updated_at.tzinfo is None:
            object.__setattr__(self, "updated_at", self.updated_at.replace(tzinfo=UTC))

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self.version,
            "aggregate_id": str(self.aggregate_id),
            "legal_entity_id": str(self.legal_entity_id),
            "total_assets": len(self.assets),
            "active_assets": len(self.get_active_assets()),
            "total_nbv": str(self.get_total_nbv()),
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
            "aggregate_id": str(self.aggregate_id),
            "details": details,
        }
        self._audit_trail.append(entry)

    def _register_event(self, event: DomainEvent) -> None:
        self._events.append(event)

    # ==================== ENTITY DASAR METHODS ====================

    def create(self, created_by: str) -> IntangibleAsset:
        self._record_audit("CREATE", created_by, {"legal_entity_id": str(self.legal_entity_id)})
        return self

    def update(self, updated_by: str, **kwargs) -> IntangibleAsset:
        data = self.to_dict()
        for key, value in kwargs.items():
            if key not in ("aggregate_id", "created_at", "created_by", "version"):
                data[key] = value
        new_agg = IntangibleAsset(
            aggregate_id=self.aggregate_id,
            legal_entity_id=self.legal_entity_id,
            assets=self.assets,
            amortization_engine=self.amortization_engine,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=updated_by,
            version=self.version + 1,
            metadata=data.get("metadata", self.metadata),
        )
        new_agg._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_agg

    def delete(self, deleted_by: str, reason: str | None = None) -> IntangibleAsset:
        if len(self.assets) > 0:
            raise ValueError("Cannot delete aggregate with existing assets")
        new_agg = self._copy()
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_agg

    def restore(self, restored_by: str) -> IntangibleAsset:
        new_agg = self._copy()
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("RESTORE", restored_by, {})
        return new_agg

    def activate(self, activated_by: str) -> IntangibleAsset:
        new_agg = self._copy()
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("ACTIVATE", activated_by, {})
        return new_agg

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> IntangibleAsset:
        new_agg = self._copy()
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("DEACTIVATE", deactivated_by, {"reason": reason})
        return new_agg

    def lock(self, locked_by: str, reason: str) -> IntangibleAsset:
        new_agg = self._copy()
        new_agg.metadata["locked_by"] = locked_by
        new_agg.metadata["locked_at"] = datetime.now(UTC).isoformat()
        new_agg.metadata["lock_reason"] = reason
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("LOCK", locked_by, {"reason": reason})
        return new_agg

    def unlock(self, unlocked_by: str) -> IntangibleAsset:
        new_agg = self._copy()
        new_agg.metadata.pop("locked_by", None)
        new_agg.metadata.pop("locked_at", None)
        new_agg.metadata.pop("lock_reason", None)
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("UNLOCK", unlocked_by, {})
        return new_agg

    def validate(self) -> dict[str, Any]:
        errors = []
        codes = set()
        for asset in self.assets.values():
            if asset.asset_code in codes:
                errors.append(f"Duplicate asset code: {asset.asset_code}")
            codes.add(asset.asset_code)
            try:
                asset._validate()
            except ValueError as e:
                errors.append(str(e))
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "aggregate_id": str(self.aggregate_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "aggregate_id": str(self.aggregate_id),
            "legal_entity_id": str(self.legal_entity_id),
            "total_assets": len(self.assets),
            "active_assets": len(self.get_active_assets()),
            "total_cost": str(self.get_total_cost()),
            "total_accumulated_amortization": str(self.get_total_accumulated_amortization()),
            "total_nbv": str(self.get_total_nbv()),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": self.created_by,
            "version": self.version,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IntangibleAsset:
        created_at = datetime.fromisoformat(data["created_at"])
        updated_at = datetime.fromisoformat(data["updated_at"])
        return cls(
            aggregate_id=UUID(data["aggregate_id"]),
            legal_entity_id=UUID(data["legal_entity_id"]),
            created_at=created_at,
            updated_at=updated_at,
            created_by=data.get("created_by", "system"),
            version=data.get("version", 1),
            metadata=data.get("metadata", {}),
        )

    def clone(self) -> IntangibleAsset:
        new_id = uuid4()
        now = datetime.now(UTC)
        cloned = IntangibleAsset(
            aggregate_id=new_id,
            legal_entity_id=self.legal_entity_id,
            created_at=now,
            updated_at=now,
            created_by=self.created_by,
            version=1,
        )
        for asset in self.assets.values():
            cloned_asset = asset.clone()
            cloned = cloned.add_asset(cloned_asset)
        cloned._record_audit("CLONE", self.created_by, {"source": str(self.aggregate_id)})
        return cloned

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "aggregate_id": str(self.aggregate_id),
            "total_assets": len(self.assets),
            "total_nbv": str(self.get_total_nbv()),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> IntangibleAsset:
        new_agg = self._copy()
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("TOUCH", touched_by, {})
        return new_agg

    # ==================== AGGREGATE ROOT METHODS ====================

    def add_child(self, asset: IntangibleAssetEntity, created_by: str) -> IntangibleAsset:
        return self.add_asset(asset)

    def remove_child(self, asset_id: UUID, removed_by: str) -> IntangibleAsset:
        return self.remove_asset(asset_id, removed_by)

    def can_post(self, asset_id: UUID) -> bool:
        asset = self.assets.get(asset_id)
        return asset is not None and asset.status != IntangibleAssetStatus.DISPOSED

    def post(
        self,
        asset_id: UUID,
        amount: Decimal,
        posted_by: str,
        transaction_type: str = "amortization",
    ) -> IntangibleAsset:
        if transaction_type == "amortization":
            return self.post_amortization(asset_id, "monthly", amount, posted_by)
        elif transaction_type == "impairment":
            return self.impair_asset(asset_id, amount, posted_by)
        else:
            raise ValueError(f"Unknown transaction type: {transaction_type}")

    def can_approve(self, asset_id: UUID, user_role: str = "user") -> bool:
        asset = self.assets.get(asset_id)
        return asset is not None and user_role in ("finance_manager", "admin")

    def approve(self, asset_id: UUID, approved_by: str) -> IntangibleAsset:
        if not self.can_approve(asset_id, "finance_manager"):
            raise ValueError(f"Cannot approve asset {asset_id}")
        return self

    def can_reject(self, asset_id: UUID, user_role: str = "user") -> bool:
        asset = self.assets.get(asset_id)
        return asset is not None

    def reject(self, asset_id: UUID, rejected_by: str, reason: str) -> IntangibleAsset:
        self._record_audit("REJECT", rejected_by, {"asset_id": str(asset_id), "reason": reason})
        return self

    def can_cancel(self, asset_id: UUID) -> bool:
        asset = self.assets.get(asset_id)
        return asset is not None and asset.status in (IntangibleAssetStatus.UNDER_DEVELOPMENT,)

    def cancel(self, asset_id: UUID, cancelled_by: str, reason: str) -> IntangibleAsset:
        if not self.can_cancel(asset_id):
            raise ValueError(f"Cannot cancel asset {asset_id}")
        return self.dispose_asset(asset_id, datetime.now(UTC), Decimal(0), cancelled_by)

    def can_reverse(self, asset_id: UUID) -> bool:
        return False

    def reverse(self, asset_id: UUID, reversed_by: str, reason: str) -> IntangibleAsset:
        raise NotImplementedError("Reverse not applicable for intangible asset")

    def can_close(self, asset_id: UUID) -> bool:
        asset = self.assets.get(asset_id)
        return asset is not None and asset.status == IntangibleAssetStatus.FULLY_AMORTIZED

    def close(self, asset_id: UUID, closed_by: str, reason: str) -> IntangibleAsset:
        if not self.can_close(asset_id):
            raise ValueError(f"Cannot close asset {asset_id}")
        return self

    def can_reopen(self, asset_id: UUID) -> bool:
        return False

    def reopen(self, asset_id: UUID, reopened_by: str, reason: str) -> IntangibleAsset:
        raise NotImplementedError("Reopen not applicable for intangible asset")

    def can_archive(self) -> bool:
        return len(self.assets) == 0

    def archive(self, archived_by: str, reason: str | None = None) -> IntangibleAsset:
        if not self.can_archive():
            raise ValueError("Cannot archive aggregate with assets")
        new_agg = self._copy()
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("ARCHIVE", archived_by, {"reason": reason})
        return new_agg

    def can_unarchive(self) -> bool:
        return True

    def unarchive(self, unarchived_by: str) -> IntangibleAsset:
        new_agg = self._copy()
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("UNARCHIVE", unarchived_by, {})
        return new_agg

    # ==================== EVENT METHODS ====================

    def register_event(self, event: DomainEvent) -> None:
        self._register_event(event)

    def get_events(self) -> list[DomainEvent]:
        return self._events.copy()

    def pull_events(self) -> list[DomainEvent]:
        events = self._events.copy()
        self._events.clear()
        return events

    def clear_events(self) -> None:
        self._events.clear()

    # ==================== ASSET MANAGEMENT ====================

    def add_asset(self, asset: IntangibleAssetEntity) -> IntangibleAsset:
        if asset.asset_id in self.assets:
            raise ValueError(f"Asset {asset.asset_id} already exists")

        for existing in self.assets.values():
            if existing.asset_code == asset.asset_code:
                raise ValueError(f"Asset code '{asset.asset_code}' already exists")

        new_assets = dict(self.assets)
        new_assets[asset.asset_id] = asset

        self._register_event(
            IntangibleAssetAcquiredEvent(
                aggregate_id=self.aggregate_id,
                aggregate_version=self.version + 1,
                asset=asset,
                acquired_by=self.created_by,
            )
        )

        return IntangibleAsset(
            aggregate_id=self.aggregate_id,
            legal_entity_id=self.legal_entity_id,
            assets=new_assets,
            amortization_engine=self.amortization_engine,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            version=self.version + 1,
            metadata=self.metadata,
        )

    def update_asset(self, asset: IntangibleAssetEntity) -> IntangibleAsset:
        if asset.asset_id not in self.assets:
            raise ValueError(f"Asset {asset.asset_id} not found")

        new_assets = dict(self.assets)
        new_assets[asset.asset_id] = asset

        return IntangibleAsset(
            aggregate_id=self.aggregate_id,
            legal_entity_id=self.legal_entity_id,
            assets=new_assets,
            amortization_engine=self.amortization_engine,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            version=self.version + 1,
            metadata=self.metadata,
        )

    def remove_asset(self, asset_id: UUID, removed_by: str) -> IntangibleAsset:
        if asset_id not in self.assets:
            raise ValueError(f"Asset {asset_id} not found")

        asset = self.assets[asset_id]
        if asset.status != IntangibleAssetStatus.DISPOSED:
            raise ValueError(f"Cannot remove non-disposed asset {asset.asset_code}")

        new_assets = {k: v for k, v in self.assets.items() if k != asset_id}

        return IntangibleAsset(
            aggregate_id=self.aggregate_id,
            legal_entity_id=self.legal_entity_id,
            assets=new_assets,
            amortization_engine=self.amortization_engine,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=removed_by,
            version=self.version + 1,
            metadata=self.metadata,
        )

    def get_asset(self, asset_id: UUID) -> IntangibleAssetEntity | None:
        return self.assets.get(asset_id)

    def get_asset_by_code(self, asset_code: str) -> IntangibleAssetEntity | None:
        for asset in self.assets.values():
            if asset.asset_code == asset_code:
                return asset
        return None

    def get_assets_by_type(self, asset_type: IntangibleAssetType) -> list[IntangibleAssetEntity]:
        return [a for a in self.assets.values() if a.asset_type == asset_type]

    def get_assets_by_status(self, status: IntangibleAssetStatus) -> list[IntangibleAssetEntity]:
        return [a for a in self.assets.values() if a.status == status]

    def get_active_assets(self) -> list[IntangibleAssetEntity]:
        return [a for a in self.assets.values() if a.status != IntangibleAssetStatus.DISPOSED]

    def get_assets_amortizable(self) -> list[IntangibleAssetEntity]:
        return [
            a
            for a in self.assets.values()
            if not a.has_indefinite_life and a.status != IntangibleAssetStatus.DISPOSED
        ]

    # ==================== AMORTIZATION ====================

    def calculate_amortization(self, asset_id: UUID, as_of_date: datetime) -> Decimal:
        asset = self.assets.get(asset_id)
        if not asset:
            raise ValueError(f"Asset {asset_id} not found")
        return self.amortization_engine.calculate_amortization(asset, as_of_date)

    def post_amortization(
        self, asset_id: UUID, period: str, amount: Decimal, posted_by: str
    ) -> IntangibleAsset:
        asset = self.assets.get(asset_id)
        if not asset:
            raise ValueError(f"Asset {asset_id} not found")

        updated_asset = asset.record_amortization(period, amount, posted_by)
        new_assets = dict(self.assets)
        new_assets[asset_id] = updated_asset

        self._register_event(
            IntangibleAssetAmortizationPostedEvent(
                aggregate_id=self.aggregate_id,
                aggregate_version=self.version + 1,
                asset=updated_asset,
                period=period,
                amount=amount,
                posted_by=posted_by,
            )
        )

        if updated_asset.is_fully_amortized and not asset.is_fully_amortized:
            self._register_event(
                IntangibleAssetFullyAmortizedEvent(
                    aggregate_id=self.aggregate_id,
                    aggregate_version=self.version + 1,
                    asset=updated_asset,
                )
            )

        # --- AUDIT TRAIL ---
        self._record_audit("POST_AMORTIZATION", posted_by, {
            "asset_id": str(asset_id),
            "period": period,
            "amount": str(amount),
            "asset_code": asset.asset_code,
        })

        return IntangibleAsset(
            aggregate_id=self.aggregate_id,
            legal_entity_id=self.legal_entity_id,
            assets=new_assets,
            amortization_engine=self.amortization_engine,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            version=self.version + 1,
            metadata=self.metadata,
        )

    def get_monthly_amortization(self, asset_id: UUID) -> Decimal:
        asset = self.assets.get(asset_id)
        if not asset:
            raise ValueError(f"Asset {asset_id} not found")
        return self.amortization_engine.get_monthly_amortization(asset)

    def get_amortization_schedule(self, asset_id: UUID) -> AmortizationSchedule:
        asset = self.assets.get(asset_id)
        if not asset:
            raise ValueError(f"Asset {asset_id} not found")
        if asset.amortization_method == AmortizationMethod.STRAIGHT_LINE:
            return self.amortization_engine.calculate_straight_line(asset)
        elif asset.amortization_method == AmortizationMethod.DECLINING_BALANCE:
            return self.amortization_engine.calculate_declining_balance(asset)
        else:
            return self.amortization_engine.calculate_straight_line(asset)

    # ==================== IMPAIRMENT ====================

    def impair_asset(
        self, asset_id: UUID, impairment_loss: Decimal, impaired_by: str
    ) -> IntangibleAsset:
        asset = self.assets.get(asset_id)
        if not asset:
            raise ValueError(f"Asset {asset_id} not found")

        updated_asset = asset.impair(impairment_loss, impaired_by)
        new_assets = dict(self.assets)
        new_assets[asset_id] = updated_asset

        self._register_event(
            IntangibleAssetImpairedEvent(
                aggregate_id=self.aggregate_id,
                aggregate_version=self.version + 1,
                asset=updated_asset,
                impairment_loss=impairment_loss,
                impaired_by=impaired_by,
            )
        )

        # --- AUDIT TRAIL ---
        self._record_audit("IMPAIR_ASSET", impaired_by, {
            "asset_id": str(asset_id),
            "impairment_loss": str(impairment_loss),
            "asset_code": asset.asset_code,
        })

        return IntangibleAsset(
            aggregate_id=self.aggregate_id,
            legal_entity_id=self.legal_entity_id,
            assets=new_assets,
            amortization_engine=self.amortization_engine,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            version=self.version + 1,
            metadata=self.metadata,
        )

    def reverse_impairment(
        self, asset_id: UUID, reversal_amount: Decimal, reversed_by: str
    ) -> IntangibleAsset:
        asset = self.assets.get(asset_id)
        if not asset:
            raise ValueError(f"Asset {asset_id} not found")
        if asset.status != IntangibleAssetStatus.IMPAIRED:
            raise ValueError(f"Asset {asset.asset_code} is not impaired")
        if reversal_amount <= 0:
            raise ValueError(f"Reversal amount must be positive: {reversal_amount}")
        if reversal_amount > asset.nbv:
            raise ValueError(f"Reversal amount {reversal_amount} exceeds NBV {asset.nbv}")

        new_cost = asset.cost + reversal_amount
        new_nbv = asset.nbv + reversal_amount

        updated_asset = IntangibleAssetEntity(
            asset_id=asset.asset_id,
            legal_entity_id=asset.legal_entity_id,
            asset_code=asset.asset_code,
            asset_name=asset.asset_name,
            asset_type=asset.asset_type,
            acquisition_date=asset.acquisition_date,
            cost=new_cost,
            currency=asset.currency,
            residual_value=asset.residual_value,
            useful_life_years=asset.useful_life_years,
            amortization_method=asset.amortization_method,
            accumulated_amortization=asset.accumulated_amortization,
            nbv=new_nbv,
            status=IntangibleAssetStatus.ACTIVE,
            legal_owner=asset.legal_owner,
            registration_number=asset.registration_number,
            expiry_date=asset.expiry_date,
            supplier_id=asset.supplier_id,
            supplier_name=asset.supplier_name,
            last_amortization_date=asset.last_amortization_date,
            created_at=asset.created_at,
            updated_at=datetime.now(UTC),
            created_by=reversed_by,
            version=asset.version + 1,
        )
        new_assets = dict(self.assets)
        new_assets[asset_id] = updated_asset

        # --- AUDIT TRAIL ---
        self._record_audit("REVERSE_IMPAIRMENT", reversed_by, {
            "asset_id": str(asset_id),
            "reversal_amount": str(reversal_amount),
            "asset_code": asset.asset_code,
        })

        # Event untuk reversal impairment (opsional, tapi lebih baik ada)
        self._register_event(
            IntangibleAssetImpairedEvent(  # Reuse event type, or create separate
                aggregate_id=self.aggregate_id,
                aggregate_version=self.version + 1,
                asset=updated_asset,
                impairment_loss=-reversal_amount,  # negative means reversal
                impaired_by=reversed_by,
            )
        )

        return IntangibleAsset(
            aggregate_id=self.aggregate_id,
            legal_entity_id=self.legal_entity_id,
            assets=new_assets,
            amortization_engine=self.amortization_engine,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            version=self.version + 1,
            metadata=self.metadata,
        )

    # ==================== DISPOSAL ====================

    def dispose_asset(
        self, asset_id: UUID, disposal_date: datetime, proceeds: Decimal, disposed_by: str
    ) -> IntangibleAsset:
        asset = self.assets.get(asset_id)
        if not asset:
            raise ValueError(f"Asset {asset_id} not found")

        gain_loss = proceeds - asset.nbv
        updated_asset = asset.dispose(disposal_date, proceeds, disposed_by)
        new_assets = dict(self.assets)
        new_assets[asset_id] = updated_asset

        self._register_event(
            IntangibleAssetDisposedEvent(
                aggregate_id=self.aggregate_id,
                aggregate_version=self.version + 1,
                asset=updated_asset,
                disposal_date=disposal_date,
                proceeds=proceeds,
                gain_loss=gain_loss,
                disposed_by=disposed_by,
            )
        )

        # --- AUDIT TRAIL ---
        self._record_audit("DISPOSE_ASSET", disposed_by, {
            "asset_id": str(asset_id),
            "disposal_date": disposal_date.isoformat(),
            "proceeds": str(proceeds),
            "gain_loss": str(gain_loss),
            "asset_code": asset.asset_code,
        })

        return IntangibleAsset(
            aggregate_id=self.aggregate_id,
            legal_entity_id=self.legal_entity_id,
            assets=new_assets,
            amortization_engine=self.amortization_engine,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            version=self.version + 1,
            metadata=self.metadata,
        )

    # ==================== FINANCIAL SUMMARY ====================

    def get_total_cost(self) -> Decimal:
        return sum(
            (a.cost for a in self.assets.values() if a.status != IntangibleAssetStatus.DISPOSED),
            Decimal('0')
        )

    def get_total_accumulated_amortization(self) -> Decimal:
        return sum(
            (a.accumulated_amortization for a in self.assets.values() if a.status != IntangibleAssetStatus.DISPOSED),
            Decimal('0')
        )

    def get_total_nbv(self) -> Decimal:
        return sum(
            (a.nbv for a in self.assets.values() if a.status != IntangibleAssetStatus.DISPOSED),
            Decimal('0')
        )

    def get_total_impairment(self) -> Decimal:
        total_impairment = Decimal(0)
        for a in self.assets.values():
            if a.status != IntangibleAssetStatus.DISPOSED:
                original_nbv = a.cost - a.accumulated_amortization
                if original_nbv > a.nbv:
                    total_impairment += original_nbv - a.nbv
        return total_impairment

    def get_summary_by_type(self) -> dict[str, dict[str, str]]:
        summary = {}
        for asset_type in IntangibleAssetType:
            assets_of_type = self.get_assets_by_type(asset_type)
            if assets_of_type:
                summary[asset_type.value] = {
                    "count": str(len(assets_of_type)),
                    "total_cost": str(sum(a.cost for a in assets_of_type)),
                    "total_amortization": str(
                        sum(a.accumulated_amortization for a in assets_of_type)
                    ),
                    "total_nbv": str(sum(a.nbv for a in assets_of_type)),
                }
        return summary

    # ==================== PRIVATE HELPERS ====================

    def _copy(self) -> IntangibleAsset:
        return IntangibleAsset(
            aggregate_id=self.aggregate_id,
            legal_entity_id=self.legal_entity_id,
            assets=self.assets.copy(),
            amortization_engine=self.amortization_engine,
            created_at=self.created_at,
            updated_at=self.updated_at,
            created_by=self.created_by,
            version=self.version,
            metadata=self.metadata.copy(),
        )

    # ==================== EVENT SOURCING (untuk checker) ====================

    def apply(self, event: DomainEvent) -> None:
        """Apply a domain event (event sourcing placeholder)."""
        self._events.append(event)

    def replay(self, events: list[DomainEvent]) -> None:
        """Replay events to rebuild state."""
        for event in events:
            self.apply(event)
        # Update version based on event count
        self.version = len(events) + 1
        self._record_audit("REPLAY_EVENTS", "system", {"count": len(events)})

    def reconstruct(self, events: list[DomainEvent]) -> None:
        """Alias for replay."""
        self.replay(events)


# ============================================================================
# Alias untuk backward compatibility
# ============================================================================

IntangibleAssetAggregate = IntangibleAsset


# ============================================================================
# Repository Implementation
# ============================================================================


class IntangibleAssetRepository:
    _storage: ClassVar[dict[UUID, IntangibleAsset]] = {}

    @classmethod
    async def get_by_legal_entity(cls, legal_entity_id: UUID) -> IntangibleAsset | None:
        for asset in cls._storage.values():
            if asset.legal_entity_id == legal_entity_id:
                return asset
        return None

    @classmethod
    async def get_by_id(cls, aggregate_id: UUID) -> IntangibleAsset | None:
        return cls._storage.get(aggregate_id)

    @classmethod
    async def get_all(cls) -> list[IntangibleAsset]:
        return list(cls._storage.values())

    @classmethod
    async def save(cls, asset: IntangibleAsset) -> None:
        cls._storage[asset.aggregate_id] = asset

    @classmethod
    async def update(cls, asset: IntangibleAsset) -> None:
        cls._storage[asset.aggregate_id] = asset

    @classmethod
    async def delete(cls, aggregate_id: UUID) -> None:
        cls._storage.pop(aggregate_id, None)

    @classmethod
    async def exists(cls, aggregate_id: UUID) -> bool:
        return aggregate_id in cls._storage

    @classmethod
    async def count(cls) -> int:
        return len(cls._storage)

    @classmethod
    async def list(cls, limit: int = 100, offset: int = 0) -> list[IntangibleAsset]:
        assets = list(cls._storage.values())
        return assets[offset : offset + limit]

    @classmethod
    async def clear(cls) -> None:
        cls._storage.clear()


__all__ = [
    "IntangibleAsset",
    "IntangibleAssetAggregate",
    "IntangibleAssetRepository",
]
