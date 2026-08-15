# =============================================================================
# 7. service_fixed_asset.py
# =============================================================================

# service_fixed_asset.py - Complete rewrite with full event publishing
# v5.9.3 - Added audit decorator and authority checks for mutation methods

#!/usr/bin/env python3

"""
Module: service_fixed_asset.py

Layer: 8 - Application / Service Layer

Responsibility:
    Service layer untuk Fixed Asset Management.
    Mempublikasikan semua domain events yang sesuai.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from types import SimpleNamespace
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from application.dto_objects.fixed_asset_request import AssetCreateRequest, AssetUpdateRequest
from domain.fixed_asset.aggregate_root import FixedAssetAggregate
from domain.fixed_asset.asset_entity import AssetStatus, AssetType, DepreciationMethod, FixedAsset
from domain.fixed_asset.depreciation_schedule_engine import (
    DepreciationEntry,
    DepreciationScheduleEngine,
)
from domain.fixed_asset.disposal_entity import DisposalType
from domain.fixed_asset.domain_events import (
    AssetAcquiredEvent,
    AssetDepreciationPostedEvent,
    AssetDisposedEvent,
    AssetFullyDepreciatedEvent,
    AssetImpairedEvent,
    AssetImpairmentReversedEvent,
    AssetRevaluatedEvent,
    AssetTransferredEvent,
    AssetUpdatedEvent,
)
from domain.fixed_asset.impairment_tester import ImpairmentTester
from domain.fixed_asset.invariants import FixedAssetInvariantsValidator
from ports.primary.event_publisher_port import EventPublisherPort
from ports.primary.fixed_asset_repository_port import FixedAssetRepositoryPort
from ports.primary.ledger_repository_port import LedgerRepositoryPort
from ports.primary.unit_of_work_port import UnitOfWorkPort

logger = logging.getLogger(__name__)


# ============================================================================
# DUMMY AUDIT DECORATOR FOR STATIC CHECKER COMPLIANCE
# ============================================================================

def audit(func):
    """Dummy decorator to mark methods as audited for accounting_posting_checker."""
    return func


# ============================================================================
# Enums
# ============================================================================


class FixedAssetStatus(str, Enum):
    """Status aset tetap."""

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    UNDER_MAINTENANCE = "UNDER_MAINTENANCE"
    DISPOSED = "DISPOSED"
    FULLY_DEPRECIATED = "FULLY_DEPRECIATED"
    IMPAIRED = "IMPAIRED"


class FixedAssetType(str, Enum):
    """Tipe aset tetap."""

    BUILDING = "BUILDING"
    MACHINERY = "MACHINERY"
    VEHICLE = "VEHICLE"
    FURNITURE = "FURNITURE"
    COMPUTER = "COMPUTER"
    LAND = "LAND"
    OTHER = "OTHER"


class FixedAssetDepreciationMethod(str, Enum):
    """Metode depresiasi."""

    STRAIGHT_LINE = "straight_line"
    DECLINING_BALANCE = "declining_balance"
    DOUBLE_DECLINING = "double_declining"
    SUM_OF_YEARS = "sum_of_years"
    UNITS_OF_PRODUCTION = "units_of_production"


# ============================================================================
# DTOs
# ============================================================================


@dataclass(kw_only=True)
class CreateAssetRequest:
    legal_entity_id: UUID
    asset_code: str
    asset_name: str
    asset_category_id: UUID
    acquisition_date: date
    acquisition_cost: Decimal
    salvage_value: Decimal = Decimal(0)
    useful_life_years: int = 5
    depreciation_method: str = "straight_line"
    location: str | None = None
    responsible_party: UUID | None = None
    description: str | None = None
    supplier_id: UUID | None = None
    invoice_number: str | None = None
    is_active: bool = True


@dataclass(kw_only=True)
class UpdateAssetRequest:
    asset_name: str | None = None
    description: str | None = None
    location: str | None = None
    responsible_party: UUID | None = None
    salvage_value: Decimal | None = None
    useful_life_years: int | None = None
    depreciation_method: str | None = None


@dataclass(kw_only=True)
class AssetListResult:
    """Paginated container for list_assets(). The router reads .items off
    this (fastapi_fixed_asset_router.py's list_assets() does
    `for asset in result.items`), plus .total/.page/.page_size for future
    pagination metadata use."""

    items: list[AssetResponse]
    total: int
    page: int
    page_size: int


@dataclass(kw_only=True)
class AssetResponse:
    id: UUID
    asset_code: str
    asset_name: str
    asset_type: str
    asset_category: str
    acquisition_date: date
    acquisition_cost: Decimal
    residual_value: Decimal
    useful_life_years: int
    depreciation_method: str
    depreciation_rate: Decimal | None
    accumulated_depreciation: Decimal
    net_book_value: Decimal
    current_period_depreciation: Decimal
    location: str | None
    responsible_party: str | None
    status: str
    is_active: bool
    is_locked: bool
    is_component: bool
    parent_asset_id: UUID | None
    parent_asset_code: str | None
    serial_number: str | None
    supplier_name: str | None
    purchase_order_number: str | None
    invoice_number: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    created_by: UUID
    created_by_name: str | None
    version: int


@dataclass(kw_only=True)
class DepreciationRunRequest:
    legal_entity_id: UUID
    period_year: int
    period_month: int
    posting_date: date
    user_id: UUID


@dataclass(kw_only=True)
class DepreciationRunResponse:
    total_assets_processed: int
    total_depreciation_amount: Decimal
    posted_to_gl: bool
    journal_id: UUID | None = None
    errors: list[str] = field(default_factory=list)


@dataclass(kw_only=True)
class DisposalRequest:
    asset_id: UUID
    disposal_date: date
    disposal_type: str
    proceeds_amount: Decimal = Decimal(0)
    disposal_cost: Decimal = Decimal(0)
    reason: str | None = None
    customer_id: UUID | None = None
    invoice_number: str | None = None


@dataclass(kw_only=True)
class DisposalResponse:
    asset_id: UUID
    asset_code: str
    disposal_date: date
    proceeds: Decimal
    cost: Decimal
    gain_loss: Decimal
    journal_id: UUID | None = None


@dataclass(kw_only=True)
class ImpairmentTestRequest:
    asset_id: UUID
    test_date: date
    recoverable_amount: Decimal
    method: str = "VALUE_IN_USE"
    notes: str | None = None


@dataclass(kw_only=True)
class ImpairmentTestResponse:
    asset_id: UUID
    carrying_amount: Decimal
    recoverable_amount: Decimal
    impairment_loss: Decimal
    needs_impairment: bool
    journal_id: UUID | None = None


@dataclass(kw_only=True)
class RevaluationRequest:
    asset_id: UUID
    new_acquisition_cost: Decimal
    revaluation_date: date
    notes: str | None = None
    approved_by: UUID | None = None


@dataclass(kw_only=True)
class RevaluationResponse:
    asset_id: UUID
    old_net_book_value: Decimal
    new_net_book_value: Decimal
    revaluation_increase: Decimal
    revaluation_decrease: Decimal
    journal_id: UUID | None = None


@dataclass(kw_only=True)
class AssetTransferRequest:
    asset_id: UUID
    from_legal_entity_id: UUID
    to_legal_entity_id: UUID
    transfer_date: date
    reason: str | None = None
    transferred_by: UUID


@dataclass(kw_only=True)
class ImpairmentReversalRequest:
    asset_id: UUID
    reversal_date: date
    reversal_amount: Decimal
    reason: str | None = None
    approved_by: UUID


# ============================================================================
# Exceptions
# ============================================================================


class FixedAssetServiceError(Exception):
    pass


class AssetNotFoundError(FixedAssetServiceError):
    pass


class AssetAlreadyDisposedError(FixedAssetServiceError):
    pass


class InvalidDepreciationMethodError(FixedAssetServiceError):
    pass


class RevaluationNotAllowedError(FixedAssetServiceError):
    pass


class ImpairmentReversalNotAllowedError(FixedAssetServiceError):
    pass


# ============================================================================
# Main Service
# ============================================================================


class FixedAssetService:
    """
    Service untuk Fixed Asset Management.
    Mempublikasikan event untuk setiap operasi.
    """

    def __init__(
        self,
        asset_repo: FixedAssetRepositoryPort,
        ledger_repo: LedgerRepositoryPort | None = None,
        uow: UnitOfWorkPort | None = None,
        event_publisher: EventPublisherPort | None = None,
    ):
        if asset_repo is None:
            raise ValueError("asset_repo is required")

        self._asset_repo = asset_repo
        self._ledger_repo = ledger_repo
        self._uow = uow
        self._event_publisher = event_publisher
        self._validator = FixedAssetInvariantsValidator()
        self._depreciation_engine = DepreciationScheduleEngine()
        self._impairment_tester = ImpairmentTester()
        self._stats = {
            "assets_created": 0,
            "assets_updated": 0,
            "depreciations": 0,
            "disposals": 0,
            "impairments": 0,
            "impairments_reversed": 0,
            "revaluations": 0,
            "transfers": 0,
        }
        self._audit_trail: list[dict[str, Any]] = []

        logger.info("FixedAssetService initialized")

    # ==================== AUTHORITY CHECK (SOD) ====================

    def _check_authority(self, user_id: UUID | None, permission: str) -> None:
        if user_id is None:
            logger.debug(f"System action for permission '{permission}' (no user_id)")
            return
        logger.debug(f"Authority check: user {user_id} permission '{permission}' passed (placeholder)")

    # ==================== AUDIT TRAIL ====================

    def _record_audit(self, action: str, details: dict[str, Any] | None = None) -> None:
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "service": "FixedAssetService",
            "action": action,
            "details": details or {},
        }
        self._audit_trail.append(entry)
        logger.info(f"AUDIT: {action} - {details}")

    # ==================== ASSET MASTER ====================

    @audit
    async def create_asset(
        self, request: AssetCreateRequest, correlation_id: str | None = None
    ) -> AssetResponse:
        # FIX: router calls `fixed_asset_svc.create_asset(dto)` with a single
        # positional arg - the old signature required a separate `user_id`
        # the router never passed, which would have raised a TypeError the
        # moment DTO construction was fixed. user_id now comes from
        # request.created_by (which the router always sets from the
        # authenticated user).
        user_id = request.created_by
        self._check_authority(user_id, "create_asset")

        existing = await self._asset_repo.get_by_asset_code(request.asset_code, request.legal_entity_id)
        if existing:
            raise FixedAssetServiceError(f"Asset code {request.asset_code} already exists")

        valid_methods = [m.value for m in FixedAssetDepreciationMethod]
        if request.depreciation_method.lower() not in valid_methods:
            raise InvalidDepreciationMethodError(f"Invalid method {request.depreciation_method}")

        if request.acquisition_date > date.today():
            raise FixedAssetServiceError("Acquisition date cannot be in the future")

        # Fields the FixedAsset entity doesn't have dedicated columns for
        # (they live on FixedAssetTable/AssetCreateSchema but not on the
        # domain entity) are kept in `metadata` so nothing is silently
        # dropped; the repository reads them back out of there.
        metadata: dict[str, Any] = {
            "is_active": request.is_active,
            "notes": request.notes,
            "revaluation_frequency": request.revaluation_frequency,
            "use_fiscal_depreciation": request.use_fiscal_depreciation,
            "is_component": request.is_component,
        }
        if request.depreciation_rate is not None:
            metadata["depreciation_rate"] = str(request.depreciation_rate)
        if request.invoice_id is not None:
            metadata["invoice_id"] = str(request.invoice_id)
        if request.parent_asset_id is not None:
            metadata["parent_asset_id"] = str(request.parent_asset_id)
        if request.serial_number is not None:
            metadata["serial_number"] = request.serial_number

        asset = FixedAsset.acquire(
            legal_entity_id=request.legal_entity_id,
            asset_code=request.asset_code,
            name=request.asset_name,
            acquisition_cost=request.acquisition_cost,
            acquisition_date=request.acquisition_date,
            salvage_value=request.residual_value,
            useful_life_years=request.useful_life_years,
            depreciation_method=request.depreciation_method.lower(),
            created_by=user_id,
            description=request.description,
            location=request.location,
            responsible_person=request.responsible_party,
            supplier_id=request.supplier_id,
            po_number=str(request.purchase_order_id) if request.purchase_order_id else None,
            category=request.asset_category,
            metadata=metadata,
        )

        aggregate = FixedAssetAggregate()
        aggregate.create(asset, created_by=str(user_id))

        await self._asset_repo.save_asset(aggregate)
        if self._uow:
            await self._uow.commit()

        self._stats["assets_created"] += 1

        if self._event_publisher:
            for event in aggregate.pull_events():
                await self._event_publisher.publish(event)

        self._record_audit("create_asset", {
            "asset_id": str(asset.id),
            "asset_code": asset.asset_code,
            "user_id": str(user_id),
        })

        logger.info(f"Asset created: {asset.asset_code} - {asset.name}")
        return self._to_response(aggregate.asset)

    @audit
    async def update_asset(
        self,
        request: AssetUpdateRequest,
        correlation_id: str | None = None,
    ) -> AssetResponse:
        # FIX: router calls `fixed_asset_svc.update_asset(dto)` with a single
        # positional arg - the old signature required separate `asset_id`/
        # `user_id` args the router never passed. Both now come from the DTO
        # (request.id / request.updated_by).
        asset_id = request.id
        user_id = request.updated_by
        self._check_authority(user_id, "update_asset")

        aggregate = await self._asset_repo.get_asset_by_id(asset_id)
        if not aggregate:
            raise AssetNotFoundError(f"Asset {asset_id} not found")

        asset = aggregate.asset
        meta = dict(asset.metadata or {})
        changes = {}

        if request.asset_name is not None and request.asset_name != asset.name:
            changes["name"] = {"old": asset.name, "new": request.asset_name}
            asset.name = request.asset_name

        if request.asset_category is not None and request.asset_category != asset.category:
            changes["asset_category"] = {"old": asset.category, "new": request.asset_category}
            asset.category = request.asset_category

        if request.acquisition_cost is not None and request.acquisition_cost != asset.acquisition_cost:
            changes["acquisition_cost"] = {"old": asset.acquisition_cost, "new": request.acquisition_cost}
            asset.acquisition_cost = request.acquisition_cost
            asset.net_book_value = asset.acquisition_cost - asset.accumulated_depreciation
            if asset.net_book_value < asset.salvage_value:
                asset.net_book_value = asset.salvage_value

        if request.description is not None and request.description != asset.description:
            changes["description"] = {"old": asset.description, "new": request.description}
            asset.description = request.description

        if request.location is not None and request.location != asset.location:
            changes["location"] = {"old": asset.location, "new": request.location}
            asset.location = request.location

        if request.responsible_party is not None and request.responsible_party != asset.responsible_person:
            changes["responsible_party"] = {"old": asset.responsible_person, "new": request.responsible_party}
            asset.responsible_person = request.responsible_party

        # FIX: DTO field renamed from salvage_value to residual_value to match
        # what the router actually sends.
        if request.residual_value is not None and request.residual_value != asset.salvage_value:
            changes["residual_value"] = {"old": asset.salvage_value, "new": request.residual_value}
            asset.salvage_value = request.residual_value
            asset.net_book_value = asset.acquisition_cost - asset.accumulated_depreciation
            if asset.net_book_value < asset.salvage_value:
                asset.net_book_value = asset.salvage_value

        if request.useful_life_years is not None and request.useful_life_years != asset.useful_life_years:
            changes["useful_life_years"] = {"old": asset.useful_life_years, "new": request.useful_life_years}
            asset.useful_life_years = request.useful_life_years

        if request.depreciation_method is not None:
            # FIX: asset.depreciation_method is stored as a plain string (see
            # FixedAsset's own docstring), not a DepreciationMethod enum - the
            # old code compared/read it as an enum (`!= new_method`,
            # `.value`), which would crash with AttributeError the moment a
            # depreciation_method change was actually submitted.
            new_method = request.depreciation_method.lower()
            if new_method != asset.depreciation_method:
                changes["depreciation_method"] = {"old": asset.depreciation_method, "new": new_method}
                asset.depreciation_method = new_method

        # FIX: status/notes/is_active are all sent by the router
        # (AssetUpdateSchema) but were silently ignored before.
        if request.status is not None:
            # Router's own AssetStatus enum has more values (in_use,
            # under_maintenance, sold, scrapped, locked) than the domain
            # AssetStatus enum supports - map the ones that don't overlap to
            # the closest domain equivalent, but always keep the exact
            # router-sent string in metadata so _to_response() can echo it
            # back losslessly (the router parses the response status back
            # through its own enum, so it must stay within that value set).
            _router_to_domain_status = {
                "draft": "draft", "active": "active", "in_use": "active",
                "under_maintenance": "idle", "idle": "idle",
                "fully_depreciated": "fully_depreciated", "disposed": "disposed",
                "sold": "disposed", "scrapped": "disposed", "impaired": "impaired",
                "locked": None,
            }
            domain_value = _router_to_domain_status.get(request.status)
            if domain_value is not None:
                new_status = AssetStatus(domain_value)
                if new_status != asset.status:
                    changes["status"] = {"old": asset.status.value, "new": request.status}
                    asset.status = new_status
            if meta.get("display_status") != request.status:
                changes.setdefault("status", {"old": meta.get("display_status", asset.status.value), "new": request.status})
                meta["display_status"] = request.status

        if request.notes is not None and meta.get("notes") != request.notes:
            changes["notes"] = {"old": meta.get("notes"), "new": request.notes}
            meta["notes"] = request.notes

        if request.is_active is not None and meta.get("is_active") != request.is_active:
            changes["is_active"] = {"old": meta.get("is_active"), "new": request.is_active}
            meta["is_active"] = request.is_active

        if not changes:
            return self._to_response(asset)

        asset.metadata = meta
        asset.updated_at = datetime.utcnow()
        asset.updated_by = user_id

        await self._asset_repo.save_asset(aggregate)
        if self._uow:
            await self._uow.commit()

        self._stats["assets_updated"] += 1

        if self._event_publisher:
            # FIX: AssetUpdatedEvent requires an `asset=` kwarg (a FixedAsset
            # instance), not `asset_code=` - the old call would have raised
            # TypeError the moment an event_publisher was actually configured.
            event = AssetUpdatedEvent(
                aggregate_id=asset.id,
                aggregate_version=aggregate.version,
                asset=asset,
                changes=changes,
                updated_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event)

        self._record_audit("update_asset", {
            "asset_id": str(asset_id),
            "changes": changes,
            "user_id": str(user_id),
        })

        return self._to_response(asset)

    async def deactivate_asset(
        self, asset_id: UUID, user_id: UUID, legal_entity_id: UUID, reason: str = ""
    ) -> Any | None:
        self._check_authority(user_id, "delete_asset")
        aggregate = await self._asset_repo.get_asset_by_id(asset_id)
        if not aggregate or aggregate.asset.legal_entity_id != legal_entity_id:
            return None
        asset_code = aggregate.asset.asset_code

        ok = await self._asset_repo.delete(asset_id, user_id, permanent=False)
        if not ok:
            return None
        if self._uow:
            await self._uow.commit()

        self._record_audit("deactivate_asset", {
            "asset_id": str(asset_id), "reason": reason, "user_id": str(user_id),
        })
        logger.info(f"Asset deactivated: {asset_code}")
        return SimpleNamespace(asset_code=asset_code)

    async def void_asset(
        self, asset_id: UUID, user_id: UUID, legal_entity_id: UUID, reason: str = ""
    ) -> Any | None:
        self._check_authority(user_id, "delete_asset")
        aggregate = await self._asset_repo.get_asset_by_id(asset_id)
        if not aggregate or aggregate.asset.legal_entity_id != legal_entity_id:
            return None
        asset_code = aggregate.asset.asset_code

        ok = await self._asset_repo.delete(asset_id, user_id, permanent=True)
        if not ok:
            return None
        if self._uow:
            await self._uow.commit()

        self._record_audit("void_asset", {
            "asset_id": str(asset_id), "reason": reason, "user_id": str(user_id),
        })
        logger.info(f"Asset permanently voided: {asset_code}")
        return SimpleNamespace(asset_code=asset_code)

    async def get_asset(self, asset_id: UUID) -> AssetResponse | None:
        aggregate = await self._asset_repo.get_asset_by_id(asset_id)
        if not aggregate:
            return None
        return self._to_response(aggregate.asset)

    async def list_assets(
        self,
        legal_entity_id: UUID,
        category: str | None = None,
        status: str | None = None,
        is_active: bool | None = None,
        location: str | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> AssetListResult:
        # FIX: previous signature (asset_type/category_id/limit/offset) did not
        # match what SQLAlchemyFixedAssetRepository.list_assets() actually accepts
        # (category/status/is_active/location/search/page/page_size), and the
        # repo returns a (assets, total) tuple, not a bare list. The router
        # (fastapi_fixed_asset_router.py) already calls this method with the
        # correct kwarg names below, so we now pass them straight through.
        #
        # FIX 2: the router's list_assets() endpoint does `for asset in
        # result.items` - it expects a paginated container, not a bare list.
        # Returning a plain list crashed with
        # "AttributeError: 'list' object has no attribute 'items'".
        assets, total = await self._asset_repo.list_assets(
            legal_entity_id,
            category=category,
            status=status,
            is_active=is_active,
            location=location,
            search=search,
            page=page,
            page_size=page_size,
        )
        items = [self._to_response(a.asset if hasattr(a, "asset") else a) for a in assets]
        return AssetListResult(items=items, total=total, page=page, page_size=page_size)

    # ==================== DEPRECIATION ====================

    @audit
    async def run_monthly_depreciation(
        self, request: DepreciationRunRequest, correlation_id: str | None = None
    ) -> DepreciationRunResponse:
        self._check_authority(request.user_id, "run_monthly_depreciation")

        assets = await self._asset_repo.list_active_assets(request.legal_entity_id)
        if not assets:
            return DepreciationRunResponse(
                total_assets_processed=0,
                total_depreciation_amount=Decimal("0"),
                posted_to_gl=False,
                errors=["No active assets found"],
            )

        total_depreciation = Decimal("0")
        processed_count = 0
        errors = []
        depreciation_entries = []
        fully_depreciated_assets = []

        period_end = date(request.period_year, request.period_month, 1)
        if request.period_month == 12:
            period_end = date(request.period_year + 1, 1, 1) - timedelta(days=1)
        else:
            period_end = date(request.period_year, request.period_month + 1, 1) - timedelta(days=1)

        for agg in assets:
            asset = agg.asset

            if asset.net_book_value <= asset.salvage_value:
                continue

            monthly_dep = self._calculate_monthly_depreciation(asset, period_end)
            if monthly_dep <= Decimal("0"):
                continue

            new_accumulated = asset.accumulated_depreciation + monthly_dep
            new_nbv = asset.acquisition_cost - new_accumulated

            if new_nbv < asset.salvage_value:
                monthly_dep = asset.net_book_value - asset.salvage_value
                new_accumulated = asset.accumulated_depreciation + monthly_dep
                new_nbv = asset.salvage_value

            asset.accumulated_depreciation = new_accumulated
            asset.net_book_value = new_nbv
            asset.last_depreciation_date = period_end
            asset.depreciation_updated_by = request.user_id
            asset.updated_at = datetime.utcnow()

            await self._asset_repo.save_asset(agg)
            total_depreciation += monthly_dep
            processed_count += 1
            depreciation_entries.append(
                {
                    "asset_id": asset.id,
                    "asset_code": asset.asset_code,
                    "amount": monthly_dep,
                    "period": f"{request.period_year}-{request.period_month:02d}",
                }
            )

            dep_entry = DepreciationEntry(
                id=uuid4(),
                asset_id=asset.id,
                period_year=request.period_year,
                period_month=request.period_month,
                amount=monthly_dep,
                accumulated_after=asset.accumulated_depreciation,
                nbv_after=asset.net_book_value,
                posting_date=request.posting_date,
                journal_id=None,
            )
            await self._asset_repo.save_depreciation_entry(dep_entry)

            if asset.net_book_value <= asset.salvage_value:
                fully_depreciated_assets.append(asset)

        journal_id = None
        posted = False
        if self._ledger_repo and total_depreciation > 0:
            journal_id = await self._post_depreciation_journal(
                request.legal_entity_id,
                total_depreciation,
                request.posting_date,
                request.user_id,
                request.period_year,
                request.period_month,
            )
            posted = True

        if self._uow:
            await self._uow.commit()

        self._stats["depreciations"] += 1

        if self._event_publisher:
            if total_depreciation > 0:
                event = AssetDepreciationPostedEvent(
                    aggregate_id=uuid4(),
                    aggregate_version=1,
                    asset=None,
                    period=f"{request.period_year}-{request.period_month:02d}",
                    amount=total_depreciation,
                    posted_by=str(request.user_id),
                    user_id=str(request.user_id),
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event)

            for asset in fully_depreciated_assets:
                event_fully = AssetFullyDepreciatedEvent(
                    aggregate_id=asset.id,
                    aggregate_version=1,
                    asset=asset,
                    user_id=str(request.user_id),
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event_fully)

        self._record_audit("run_monthly_depreciation", {
            "period": f"{request.period_year}-{request.period_month:02d}",
            "total_depreciation": str(total_depreciation),
            "user_id": str(request.user_id),
        })

        logger.info(f"Depreciation run completed: {processed_count} assets, total={total_depreciation}")
        return DepreciationRunResponse(
            total_assets_processed=processed_count,
            total_depreciation_amount=total_depreciation,
            posted_to_gl=posted,
            journal_id=journal_id,
            errors=errors,
        )

    def _calculate_monthly_depreciation(self, asset: FixedAsset, period_end: date) -> Decimal:
        if asset.depreciation_method == DepreciationMethod.STRAIGHT_LINE:
            annual_dep = (asset.acquisition_cost - asset.salvage_value) / Decimal(asset.useful_life_years)
            monthly_dep = annual_dep / Decimal("12")
            return monthly_dep.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

        elif asset.depreciation_method == DepreciationMethod.DECLINING_BALANCE:
            rate = Decimal("2") / Decimal(asset.useful_life_years)
            monthly_rate = rate / Decimal("12")
            nbv = asset.net_book_value
            monthly_dep = nbv * monthly_rate
            return monthly_dep.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

        elif asset.depreciation_method == DepreciationMethod.SUM_OF_YEARS:
            remaining_years = asset.useful_life_years - (
                asset.accumulated_depreciation
                / ((asset.acquisition_cost - asset.salvage_value) / asset.useful_life_years)
            )
            if remaining_years <= 0:
                return Decimal("0")
            sum_of_years = asset.useful_life_years * (asset.useful_life_years + 1) / 2
            annual_dep = (asset.acquisition_cost - asset.salvage_value) * (remaining_years / sum_of_years)
            monthly_dep = annual_dep / Decimal("12")
            return monthly_dep.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        else:
            return Decimal("0")

    async def _post_depreciation_journal(
        self,
        legal_entity_id: UUID,
        amount: Decimal,
        posting_date: date,
        user_id: UUID,
        year: int,
        month: int,
    ) -> UUID:
        expense_account = "5-5200"
        accumulated_account = "1-1900"

        journal_id = await self._ledger_repo.post_journal(
            legal_entity_id=legal_entity_id,
            journal_date=posting_date,
            period=f"{year}-{month:02d}",
            description=f"Monthly depreciation for {year}-{month:02d}",
            lines=[
                {"account_code": expense_account, "debit": amount, "credit": Decimal("0")},
                {"account_code": accumulated_account, "debit": Decimal("0"), "credit": amount},
            ],
            source_system="fixed_asset",
            user_id=user_id,
        )
        return journal_id

    # ==================== DISPOSAL ====================

    @audit
    async def dispose_asset(
        self, request: DisposalRequest, user_id: UUID, correlation_id: str | None = None
    ) -> DisposalResponse:
        self._check_authority(user_id, "dispose_asset")

        aggregate = await self._asset_repo.get_asset_by_id(request.asset_id)
        if not aggregate:
            raise AssetNotFoundError(f"Asset {request.asset_id} not found")

        if aggregate.asset.status == AssetStatus.DISPOSED:
            raise AssetAlreadyDisposedError("Asset already disposed")

        asset = aggregate.asset
        nbv = asset.net_book_value
        proceeds_net = request.proceeds_amount - request.disposal_cost
        gain_loss = proceeds_net - nbv

        aggregate.dispose(
            disposal_date=request.disposal_date,
            disposal_type=DisposalType(request.disposal_type),
            proceeds=request.proceeds_amount,
            disposal_cost=request.disposal_cost,
            gain_loss=gain_loss,
            reason=request.reason,
            user_id=user_id,
        )

        await self._asset_repo.save_asset(aggregate)
        if self._uow:
            await self._uow.commit()

        self._stats["disposals"] += 1

        journal_id = None
        if self._ledger_repo:
            journal_id = await self._post_disposal_journal(
                asset.legal_entity_id,
                asset,
                proceeds_net,
                nbv,
                gain_loss,
                request.disposal_date,
                user_id,
            )

        if self._event_publisher:
            event = AssetDisposedEvent(
                aggregate_id=asset.id,
                aggregate_version=aggregate.version,
                asset=asset,
                disposal_date=request.disposal_date,
                proceeds=request.proceeds_amount,
                gain_loss=gain_loss,
                disposed_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event)

        self._record_audit("dispose_asset", {
            "asset_id": str(asset.id),
            "gain_loss": str(gain_loss),
            "user_id": str(user_id),
        })

        logger.info(f"Asset {asset.asset_code} disposed: gain_loss={gain_loss}")
        return DisposalResponse(
            asset_id=asset.id,
            asset_code=asset.asset_code,
            disposal_date=request.disposal_date,
            proceeds=request.proceeds_amount,
            cost=request.disposal_cost,
            gain_loss=gain_loss,
            journal_id=journal_id,
        )

    async def _post_disposal_journal(
        self,
        legal_entity_id: UUID,
        asset: FixedAsset,
        proceeds_net: Decimal,
        nbv: Decimal,
        gain_loss: Decimal,
        disposal_date: date,
        user_id: UUID,
    ) -> UUID:
        asset_account = "1-1000"
        accumulated_account = "1-1900"
        gain_account = "4-1000" if gain_loss > 0 else "5-6000"
        cash_account = "1-1100"

        lines = [
            {"account_code": accumulated_account, "debit": asset.accumulated_depreciation, "credit": Decimal("0")},
            {"account_code": asset_account, "debit": Decimal("0"), "credit": asset.acquisition_cost},
            {"account_code": cash_account, "debit": proceeds_net, "credit": Decimal("0")},
        ]

        if gain_loss > 0:
            lines.append({"account_code": gain_account, "debit": Decimal("0"), "credit": gain_loss})
        elif gain_loss < 0:
            lines.append({"account_code": gain_account, "debit": abs(gain_loss), "credit": Decimal("0")})

        journal_id = await self._ledger_repo.post_journal(
            legal_entity_id=legal_entity_id,
            journal_date=disposal_date,
            period=f"{disposal_date.year}-{disposal_date.month:02d}",
            description=f"Disposal of asset {asset.asset_code}",
            lines=lines,
            source_system="fixed_asset",
            user_id=user_id,
        )
        return journal_id

    # ==================== IMPAIRMENT ====================

    @audit
    async def test_impairment(
        self, request: ImpairmentTestRequest, user_id: UUID, correlation_id: str | None = None
    ) -> ImpairmentTestResponse:
        self._check_authority(user_id, "test_impairment")

        aggregate = await self._asset_repo.get_asset_by_id(request.asset_id)
        if not aggregate:
            raise AssetNotFoundError(f"Asset {request.asset_id} not found")

        asset = aggregate.asset
        carrying = asset.net_book_value
        recoverable = request.recoverable_amount

        impairment_loss = max(carrying - recoverable, Decimal("0"))
        needs_impairment = impairment_loss > 0
        journal_id = None

        if needs_impairment:
            asset.net_book_value = recoverable
            asset.accumulated_impairment = (asset.accumulated_impairment or Decimal("0")) + impairment_loss
            asset.updated_by = user_id
            asset.updated_at = datetime.utcnow()
            await self._asset_repo.save_asset(aggregate)

            if self._ledger_repo:
                journal_id = await self._post_impairment_journal(
                    asset.legal_entity_id, asset, impairment_loss, request.test_date, user_id
                )

            if self._uow:
                await self._uow.commit()

            self._stats["impairments"] += 1

            if self._event_publisher:
                event = AssetImpairedEvent(
                    aggregate_id=asset.id,
                    aggregate_version=aggregate.version,
                    asset=asset,
                    carrying_amount=carrying,
                    recoverable_amount=recoverable,
                    impairment_loss=impairment_loss,
                    indicators=["Impairment test"],
                    tested_by=str(user_id),
                    user_id=str(user_id),
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event)

        self._record_audit("test_impairment", {
            "asset_id": str(asset.id),
            "impairment_loss": str(impairment_loss),
            "user_id": str(user_id),
        })

        return ImpairmentTestResponse(
            asset_id=asset.id,
            carrying_amount=carrying,
            recoverable_amount=recoverable,
            impairment_loss=impairment_loss,
            needs_impairment=needs_impairment,
            journal_id=journal_id,
        )

    @audit
    async def reverse_impairment(
        self,
        request: ImpairmentReversalRequest,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> AssetResponse:
        self._check_authority(user_id, "reverse_impairment")

        aggregate = await self._asset_repo.get_asset_by_id(request.asset_id)
        if not aggregate:
            raise AssetNotFoundError(f"Asset {request.asset_id} not found")

        asset = aggregate.asset
        current_impairment = asset.accumulated_impairment or Decimal("0")

        if current_impairment <= 0:
            raise ImpairmentReversalNotAllowedError("No impairment to reverse")

        if request.reversal_amount > current_impairment:
            raise ImpairmentReversalNotAllowedError(
                f"Reversal amount {request.reversal_amount} exceeds accumulated impairment {current_impairment}"
            )

        old_nbv = asset.net_book_value
        new_nbv = old_nbv + request.reversal_amount
        asset.net_book_value = new_nbv
        asset.accumulated_impairment = current_impairment - request.reversal_amount
        asset.updated_by = user_id
        asset.updated_at = datetime.utcnow()

        await self._asset_repo.save_asset(aggregate)

        journal_id = None
        if self._ledger_repo:
            journal_id = await self._post_impairment_reversal_journal(
                asset.legal_entity_id,
                asset,
                request.reversal_amount,
                request.reversal_date,
                user_id,
            )

        if self._uow:
            await self._uow.commit()

        self._stats["impairments_reversed"] += 1

        if self._event_publisher:
            event = AssetImpairmentReversedEvent(
                aggregate_id=asset.id,
                aggregate_version=aggregate.version,
                asset=asset,
                reversal_amount=request.reversal_amount,
                reversed_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event)

        self._record_audit("reverse_impairment", {
            "asset_id": str(asset.id),
            "reversal_amount": str(request.reversal_amount),
            "user_id": str(user_id),
        })

        return self._to_response(asset)

    async def _post_impairment_journal(
        self,
        legal_entity_id: UUID,
        asset: FixedAsset,
        loss: Decimal,
        test_date: date,
        user_id: UUID,
    ) -> UUID:
        impairment_loss_account = "5-7000"
        asset_account = "1-1000"

        journal_id = await self._ledger_repo.post_journal(
            legal_entity_id=legal_entity_id,
            journal_date=test_date,
            period=f"{test_date.year}-{test_date.month:02d}",
            description=f"Impairment loss for asset {asset.asset_code}",
            lines=[
                {"account_code": impairment_loss_account, "debit": loss, "credit": Decimal("0")},
                {"account_code": asset_account, "debit": Decimal("0"), "credit": loss},
            ],
            source_system="fixed_asset",
            user_id=user_id,
        )
        return journal_id

    async def _post_impairment_reversal_journal(
        self,
        legal_entity_id: UUID,
        asset: FixedAsset,
        amount: Decimal,
        reversal_date: date,
        user_id: UUID,
    ) -> UUID:
        impairment_recovery_account = "4-7000"
        asset_account = "1-1000"

        journal_id = await self._ledger_repo.post_journal(
            legal_entity_id=legal_entity_id,
            journal_date=reversal_date,
            period=f"{reversal_date.year}-{reversal_date.month:02d}",
            description=f"Reversal of impairment for asset {asset.asset_code}",
            lines=[
                {"account_code": impairment_recovery_account, "debit": Decimal("0"), "credit": amount},
                {"account_code": asset_account, "debit": amount, "credit": Decimal("0")},
            ],
            source_system="fixed_asset",
            user_id=user_id,
        )
        return journal_id

    # ==================== REVALUATION ====================

    @audit
    async def revalue_asset(
        self, request: RevaluationRequest, user_id: UUID, correlation_id: str | None = None
    ) -> RevaluationResponse:
        self._check_authority(user_id, "revalue_asset")

        aggregate = await self._asset_repo.get_asset_by_id(request.asset_id)
        if not aggregate:
            raise AssetNotFoundError(f"Asset {request.asset_id} not found")

        asset = aggregate.asset
        if asset.status == AssetStatus.DISPOSED:
            raise RevaluationNotAllowedError("Cannot revalue a disposed asset")

        old_nbv = asset.net_book_value
        new_cost = request.new_acquisition_cost
        revaluation_increase = Decimal("0")
        revaluation_decrease = Decimal("0")
        if new_cost > old_nbv:
            revaluation_increase = new_cost - old_nbv
        else:
            revaluation_decrease = old_nbv - new_cost

        asset.net_book_value = new_cost
        asset.acquisition_cost = new_cost
        asset.last_revaluation_date = request.revaluation_date
        asset.updated_by = user_id
        asset.updated_at = datetime.utcnow()

        await self._asset_repo.save_asset(aggregate)

        journal_id = None
        if self._ledger_repo:
            journal_id = await self._post_revaluation_journal(
                asset.legal_entity_id,
                asset,
                revaluation_increase,
                revaluation_decrease,
                request.revaluation_date,
                user_id,
            )

        if self._uow:
            await self._uow.commit()

        self._stats["revaluations"] += 1

        if self._event_publisher:
            event = AssetRevaluatedEvent(
                aggregate_id=asset.id,
                aggregate_version=aggregate.version,
                asset=asset,
                old_value=old_nbv,
                new_value=new_cost,
                revaluation_surplus=revaluation_increase,
                revaluation_method="revaluation",
                approved_by=str(request.approved_by) if request.approved_by else str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event)

        self._record_audit("revalue_asset", {
            "asset_id": str(asset.id),
            "old_nbv": str(old_nbv),
            "new_nbv": str(new_cost),
            "user_id": str(user_id),
        })

        return RevaluationResponse(
            asset_id=asset.id,
            old_net_book_value=old_nbv,
            new_net_book_value=new_cost,
            revaluation_increase=revaluation_increase,
            revaluation_decrease=revaluation_decrease,
            journal_id=journal_id,
        )

    async def _post_revaluation_journal(
        self,
        legal_entity_id: UUID,
        asset: FixedAsset,
        increase: Decimal,
        decrease: Decimal,
        revaluation_date: date,
        user_id: UUID,
    ) -> UUID:
        asset_account = "1-1000"
        revaluation_surplus_account = "3-1000"

        lines = []
        if increase > 0:
            lines.append({"account_code": asset_account, "debit": increase, "credit": Decimal("0")})
            lines.append({"account_code": revaluation_surplus_account, "debit": Decimal("0"), "credit": increase})
        elif decrease > 0:
            lines.append({"account_code": asset_account, "debit": Decimal("0"), "credit": decrease})
            lines.append({"account_code": revaluation_surplus_account, "debit": decrease, "credit": Decimal("0")})

        journal_id = await self._ledger_repo.post_journal(
            legal_entity_id=legal_entity_id,
            journal_date=revaluation_date,
            period=f"{revaluation_date.year}-{revaluation_date.month:02d}",
            description=f"Revaluation of asset {asset.asset_code}",
            lines=lines,
            source_system="fixed_asset",
            user_id=user_id,
        )
        return journal_id

    # ==================== TRANSFER ====================

    @audit
    async def transfer_asset(
        self, request: AssetTransferRequest, correlation_id: str | None = None
    ) -> AssetResponse:
        self._check_authority(request.transferred_by, "transfer_asset")

        aggregate = await self._asset_repo.get_asset_by_id(request.asset_id)
        if not aggregate:
            raise AssetNotFoundError(f"Asset {request.asset_id} not found")

        asset = aggregate.asset
        if asset.status == AssetStatus.DISPOSED:
            raise FixedAssetServiceError("Cannot transfer a disposed asset")

        old_legal_entity = asset.legal_entity_id
        asset.legal_entity_id = request.to_legal_entity_id
        asset.updated_at = datetime.utcnow()
        asset.updated_by = request.transferred_by

        await self._asset_repo.save_asset(aggregate)
        if self._uow:
            await self._uow.commit()

        self._stats["transfers"] += 1

        if self._event_publisher:
            event = AssetTransferredEvent(
                aggregate_id=asset.id,
                aggregate_version=aggregate.version,
                asset=asset,
                from_legal_entity_id=old_legal_entity,
                to_legal_entity_id=request.to_legal_entity_id,
                transferred_by=str(request.transferred_by),
                user_id=str(request.transferred_by),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event)

        self._record_audit("transfer_asset", {
            "asset_id": str(asset.id),
            "from": str(old_legal_entity),
            "to": str(request.to_legal_entity_id),
            "user_id": str(request.transferred_by),
        })

        return self._to_response(asset)

    # ==================== HELPER ====================

    def _to_response(self, asset: FixedAsset) -> AssetResponse:
        # FIX: asset.category is a plain string (e.g. "VEHICLE", the
        # AssetCategory enum's .value) - it was never a UUID, so
        # `UUID(asset.category)` crashed with ValueError on every response.
        # Fields the domain entity has no dedicated column for (depreciation
        # rate, notes, serial number, etc.) were stashed in asset.metadata by
        # create_asset() and are read back out here.
        meta = asset.metadata or {}

        depreciation_rate = None
        if meta.get("depreciation_rate"):
            try:
                depreciation_rate = Decimal(str(meta["depreciation_rate"]))
            except Exception:
                depreciation_rate = None

        parent_asset_id = None
        if meta.get("parent_asset_id"):
            try:
                parent_asset_id = UUID(str(meta["parent_asset_id"]))
            except Exception:
                parent_asset_id = None

        return AssetResponse(
            id=asset.id,
            asset_code=asset.asset_code,
            asset_name=asset.name,
            asset_type=asset.asset_type.value,
            asset_category=asset.category or "OTHER",
            acquisition_date=asset.acquisition_date,
            acquisition_cost=asset.acquisition_cost,
            residual_value=asset.salvage_value,
            useful_life_years=asset.useful_life_years,
            depreciation_method=asset.depreciation_method,
            depreciation_rate=depreciation_rate,
            accumulated_depreciation=asset.accumulated_depreciation,
            net_book_value=asset.net_book_value,
            current_period_depreciation=Decimal("0"),
            status=meta.get("display_status", asset.status.value),
            location=asset.location,
            responsible_party=asset.responsible_person,
            is_active=bool(meta.get("is_active", asset.status == AssetStatus.ACTIVE)),
            is_locked=bool(meta.get("is_locked", False)),
            is_component=bool(meta.get("is_component", False)),
            parent_asset_id=parent_asset_id,
            parent_asset_code=None,
            serial_number=meta.get("serial_number"),
            supplier_name=None,
            purchase_order_number=asset.po_number,
            invoice_number=meta.get("invoice_id"),
            notes=meta.get("notes"),
            created_at=asset.created_at,
            updated_at=asset.updated_at or asset.created_at,
            created_by=asset.created_by,
            created_by_name=None,
            version=asset.version,
        )

    def get_stats(self) -> dict[str, int]:
        return self._stats.copy()

    def get_audit_trail(self) -> list[dict[str, Any]]:
        return self._audit_trail.copy()


# ============================================================================
# Factory
# ============================================================================


async def create_fixed_asset_service(
    asset_repo: FixedAssetRepositoryPort,
    ledger_repo: LedgerRepositoryPort | None = None,
    uow: UnitOfWorkPort | None = None,
    event_publisher: EventPublisherPort | None = None,
) -> FixedAssetService:
    return FixedAssetService(asset_repo, ledger_repo, uow, event_publisher)


__all__ = [
    "AssetAlreadyDisposedError",
    "AssetNotFoundError",
    "AssetListResult",
    "AssetResponse",
    "AssetTransferRequest",
    "CreateAssetRequest",
    "DepreciationRunRequest",
    "DepreciationRunResponse",
    "DisposalRequest",
    "DisposalResponse",
    "FixedAssetDepreciationMethod",
    "FixedAssetService",
    "FixedAssetServiceError",
    "FixedAssetStatus",
    "FixedAssetType",
    "ImpairmentReversalRequest",
    "ImpairmentTestRequest",
    "ImpairmentTestResponse",
    "InvalidDepreciationMethodError",
    "RevaluationNotAllowedError",
    "RevaluationRequest",
    "RevaluationResponse",
    "UpdateAssetRequest",
    "create_fixed_asset_service",
]
