#!/usr/bin/env python3
"""
Module: fixed_asset_repository_port.py
Layer: Ports (Primary)
Responsibility: Implementasi in-memory repository untuk Fixed Asset (Aset Tetap)
               dengan fitur lengkap: depresiasi, revaluasi, penghentian, impor/ekspor.
"""

from __future__ import annotations

import asyncio
import csv
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


class DepreciationMethod(Enum):
    STRAIGHT_LINE = "straight_line"
    DOUBLE_DECLINING = "double_declining"
    UNITS_OF_PRODUCTION = "units_of_production"
    SUM_OF_YEARS = "sum_of_years"


class AssetStatus(Enum):
    ACTIVE = "active"
    FULLY_DEPRECIATED = "fully_depreciated"
    DISPOSED = "disposed"
    HELD_FOR_SALE = "held_for_sale"
    IMPAIRED = "impaired"
    REVALUED = "revalued"


class RevaluationType(Enum):
    INCREASE = "increase"
    DECREASE = "decrease"


@dataclass
class DepreciationEntry:
    period_date: date
    depreciation_amount: Decimal
    accumulated_depreciation: Decimal
    net_book_value: Decimal
    posted_to_journal: bool
    journal_id: UUID | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "period_date": self.period_date.isoformat(),
            "depreciation_amount": float(self.depreciation_amount),
            "accumulated_depreciation": float(self.accumulated_depreciation),
            "net_book_value": float(self.net_book_value),
            "posted_to_journal": self.posted_to_journal,
            "journal_id": str(self.journal_id) if self.journal_id else None,
        }


@dataclass
class RevaluationHistory:
    revaluation_date: date
    revaluation_type: RevaluationType
    old_value: Decimal
    new_value: Decimal
    revaluation_surplus: Decimal
    approved_by: UUID
    reason: str
    journal_id: UUID | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "revaluation_date": self.revaluation_date.isoformat(),
            "revaluation_type": self.revaluation_type.value,
            "old_value": float(self.old_value),
            "new_value": float(self.new_value),
            "revaluation_surplus": float(self.revaluation_surplus),
            "approved_by": str(self.approved_by),
            "reason": self.reason,
            "journal_id": str(self.journal_id) if self.journal_id else None,
        }


@dataclass
class FixedAsset:
    id: UUID
    asset_code: str
    asset_name: str
    legal_entity_id: UUID
    asset_group_id: UUID | None
    acquisition_date: date
    acquisition_cost: Decimal
    salvage_value: Decimal
    useful_life_years: int
    depreciation_method: DepreciationMethod
    annual_depreciation_rate: Decimal
    status: AssetStatus
    current_net_book_value: Decimal
    accumulated_depreciation: Decimal
    total_units_produced: Decimal | None
    estimated_total_units: Decimal | None
    revaluation_surplus: Decimal
    impairment_loss: Decimal
    disposal_date: date | None
    disposal_proceeds: Decimal | None
    disposal_gain_loss: Decimal | None
    location: str | None
    responsible_party: UUID | None
    invoice_reference: str | None
    notes: str | None
    depreciation_history: list[DepreciationEntry] = field(default_factory=list)
    revaluation_history: list[RevaluationHistory] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID = field(default_factory=lambda: UUID(int=0))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_by: UUID = field(default_factory=lambda: UUID(int=0))
    version: int = 1

    def to_dict(self, include_history: bool = False) -> dict[str, Any]:
        result = {
            "id": str(self.id),
            "asset_code": self.asset_code,
            "asset_name": self.asset_name,
            "legal_entity_id": str(self.legal_entity_id),
            "asset_group_id": str(self.asset_group_id) if self.asset_group_id else None,
            "acquisition_date": self.acquisition_date.isoformat(),
            "acquisition_cost": float(self.acquisition_cost),
            "salvage_value": float(self.salvage_value),
            "useful_life_years": self.useful_life_years,
            "depreciation_method": self.depreciation_method.value,
            "annual_depreciation_rate": float(self.annual_depreciation_rate),
            "status": self.status.value,
            "current_net_book_value": float(self.current_net_book_value),
            "accumulated_depreciation": float(self.accumulated_depreciation),
            "total_units_produced": float(self.total_units_produced) if self.total_units_produced else None,
            "estimated_total_units": float(self.estimated_total_units) if self.estimated_total_units else None,
            "revaluation_surplus": float(self.revaluation_surplus),
            "impairment_loss": float(self.impairment_loss),
            "disposal_date": self.disposal_date.isoformat() if self.disposal_date else None,
            "disposal_proceeds": float(self.disposal_proceeds) if self.disposal_proceeds else None,
            "disposal_gain_loss": float(self.disposal_gain_loss) if self.disposal_gain_loss else None,
            "location": self.location,
            "responsible_party": str(self.responsible_party) if self.responsible_party else None,
            "invoice_reference": self.invoice_reference,
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
            "created_by": str(self.created_by),
            "updated_at": self.updated_at.isoformat(),
            "updated_by": str(self.updated_by),
            "version": self.version,
        }
        if include_history:
            result["depreciation_history"] = [h.to_dict() for h in self.depreciation_history]
            result["revaluation_history"] = [h.to_dict() for h in self.revaluation_history]
        return result


class FixedAssetRepositoryPort:
    """
    Repository in-memory untuk Fixed Asset.
    """

    def __init__(self):
        self._storage: dict[UUID, FixedAsset] = {}
        self._code_index: dict[tuple[str, UUID], FixedAsset] = {}
        self._group_index: dict[UUID, list[UUID]] = {}
        self._status_index: dict[AssetStatus, list[UUID]] = {}
        self._audit_log: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()

    # ==================== METHOD ALIAS UNTUK KONTRAK ====================
    async def save_asset(self, asset: FixedAsset) -> None:
        """Alias untuk add(). Memenuhi kontrak FixedAssetRepositoryPort."""
        return await self.add(asset)

    async def find_asset_by_id(self, asset_id: UUID) -> FixedAsset | None:
        """Alias untuk get_by_id(). Memenuhi kontrak FixedAssetRepositoryPort."""
        return await self.get_by_id(asset_id)

    # ==================== CRUD ====================
    async def add(self, asset: FixedAsset) -> None:
        if not isinstance(asset, FixedAsset):
            raise TypeError("asset must be FixedAsset instance")
        if asset.id in self._storage:
            raise ValueError(f"Asset with id {asset.id} already exists")
        key = (asset.asset_code, asset.legal_entity_id)
        if key in self._code_index:
            raise ValueError(f"Asset with code {asset.asset_code} already exists for this legal entity")
        async with self._lock:
            self._storage[asset.id] = asset
            self._code_index[key] = asset
            if asset.asset_group_id:
                self._group_index.setdefault(asset.asset_group_id, []).append(asset.id)
            self._status_index.setdefault(asset.status, []).append(asset.id)
        await self._log_audit("ADD", asset.id, asset.created_by, {"asset_code": asset.asset_code})

    async def get_by_id(self, asset_id: UUID) -> FixedAsset | None:
        return self._storage.get(asset_id)

    async def get_by_asset_code(self, asset_code: str, legal_entity_id: UUID) -> FixedAsset | None:
        return self._code_index.get((asset_code, legal_entity_id))

    async def update(self, asset: FixedAsset) -> None:
        if asset.id not in self._storage:
            raise ValueError(f"Asset with id {asset.id} not found")
        old = self._storage[asset.id]
        old_key = (old.asset_code, old.legal_entity_id)
        new_key = (asset.asset_code, asset.legal_entity_id)
        if old_key != new_key:
            del self._code_index[old_key]
            self._code_index[new_key] = asset
        if old.asset_group_id != asset.asset_group_id:
            if old.asset_group_id and old.asset_group_id in self._group_index:
                self._group_index[old.asset_group_id] = [aid for aid in self._group_index[old.asset_group_id] if aid != asset.id]
            if asset.asset_group_id:
                self._group_index.setdefault(asset.asset_group_id, []).append(asset.id)
        if old.status != asset.status:
            if old.status in self._status_index and asset.id in self._status_index[old.status]:
                self._status_index[old.status].remove(asset.id)
            self._status_index.setdefault(asset.status, []).append(asset.id)
        asset.updated_at = datetime.now(UTC)
        asset.version += 1
        self._storage[asset.id] = asset
        await self._log_audit("UPDATE", asset.id, asset.updated_by, {})

    async def delete(self, asset_id: UUID, user_id: UUID, permanent: bool = False) -> bool:
        if asset_id not in self._storage:
            return False
        asset = self._storage[asset_id]
        if permanent:
            key = (asset.asset_code, asset.legal_entity_id)
            if key in self._code_index:
                del self._code_index[key]
            if asset.asset_group_id and asset.asset_group_id in self._group_index:
                self._group_index[asset.asset_group_id] = [aid for aid in self._group_index[asset.asset_group_id] if aid != asset_id]
            if asset.status in self._status_index and asset_id in self._status_index[asset.status]:
                self._status_index[asset.status].remove(asset_id)
            del self._storage[asset_id]
        else:
            asset.status = AssetStatus.DISPOSED
            asset.disposal_date = datetime.now(UTC).date()
            asset.updated_by = user_id
            asset.updated_at = datetime.now(UTC)
            asset.version += 1
            if AssetStatus.DISPOSED not in self._status_index:
                self._status_index[AssetStatus.DISPOSED] = []
            if asset_id not in self._status_index[AssetStatus.DISPOSED]:
                self._status_index[AssetStatus.DISPOSED].append(asset_id)
            if asset.status in self._status_index and asset_id in self._status_index[asset.status]:
                self._status_index[asset.status].remove(asset_id)
        await self._log_audit("DELETE", asset_id, user_id, {"permanent": permanent})
        return True

    # ==================== DEPRESIASI ====================
    async def calculate_monthly_depreciation(self, asset_id: UUID, period_date: date) -> Decimal:
        asset = await self.get_by_id(asset_id)
        if not asset:
            raise ValueError(f"Asset {asset_id} not found")
        if asset.status in (AssetStatus.DISPOSED, AssetStatus.FULLY_DEPRECIATED):
            return Decimal(0)
        if period_date < asset.acquisition_date:
            return Decimal(0)
        if asset.depreciation_method == DepreciationMethod.STRAIGHT_LINE:
            depr_per_year = (asset.acquisition_cost - asset.salvage_value) / Decimal(asset.useful_life_years)
            return (depr_per_year / Decimal(12)).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        elif asset.depreciation_method == DepreciationMethod.DOUBLE_DECLINING:
            rate = Decimal(2) / Decimal(asset.useful_life_years)
            accum, nbv = await self._recompute_nbv(asset)
            monthly = (nbv * rate / Decimal(12)).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
            return max(monthly, Decimal(0))
        else:
            return Decimal(0)

    async def post_monthly_depreciation(self, asset_id: UUID, period_date: date, journal_id: UUID, user_id: UUID) -> Decimal:
        asset = await self.get_by_id(asset_id)
        if not asset:
            raise ValueError(f"Asset {asset_id} not found")
        if asset.status in (AssetStatus.DISPOSED, AssetStatus.FULLY_DEPRECIATED):
            raise ValueError(f"Asset {asset_id} already disposed or fully depreciated")
        monthly_amount = await self.calculate_monthly_depreciation(asset_id, period_date)
        if monthly_amount <= 0:
            return Decimal(0)
        new_accum = asset.accumulated_depreciation + monthly_amount
        if new_accum > (asset.acquisition_cost - asset.salvage_value):
            new_accum = asset.acquisition_cost - asset.salvage_value
        asset.accumulated_depreciation = new_accum
        asset.current_net_book_value = asset.acquisition_cost - new_accum
        if new_accum >= (asset.acquisition_cost - asset.salvage_value) and asset.acquisition_cost > asset.salvage_value:
            asset.status = AssetStatus.FULLY_DEPRECIATED
        entry = DepreciationEntry(
            period_date=period_date,
            depreciation_amount=monthly_amount,
            accumulated_depreciation=new_accum,
            net_book_value=asset.current_net_book_value,
            posted_to_journal=True,
            journal_id=journal_id,
        )
        asset.depreciation_history.append(entry)
        asset.updated_at = datetime.now(UTC)
        asset.updated_by = user_id
        asset.version += 1
        await self.update(asset)
        await self._log_audit("POST_DEPRECIATION", asset_id, user_id, {"period": period_date.isoformat(), "amount": float(monthly_amount)})
        return monthly_amount

    async def get_net_book_value(self, asset_id: UUID, as_of_date: date) -> Decimal:
        asset = await self.get_by_id(asset_id)
        if not asset:
            raise ValueError(f"Asset {asset_id} not found")
        depr_accum, nbv = await self._recompute_nbv(asset)
        return nbv

    async def get_accumulated_depreciation(self, asset_id: UUID, as_of_date: date) -> Decimal:
        asset = await self.get_by_id(asset_id)
        if not asset:
            raise ValueError(f"Asset {asset_id} not found")
        depr_accum, _ = await self._recompute_nbv(asset)
        return depr_accum

    async def _recompute_nbv(self, asset: FixedAsset) -> tuple[Decimal, Decimal]:
        if asset.depreciation_method == DepreciationMethod.STRAIGHT_LINE:
            depr_per_year = (asset.acquisition_cost - asset.salvage_value) / Decimal(asset.useful_life_years)
            months_elapsed = self._months_between(asset.acquisition_date, datetime.now(UTC).date())
            depr_accum = (depr_per_year / Decimal(12)) * Decimal(months_elapsed)
            depr_accum = min(depr_accum, asset.acquisition_cost - asset.salvage_value)
        elif asset.depreciation_method == DepreciationMethod.DOUBLE_DECLINING:
            rate = Decimal(2) / Decimal(asset.useful_life_years)
            nbv = asset.acquisition_cost
            months_elapsed = self._months_between(asset.acquisition_date, datetime.now(UTC).date())
            full_years = months_elapsed // 12
            remaining_months = months_elapsed % 12
            for _ in range(full_years):
                depr = nbv * rate
                nbv -= depr
            if remaining_months > 0:
                depr = nbv * rate * Decimal(remaining_months) / Decimal(12)
                nbv -= depr
            depr_accum = asset.acquisition_cost - max(nbv, asset.salvage_value)
        else:
            depr_accum = asset.accumulated_depreciation
        nbv = asset.acquisition_cost - depr_accum
        if nbv < asset.salvage_value:
            nbv = asset.salvage_value
            depr_accum = asset.acquisition_cost - nbv
        return depr_accum, nbv

    def _months_between(self, start_date: date, end_date: date) -> int:
        return (end_date.year - start_date.year) * 12 + (end_date.month - start_date.month)

    # ==================== REVALUASI ====================
    async def revalue_asset(self, asset_id: UUID, new_value: Decimal, revaluation_date: date, reason: str, approved_by: UUID, journal_id: UUID | None = None) -> FixedAsset:
        asset = await self.get_by_id(asset_id)
        if not asset:
            raise ValueError(f"Asset {asset_id} not found")
        old_value = asset.current_net_book_value
        if new_value == old_value:
            raise ValueError("New value equals current NBV")
        reval_type = RevaluationType.INCREASE if new_value > old_value else RevaluationType.DECREASE
        surplus = new_value - old_value
        if reval_type == RevaluationType.INCREASE:
            asset.revaluation_surplus += surplus
        else:
            if asset.revaluation_surplus > 0:
                reduce = min(asset.revaluation_surplus, -surplus)
                asset.revaluation_surplus -= reduce
                surplus += reduce
            if surplus < 0:
                asset.impairment_loss += -surplus
        asset.current_net_book_value = new_value
        history = RevaluationHistory(
            revaluation_date=revaluation_date,
            revaluation_type=reval_type,
            old_value=old_value,
            new_value=new_value,
            revaluation_surplus=surplus if reval_type == RevaluationType.INCREASE else Decimal(0),
            approved_by=approved_by,
            reason=reason,
            journal_id=journal_id,
        )
        asset.revaluation_history.append(history)
        asset.updated_at = datetime.now(UTC)
        asset.updated_by = approved_by
        asset.version += 1
        await self.update(asset)
        await self._log_audit("REVALUATION", asset_id, approved_by, {"old_value": float(old_value), "new_value": float(new_value)})
        return asset

    # ==================== DISPOSAL ====================
    async def dispose_asset(self, asset_id: UUID, disposal_date: date, proceeds: Decimal, user_id: UUID, journal_id: UUID | None = None) -> tuple[Decimal, Decimal]:
        asset = await self.get_by_id(asset_id)
        if not asset:
            raise ValueError(f"Asset {asset_id} not found")
        if asset.status == AssetStatus.DISPOSED:
            raise ValueError(f"Asset {asset_id} already disposed")
        nbv = asset.current_net_book_value
        gain_loss = proceeds - nbv
        asset.status = AssetStatus.DISPOSED
        asset.disposal_date = disposal_date
        asset.disposal_proceeds = proceeds
        asset.disposal_gain_loss = gain_loss
        asset.updated_at = datetime.now(UTC)
        asset.updated_by = user_id
        asset.version += 1
        await self.update(asset)
        await self._log_audit("DISPOSAL", asset_id, user_id, {"proceeds": float(proceeds), "nbv": float(nbv), "gain_loss": float(gain_loss)})
        return (gain_loss if gain_loss > 0 else Decimal(0), abs(gain_loss) if gain_loss < 0 else Decimal(0))

    # ==================== QUERY ====================
    async def find_by_asset_group(self, group_id: UUID) -> list[FixedAsset]:
        asset_ids = self._group_index.get(group_id, [])
        return [self._storage[aid] for aid in asset_ids if aid in self._storage]

    async def find_by_status(self, status: AssetStatus) -> list[FixedAsset]:
        asset_ids = self._status_index.get(status, [])
        return [self._storage[aid] for aid in asset_ids if aid in self._storage]

    async def find_active_as_of_date(self, as_of_date: date, legal_entity_id: UUID) -> list[FixedAsset]:
        result = []
        for asset in self._storage.values():
            if asset.legal_entity_id != legal_entity_id:
                continue
            if asset.status in (AssetStatus.DISPOSED, AssetStatus.FULLY_DEPRECIATED):
                continue
            if asset.acquisition_date > as_of_date:
                continue
            if asset.disposal_date and asset.disposal_date <= as_of_date:
                continue
            result.append(asset)
        return result

    async def find_due_for_depreciation(self, depreciation_date: date, legal_entity_id: UUID | None = None) -> list[FixedAsset]:
        result = []
        for asset in self._storage.values():
            if legal_entity_id and asset.legal_entity_id != legal_entity_id:
                continue
            if asset.status != AssetStatus.ACTIVE:
                continue
            if asset.acquisition_date > depreciation_date:
                continue
            if asset.accumulated_depreciation >= (asset.acquisition_cost - asset.salvage_value):
                continue
            already_posted = any(e.period_date == depreciation_date for e in asset.depreciation_history)
            if not already_posted:
                result.append(asset)
        return result

    async def find_by_name_contains(self, keyword: str, legal_entity_id: UUID | None = None) -> list[FixedAsset]:
        keyword_lower = keyword.lower()
        result = []
        for asset in self._storage.values():
            if legal_entity_id and asset.legal_entity_id != legal_entity_id:
                continue
            if keyword_lower in asset.asset_name.lower():
                result.append(asset)
        return result

    async def get_all(self, legal_entity_id: UUID | None = None, limit: int = 100, offset: int = 0) -> list[FixedAsset]:
        result = list(self._storage.values())
        if legal_entity_id:
            result = [a for a in result if a.legal_entity_id == legal_entity_id]
        result.sort(key=lambda x: x.asset_code)
        return result[offset:offset+limit]

    # ==================== AUDIT & STATISTIK ====================
    async def _log_audit(self, action: str, asset_id: UUID, user_id: UUID, details: dict[str, Any]):
        entry = {"timestamp": datetime.now(UTC).isoformat(), "action": action, "asset_id": str(asset_id), "user_id": str(user_id), "details": details}
        self._audit_log.append(entry)
        logger.info(f"AUDIT: {action} on {asset_id}")

    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        return self._audit_log[offset:offset+limit]

    async def get_statistics(self, legal_entity_id: UUID | None = None) -> dict[str, Any]:
        assets = list(self._storage.values())
        if legal_entity_id:
            assets = [a for a in assets if a.legal_entity_id == legal_entity_id]
        return {
            "total_assets": len(assets),
            "total_acquisition_cost": float(sum(a.acquisition_cost for a in assets)),
            "total_net_book_value": float(sum(a.current_net_book_value for a in assets)),
            "active": sum(1 for a in assets if a.status == AssetStatus.ACTIVE),
            "fully_depreciated": sum(1 for a in assets if a.status == AssetStatus.FULLY_DEPRECIATED),
            "disposed": sum(1 for a in assets if a.status == AssetStatus.DISPOSED),
        }

    async def export_to_csv(self, legal_entity_id: UUID | None = None) -> str:
        assets = await self.get_all(legal_entity_id, limit=10000, offset=0)
        import io
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["id", "asset_code", "asset_name", "acquisition_date", "acquisition_cost", "salvage_value", "useful_life_years", "depreciation_method", "current_nbv", "status"])
        for a in assets:
            writer.writerow([str(a.id), a.asset_code, a.asset_name, a.acquisition_date.isoformat(), float(a.acquisition_cost), float(a.salvage_value), a.useful_life_years, a.depreciation_method.value, float(a.current_net_book_value), a.status.value])
        return output.getvalue()

    async def import_from_csv(self, csv_content: str, user_id: UUID, legal_entity_id: UUID) -> int:
        import io
        reader = csv.DictReader(io.StringIO(csv_content))
        count = 0
        for row in reader:
            try:
                asset = FixedAsset(
                    id=uuid4(),
                    asset_code=row["asset_code"],
                    asset_name=row["asset_name"],
                    legal_entity_id=legal_entity_id,
                    asset_group_id=None,
                    acquisition_date=date.fromisoformat(row["acquisition_date"]),
                    acquisition_cost=Decimal(row["acquisition_cost"]),
                    salvage_value=Decimal(row.get("salvage_value", "0")),
                    useful_life_years=int(row["useful_life_years"]),
                    depreciation_method=DepreciationMethod(row["depreciation_method"]),
                    annual_depreciation_rate=Decimal(100) / Decimal(row["useful_life_years"]),
                    status=AssetStatus.ACTIVE,
                    current_net_book_value=Decimal(row["acquisition_cost"]),
                    accumulated_depreciation=Decimal(0),
                    total_units_produced=None,
                    estimated_total_units=None,
                    revaluation_surplus=Decimal(0),
                    impairment_loss=Decimal(0),
                    disposal_date=None,
                    disposal_proceeds=None,
                    disposal_gain_loss=None,
                    location=row.get("location"),
                    responsible_party=None,
                    invoice_reference=None,
                    notes=None,
                    created_by=user_id,
                    updated_by=user_id,
                )
                await self.add(asset)
                count += 1
            except Exception as e:
                logger.warning(f"Import failed: {e}")
        return count

    async def health_check(self) -> dict[str, Any]:
        return {"status": "healthy", "total_assets": len(self._storage), "audit_log_size": len(self._audit_log)}
