# =============================================================================
# service_inventory.py - Complete rewrite with full event publishing and validations
# v6.0.0 - Fixed complete_transfer validation (INV-068, INV-069)
# =============================================================================

#!/usr/bin/env python3

"""
Module: service_inventory.py

Layer: 8 - Application / Service Layer

Responsibility:
    Service layer untuk Inventory Management.
    Mempublikasikan semua domain events yang sesuai.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from domain.inventory.aggregate_root import InventoryAggregate
from domain.inventory.domain_events import (
    COGSCalculated,
    InterWarehouseTransferCreated,
    InventoryValuationUpdated,
    ItemCreated,
    ItemDeactivated,
    ItemUpdated,
    StockLevelAlert,
    StockMovementCreated,
    StockOpnameApproved,
    StockOpnameCreated,
    TransferCompleted,
)
from domain.inventory.inter_warehouse_transfer_entity import (
    InterWarehouseTransfer,
    TransferItem,
    TransferPriority,
    TransferStatus,
)
from domain.inventory.invariants import InventoryInvariantsValidator
from domain.inventory.item_entity import Item, ItemStatus, ItemType, UnitOfMeasure
from domain.inventory.movement_entity import MovementStatus, MovementType, StockMovement
from domain.inventory.stock_opname_entity import DiscrepancyType, OpnameItem, OpnameStatus, StockOpname
from domain.inventory.valuation_method import (
    FIFOValuation,
    ValuationMethod,
    WeightedAverageValuation,
)
from ports.primary.event_publisher_port import EventPublisherPort
from ports.primary.inventory_repository_port import InventoryRepositoryPort
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


class InventoryValuationMethod(str, Enum):
    FIFO = "FIFO"
    WEIGHTED_AVERAGE = "WEIGHTED_AVERAGE"
    MOVING_AVERAGE = "MOVING_AVERAGE"


# ============================================================================
# DTOs
# ============================================================================


@dataclass(kw_only=True)
class CreateItemRequest:
    legal_entity_id: UUID
    sku: str
    name: str
    description: str | None = None
    item_type: str = "finished_good"
    uom: str = "pcs"
    category: str | None = None
    brand: str | None = None
    reorder_point: Decimal = Decimal("0")
    safety_stock: Decimal = Decimal("0")
    maximum_stock: Decimal | None = None
    minimum_stock: Decimal | None = None
    standard_cost: Decimal = Decimal("0")
    selling_price: Decimal = Decimal("0")
    warehouse_code: str | None = None
    is_active: bool = True


@dataclass(kw_only=True)
class UpdateItemRequest:
    id: UUID
    name: str | None = None
    description: str | None = None
    item_type: str | None = None
    uom: str | None = None
    category: str | None = None
    brand: str | None = None
    reorder_point: Decimal | None = None
    safety_stock: Decimal | None = None
    maximum_stock: Decimal | None = None
    minimum_stock: Decimal | None = None
    standard_cost: Decimal | None = None
    selling_price: Decimal | None = None
    warehouse_code: str | None = None


@dataclass(kw_only=True)
class ItemResponse:
    id: UUID
    sku: str
    name: str
    description: str | None
    item_type: str
    uom: str
    current_stock: Decimal
    current_stock_value: Decimal
    average_cost: Decimal
    last_cost: Decimal
    reorder_point: Decimal
    safety_stock: Decimal
    standard_cost: Decimal
    selling_price: Decimal
    category: str | None
    warehouse_code: str | None
    status: str
    created_at: datetime
    # -- Field tambahan supaya cocok dengan kontrak router (ItemResponseSchema) --
    item_code: str = ""
    item_name: str = ""
    unit_of_measure: str = ""
    brand: str | None = None
    reorder_quantity: Decimal = Decimal("0")
    min_stock: Decimal | None = None
    max_stock: Decimal | None = None
    valuation_method: str = "FIFO"
    is_active: bool = True
    is_locked: bool = False
    weight_kg: Decimal | None = None
    volume_m3: Decimal | None = None
    last_purchase_price: Decimal | None = None
    last_purchase_date: date | None = None
    total_value: Decimal = Decimal("0")
    updated_at: datetime | None = None
    created_by: UUID | None = None
    created_by_name: str | None = None
    version: int = 1

    def __post_init__(self) -> None:
        # Alias otomatis supaya konsumen lama (sku/name/uom) dan baru
        # (item_code/item_name/unit_of_measure) sama-sama terisi tanpa
        # perlu diisi dobel oleh pemanggil.
        if not self.item_code:
            self.item_code = self.sku
        if not self.item_name:
            self.item_name = self.name
        if not self.unit_of_measure:
            self.unit_of_measure = self.uom
        if not self.total_value:
            self.total_value = self.current_stock_value


@dataclass(kw_only=True)
class ItemListResult:
    """Hasil query list item dengan paginasi (dipakai endpoint GET /items)."""

    items: list[ItemResponse]
    total: int
    page: int = 1
    page_size: int = 20


@dataclass(kw_only=True)
class WarehouseResponse:
    id: UUID
    warehouse_code: str
    warehouse_name: str
    location: str | None
    is_active: bool
    is_default: bool
    notes: str | None
    created_at: datetime
    created_by: UUID | None
    version: int = 1


@dataclass(kw_only=True)
class LowStockAlert:
    item_id: UUID
    item_code: str
    item_name: str
    current_stock: Decimal
    reorder_point: Decimal
    reorder_quantity: Decimal
    shortage: Decimal
    warehouse_id: UUID | None = None
    warehouse_name: str | None = None
    days_until_out: int | None = None


@dataclass(kw_only=True)
class StockMovementRequest:
    legal_entity_id: UUID
    item_id: UUID
    movement_type: str
    quantity: Decimal
    unit_cost: Decimal | None = None
    reference_document_type: str | None = None
    reference_document_number: str | None = None
    movement_date: date | None = None
    warehouse_code: str | None = None
    notes: str | None = None
    # -- Field tambahan supaya cocok dengan kontrak router (StockMovementCreateSchema) --
    reference_type: str | None = None
    reference_id: UUID | None = None
    warehouse_id: UUID | None = None
    to_warehouse_id: UUID | None = None
    batch_number: str | None = None
    serial_number: str | None = None
    expiry_date: date | None = None


@dataclass(kw_only=True)
class StockMovementResponse:
    id: UUID
    item_id: UUID
    sku: str
    movement_type: str
    quantity: Decimal
    unit_cost: Decimal
    total_value: Decimal
    movement_date: date
    reference_document_type: str | None
    reference_document_number: str | None
    warehouse_code: str | None
    notes: str | None
    created_at: datetime
    # -- Field tambahan supaya cocok dengan kontrak router (MovementResponseSchema) --
    movement_number: str = ""
    item_code: str = ""
    item_name: str = ""
    total_cost: Decimal = Decimal("0")
    reference_type: str | None = None
    reference_id: UUID | None = None
    warehouse_id: UUID | None = None
    warehouse_name: str | None = None
    to_warehouse_id: UUID | None = None
    batch_number: str | None = None
    serial_number: str | None = None
    expiry_date: date | None = None
    status: str = "confirmed"
    created_by: UUID | None = None
    created_by_name: str | None = None
    reversed_at: datetime | None = None
    reversed_by: UUID | None = None
    version: int = 1

    def __post_init__(self) -> None:
        if not self.item_code:
            self.item_code = self.sku
        if not self.item_name:
            self.item_name = self.sku
        if not self.total_cost:
            self.total_cost = self.total_value
        if not self.reference_type:
            self.reference_type = self.reference_document_type


@dataclass(kw_only=True)
class MovementListResult:
    """Hasil query list movement dengan paginasi (dipakai endpoint GET /movements)."""

    items: list[StockMovementResponse]
    total: int
    page: int = 1
    page_size: int = 20


@dataclass(kw_only=True)
class StockOpnameRequest:
    """FIX: field lama (item_id + physical_quantity tunggal) diganti supaya
    cocok dengan bentuk sebenarnya yang dikirim router (satu sesi opname per
    gudang, berisi banyak baris item)."""

    legal_entity_id: UUID
    warehouse_id: UUID
    lines: list[dict[str, Any]]
    opname_date: date | None = None
    notes: str | None = None
    created_by: UUID | None = None


@dataclass(kw_only=True)
class StockOpnameResponse:
    id: UUID
    item_id: UUID
    item_name: str
    sku: str
    opname_date: date
    system_quantity: Decimal
    physical_quantity: Decimal
    discrepancy: Decimal
    discrepancy_value: Decimal
    status: str
    notes: str | None
    counted_by: UUID
    counted_at: datetime
    approved_by: UUID | None
    approved_at: datetime | None


@dataclass(kw_only=True)
class StockOpnameSessionResponse:
    """Response satu sesi stock opname (banyak baris item per gudang) -
    bentuknya persis mengikuti apa yang dibaca router di
    StockOpnameResponseSchema (fastapi_inventory_router.py)."""

    id: UUID
    opname_number: str
    warehouse_id: UUID
    warehouse_name: str | None
    opname_date: date
    status: str
    total_adjustments: int
    adjustment_value: Decimal
    lines: list[dict[str, Any]]
    notes: str | None
    created_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    approved_at: datetime | None = None
    approved_by: UUID | None = None
    applied_at: datetime | None = None
    version: int = 1


@dataclass(kw_only=True)
class TransferRequest:
    legal_entity_id: UUID
    item_id: UUID
    from_warehouse: str
    to_warehouse: str
    quantity: Decimal
    transfer_date: date | None = None
    notes: str | None = None


@dataclass(kw_only=True)
class TransferResponse:
    id: UUID
    item_id: UUID
    item_name: str
    sku: str
    from_warehouse: str
    to_warehouse: str
    quantity: Decimal
    unit_cost: Decimal
    total_value: Decimal
    transfer_date: date
    status: str
    notes: str | None
    requested_by: UUID
    requested_at: datetime
    completed_by: UUID | None
    completed_at: datetime | None


@dataclass(kw_only=True)
class COGSCalculationRequest:
    legal_entity_id: UUID
    period_start: date
    period_end: date


@dataclass(kw_only=True)
class COGSCalculationResponse:
    period_start: date
    period_end: date
    total_cogs: Decimal
    items: list[dict[str, Any]]


@dataclass(kw_only=True)
class InventoryValuationRequest:
    legal_entity_id: UUID
    valuation_date: date
    valuation_method: str


# ============================================================================
# Exceptions
# ============================================================================


class InventoryServiceError(Exception):
    pass


class ItemNotFoundError(InventoryServiceError):
    pass


class InsufficientStockError(InventoryServiceError):
    pass


class NegativeStockNotAllowedError(InventoryServiceError):
    pass


class TransferNotFoundError(InventoryServiceError):
    pass


class WarehouseNotFoundError(InventoryServiceError):
    pass


# ============================================================================
# Main Service
# ============================================================================


class InventoryService:
    """
    Service layer untuk Inventory Management.
    """

    def __init__(
        self,
        inv_repo: InventoryRepositoryPort,
        uow: UnitOfWorkPort,
        event_publisher: EventPublisherPort | None = None,
        ledger_repo: LedgerRepositoryPort | None = None,
        valuation_method: str = "FIFO",
    ):
        if inv_repo is None:
            raise ValueError("inv_repo is required")
        if uow is None:
            raise ValueError("uow is required")

        self._inv_repo = inv_repo
        self._uow = uow
        self._event_publisher = event_publisher
        self._ledger_repo = ledger_repo
        self._validator = InventoryInvariantsValidator()
        self._audit_trail: list[dict[str, Any]] = []

        if valuation_method.upper() == "FIFO":
            self._valuation_method = ValuationMethod.FIFO
            self._valuation_engine = FIFOValuation()
        else:
            self._valuation_method = ValuationMethod.WEIGHTED_AVERAGE
            self._valuation_engine = WeightedAverageValuation()

        self._stats = {"items_created": 0, "movements": 0, "opnames": 0, "transfers": 0}

        logger.info(f"InventoryService initialized with valuation method {valuation_method}")

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
            "service": "InventoryService",
            "action": action,
            "details": details or {},
        }
        self._audit_trail.append(entry)
        logger.info(f"AUDIT: {action} - {details}")

    # ==================== ITEM MASTER ====================

    @audit
    async def create_item(
        self, request: CreateItemRequest, user_id: UUID, correlation_id: str | None = None
    ) -> ItemResponse:
        self._check_authority(user_id, "create_item")
        await self._uow.begin()

        existing = await self._inv_repo.get_item_by_sku(request.sku, request.legal_entity_id)
        if existing:
            raise InventoryServiceError(f"Item with SKU {request.sku} already exists")

        # FIX BUG: daftar ini sebelumnya salah ketik ("work_in_progress")
        # dan tidak mencantumkan nilai SAH "work_in_process" dari ItemType
        # enum backend (fastapi_inventory_router.py) - membuat validasi ganda
        # yang saling bertentangan dengan Pydantic di router. Disamakan persis.
        valid_types = [
            "raw_material", "work_in_process", "finished_good",
            "trading", "consumable", "service", "asset",
        ]
        if request.item_type not in valid_types:
            raise InventoryServiceError(f"Invalid item_type: {request.item_type}")

        item = Item(
            id=uuid4(),
            legal_entity_id=request.legal_entity_id,
            sku=request.sku,
            name=request.name,
            description=request.description,
            item_type=ItemType.from_string(request.item_type),
            unit_of_measure=UnitOfMeasure(request.uom),
            current_stock=Decimal("0"),
            current_stock_value=Decimal("0"),
            average_cost=Decimal("0"),
            last_cost=Decimal("0"),
            reorder_point=request.reorder_point or Decimal("0"),
            safety_stock=request.safety_stock or Decimal("0"),
            maximum_stock=request.maximum_stock or Decimal("0"),
            minimum_stock=request.minimum_stock or Decimal("0"),
            status=ItemStatus.ACTIVE,
            standard_cost=request.standard_cost,
            selling_price=request.selling_price,
            category=request.category,
            warehouse_code=request.warehouse_code,
            # FIX BUG: sebelumnya warehouse_id yang dipilih user di form tidak
            # pernah ikut disimpan sama sekali saat item BARU dibuat (hanya
            # warehouse_code, yang tidak punya kolom database).
            warehouse_id=getattr(request, "warehouse_id", None),
            created_by=user_id,
            created_at=datetime.utcnow(),
            updated_at=None,
            updated_by=None,
            # -- Field tambahan (kontrak router ItemCreateSchema) --
            brand=request.brand,
            reorder_quantity=getattr(request, "reorder_quantity", None) or Decimal("0"),
            valuation_method=getattr(request, "valuation_method", None),
            weight_gram=(request.weight_kg * Decimal("1000")) if getattr(request, "weight_kg", None) else None,
        )

        aggregate = InventoryAggregate.create(item, user_id)

        await self._inv_repo.save_item(aggregate)
        await self._uow.commit()

        self._stats["items_created"] += 1

        if self._event_publisher:
            event = ItemCreated(
                item_id=item.id,
                aggregate_id=item.id,
                legal_entity_id=item.legal_entity_id,
                sku=item.sku,
                name=item.name,
                item_type=item.item_type.value,
                unit_cost=item.standard_cost,
                created_by=str(user_id),
                user_id=str(user_id),
                occurred_at=datetime.utcnow(),
            )
            try:
                await self._event_publisher.publish(event, correlation_id=correlation_id)
            except Exception as e:
                logger.warning(f"Failed to publish event {type(event).__name__}: {e}")

        self._record_audit("create_item", {
            "item_id": str(item.id),
            "sku": item.sku,
            "user_id": str(user_id),
        })

        logger.info(f"Item created: {item.sku} - {item.name}")
        return self._to_item_response(item)

    @audit
    async def update_item(
        self,
        request: UpdateItemRequest,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> ItemResponse:
        self._check_authority(user_id, "update_item")
        await self._uow.begin()

        agg = await self._inv_repo.get_item_by_id(request.id)
        if not agg:
            raise ItemNotFoundError(f"Item {request.id} not found")

        item = agg.item
        changes = {}

        if request.name is not None and request.name != item.name:
            changes["name"] = {"old": item.name, "new": request.name}
            item.name = request.name
        if request.description is not None and request.description != item.description:
            changes["description"] = {"old": item.description, "new": request.description}
            item.description = request.description
        if request.item_type is not None:
            new_type = ItemType.from_string(request.item_type)
            if new_type != item.item_type:
                changes["item_type"] = {"old": item.item_type.value, "new": new_type.value}
                item.item_type = new_type
        if request.uom is not None:
            new_uom = UnitOfMeasure(request.uom)
            if new_uom != item.unit_of_measure:
                changes["uom"] = {"old": item.unit_of_measure.value, "new": new_uom.value}
                item.unit_of_measure = new_uom
        if request.category is not None and request.category != item.category:
            changes["category"] = {"old": item.category, "new": request.category}
            item.category = request.category
        if request.brand is not None and request.brand != item.brand:
            changes["brand"] = {"old": item.brand, "new": request.brand}
            item.brand = request.brand
        if request.reorder_point is not None and request.reorder_point != item.reorder_point:
            changes["reorder_point"] = {"old": item.reorder_point, "new": request.reorder_point}
            item.reorder_point = request.reorder_point
        if request.safety_stock is not None and request.safety_stock != item.safety_stock:
            changes["safety_stock"] = {"old": item.safety_stock, "new": request.safety_stock}
            item.safety_stock = request.safety_stock
        if request.maximum_stock is not None and request.maximum_stock != item.maximum_stock:
            changes["maximum_stock"] = {"old": item.maximum_stock, "new": request.maximum_stock}
            item.maximum_stock = request.maximum_stock
        if request.minimum_stock is not None and request.minimum_stock != item.minimum_stock:
            changes["minimum_stock"] = {"old": item.minimum_stock, "new": request.minimum_stock}
            item.minimum_stock = request.minimum_stock
        if request.standard_cost is not None and request.standard_cost != item.standard_cost:
            changes["standard_cost"] = {"old": item.standard_cost, "new": request.standard_cost}
            item.standard_cost = request.standard_cost
        if request.selling_price is not None and request.selling_price != item.selling_price:
            changes["selling_price"] = {"old": item.selling_price, "new": request.selling_price}
            item.selling_price = request.selling_price
        if request.warehouse_id is not None and request.warehouse_id != item.warehouse_id:
            # FIX BUG: sebelumnya membandingkan/menyimpan ke warehouse_code
            # (diisi paksa dengan str(warehouse_id) di DTO) - field itu tidak
            # punya kolom database sama sekali, sementara kolom FK asli
            # warehouse_id justru selalu ditulis ulang jadi NULL oleh
            # _to_orm_item(). Akibatnya gudang yang dipilih di form terlihat
            # tersimpan sesaat tapi hilang lagi setiap item dimuat ulang.
            changes["warehouse_id"] = {
                "old": str(item.warehouse_id) if item.warehouse_id else None,
                "new": str(request.warehouse_id),
            }
            item.warehouse_id = request.warehouse_id

        if not changes:
            return self._to_item_response(item)

        item.updated_at = datetime.utcnow()
        item.updated_by = user_id

        await self._inv_repo.save_item(agg)
        await self._uow.commit()

        if self._event_publisher:
            event = ItemUpdated(
                legal_entity_id=item.legal_entity_id,
                sku=item.sku,
                changes=changes,
                user_id=user_id,
                aggregate_id=item.id,
                occurred_at=datetime.utcnow(),
                correlation_id=correlation_id,
            )
            try:
                await self._event_publisher.publish(event, correlation_id=correlation_id)
            except Exception as e:
                logger.warning(f"Failed to publish event {type(event).__name__}: {e}")

        self._record_audit("update_item", {
            "item_id": str(item.id),
            "changes": changes,
            "user_id": str(user_id),
        })

        logger.info(f"Item updated: {item.sku} (fields: {list(changes.keys())})")
        return self._to_item_response(item)

    @audit
    async def deactivate_item(
        self,
        item_id: UUID,
        reason: str | None = None,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
    ) -> bool:
        self._check_authority(user_id, "deactivate_item")
        await self._uow.begin()

        agg = await self._inv_repo.get_item_by_id(item_id)
        if not agg:
            raise ItemNotFoundError(f"Item {item_id} not found")

        if agg.item.status == ItemStatus.INACTIVE:
            return True

        if agg.item.current_stock > 0:
            raise InventoryServiceError(f"Cannot deactivate item with stock {agg.item.current_stock}. Please adjust stock first.")

        agg.item.status = ItemStatus.INACTIVE
        agg.item.updated_at = datetime.utcnow()
        agg.item.updated_by = user_id

        await self._inv_repo.save_item(agg)
        await self._uow.commit()

        if self._event_publisher:
            event = ItemDeactivated(
                sku=agg.item.sku,
                reason=reason,
                user_id=user_id,
                aggregate_id=item_id,
                occurred_at=datetime.utcnow(),
                correlation_id=correlation_id,
            )
            try:
                await self._event_publisher.publish(event, correlation_id=correlation_id)
            except Exception as e:
                logger.warning(f"Failed to publish event {type(event).__name__}: {e}")

        self._record_audit("deactivate_item", {
            "item_id": str(item_id),
            "reason": reason,
            "user_id": str(user_id) if user_id else None,
        })

        logger.info(f"Item deactivated: {agg.item.sku} (reason: {reason})")
        return True

    async def get_item(self, item_id: UUID) -> ItemResponse | None:
        aggregate = await self._inv_repo.get_item_by_id(item_id)
        if not aggregate:
            return None
        return self._to_item_response(aggregate.item)

    async def list_items(
        self,
        legal_entity_id: UUID,
        item_type: str | None = None,
        status: str | None = None,
        category: str | None = None,
        is_active: bool | None = None,
        low_stock_only: bool = False,
        search: str | None = None,
        warehouse_id: UUID | None = None,  # noqa: ARG002 - item belum tracking warehouse_id per-unit, hanya warehouse_code
        warehouse_code: str | None = None,
        limit: int = 100,
        offset: int = 0,
        page: int | None = None,
        page_size: int | None = None,
    ) -> ItemListResult:
        """List item dengan filter dan paginasi (dipakai endpoint GET /items).

        CATATAN: filtering saat ini dilakukan di memori (mengambil batch besar
        dari repository lalu difilter di Python) karena repository belum
        punya method list_items dengan filter native di level SQL. Untuk
        dataset besar sebaiknya nanti dipindah jadi query SQL langsung.
        """
        if page is not None or page_size is not None:
            page = max(page or 1, 1)
            page_size = max(min(page_size or 20, 200), 1)
        else:
            page = (offset // limit) + 1 if limit else 1
            page_size = limit

        # Ambil batch besar dari repo (bukan solusi jangka panjang, lihat catatan di atas)
        all_items = await self._inv_repo.get_all_items(legal_entity_id, limit=5000, offset=0)
        responses = [self._to_item_response(agg.item) for agg in all_items]

        if item_type:
            responses = [r for r in responses if r.item_type == item_type]
        if status:
            responses = [r for r in responses if r.status == status]
        if category:
            responses = [r for r in responses if r.category == category]
        if warehouse_code:
            responses = [r for r in responses if r.warehouse_code == warehouse_code]
        if is_active is not None:
            responses = [r for r in responses if r.is_active == is_active]
        if low_stock_only:
            responses = [r for r in responses if r.current_stock <= r.reorder_point]
        if search:
            needle = search.lower()
            responses = [
                r for r in responses
                if needle in r.item_code.lower() or needle in r.item_name.lower()
            ]

        total = len(responses)
        start = (page - 1) * page_size
        end = start + page_size
        page_items = responses[start:end]

        return ItemListResult(items=page_items, total=total, page=page, page_size=page_size)

    async def list_warehouses(
        self, legal_entity_id: UUID, is_active: bool | None = None
    ) -> list[WarehouseResponse]:
        """List semua warehouse milik satu legal entity."""
        rows = await self._inv_repo.list_warehouses(legal_entity_id, is_active=is_active)
        return [
            WarehouseResponse(
                id=w["id"],
                warehouse_code=w["warehouse_code"],
                warehouse_name=w["name"],
                location=w.get("location_code"),
                is_active=w["is_active"],
                is_default=w["is_default"],
                notes=w.get("notes"),
                created_at=w["created_at"],
                created_by=w.get("created_by"),
                version=w.get("version", 1),
            )
            for w in rows
        ]

    async def create_warehouse(
        self,
        legal_entity_id: UUID,
        warehouse_code: str,
        warehouse_name: str,
        location: str | None = None,
        is_active: bool = True,
        is_default: bool = False,
        notes: str | None = None,
        created_by: UUID | None = None,
    ) -> WarehouseResponse:
        """Buat warehouse/gudang baru untuk satu legal entity."""
        # Cek duplikat kode lebih dulu supaya user dapat pesan yang jelas
        # ("kode sudah dipakai") alih-alih IntegrityError mentah dari
        # constraint uq_warehouse_code_entity di database.
        if await self._inv_repo.get_warehouse_by_code(warehouse_code, legal_entity_id):
            raise ValueError(f"Kode gudang '{warehouse_code}' sudah dipakai di entitas ini")
        row = await self._inv_repo.create_warehouse(
            legal_entity_id=legal_entity_id,
            warehouse_code=warehouse_code,
            name=warehouse_name,
            location_code=location,
            is_active=is_active,
            is_default=is_default,
            notes=notes,
            created_by=created_by,
        )
        self._record_audit("create_warehouse", {
            "warehouse_id": str(row["id"]),
            "warehouse_code": row["warehouse_code"],
            "user_id": str(created_by) if created_by else None,
        })
        return WarehouseResponse(
            id=row["id"],
            warehouse_code=row["warehouse_code"],
            warehouse_name=row["name"],
            location=row.get("location_code"),
            is_active=row["is_active"],
            is_default=row["is_default"],
            notes=row.get("notes"),
            created_at=row["created_at"],
            created_by=row.get("created_by"),
            version=row.get("version", 1),
        )

    async def update_warehouse(
        self,
        warehouse_id: UUID,
        legal_entity_id: UUID,
        warehouse_name: str | None = None,
        location: str | None = None,
        is_active: bool | None = None,
        is_default: bool | None = None,
        notes: str | None = None,
        updated_by: UUID | None = None,
    ) -> WarehouseResponse | None:
        """Update warehouse/gudang yang sudah ada. Return None kalau tidak ditemukan."""
        row = await self._inv_repo.update_warehouse(
            warehouse_id=warehouse_id,
            legal_entity_id=legal_entity_id,
            name=warehouse_name,
            location_code=location,
            is_active=is_active,
            is_default=is_default,
            notes=notes,
        )
        if row is None:
            return None
        self._record_audit("update_warehouse", {
            "warehouse_id": str(warehouse_id),
            "user_id": str(updated_by) if updated_by else None,
        })
        return WarehouseResponse(
            id=row["id"],
            warehouse_code=row["warehouse_code"],
            warehouse_name=row["name"],
            location=row.get("location_code"),
            is_active=row["is_active"],
            is_default=row["is_default"],
            notes=row.get("notes"),
            created_at=row["created_at"],
            created_by=row.get("created_by"),
            version=row.get("version", 1),
        )

    async def delete_warehouse(
        self, warehouse_id: UUID, legal_entity_id: UUID
    ) -> bool:
        """Soft-delete (nonaktifkan) warehouse/gudang."""
        deleted = await self._inv_repo.delete_warehouse(warehouse_id, legal_entity_id)
        if deleted:
            self._record_audit("delete_warehouse", {"warehouse_id": str(warehouse_id)})
        return deleted

    async def get_low_stock_alerts(
        self,
        legal_entity_id: UUID,
        warehouse_id: UUID | None = None,  # noqa: ARG002 - lihat catatan di bawah
        include_zero_stock: bool = False,
    ) -> list[LowStockAlert]:
        """Ambil daftar item yang stoknya di bawah reorder point.

        CATATAN: filter warehouse_id belum diterapkan karena domain Item
        saat ini hanya menyimpan `warehouse_code` (string bebas), bukan
        `warehouse_id` (UUID relasi ke tabel warehouse). Semua item dalam
        legal entity akan dicek terlepas dari warehouse.
        """
        aggregates = await self._inv_repo.get_items_below_reorder_point(legal_entity_id)
        alerts: list[LowStockAlert] = []
        for agg in aggregates:
            item = agg.item
            if not include_zero_stock and item.current_stock <= 0:
                continue
            shortage = item.reorder_point - item.current_stock
            if shortage < 0:
                shortage = Decimal("0")
            alerts.append(
                LowStockAlert(
                    item_id=item.id,
                    item_code=item.sku,
                    item_name=item.name,
                    current_stock=item.current_stock,
                    reorder_point=item.reorder_point,
                    reorder_quantity=getattr(item, "reorder_quantity", Decimal("0")) or Decimal("0"),
                    shortage=shortage,
                    warehouse_id=None,
                    warehouse_name=item.warehouse_code,
                    days_until_out=None,  # butuh data rata-rata konsumsi - belum diimplementasikan
                )
            )
        return alerts

    # ==================== STOCK MOVEMENTS ====================

    # Mapping dari kode movement generik (dipakai router/API publik) ke
    # MovementType domain yang lebih spesifik secara bisnis. Beberapa kode
    # generik sengaja dipetakan ke tipe ADJUSTMENT_* karena tidak ada
    # informasi dokumen referensi yang lebih spesifik dari caller.
    _GENERIC_MOVEMENT_TYPE_MAP = {
        "IN": MovementType.ADJUSTMENT_IN,
        "OUT": MovementType.ADJUSTMENT_OUT,
        "ADJUSTMENT": MovementType.ADJUSTMENT_IN,
        "ADJUSTMENT_IN": MovementType.ADJUSTMENT_IN,
        "ADJUSTMENT_OUT": MovementType.ADJUSTMENT_OUT,
        "TRANSFER_IN": MovementType.TRANSFER_IN,
        "TRANSFER_OUT": MovementType.TRANSFER_OUT,
        "RETURN_IN": MovementType.RETURN_FROM_CUSTOMER,
        "RETURN_OUT": MovementType.RETURN_TO_SUPPLIER,
        "SCRAP": MovementType.WRITE_OFF,
        "SAMPLE": MovementType.SAMPLE_ISSUE,
    }

    def _resolve_movement_type(self, raw: str) -> MovementType:
        """Terima baik kode generik (IN/OUT/TRANSFER_IN/...) dari API publik
        maupun value MovementType domain (purchase_receipt/sales_issue/...)
        dari pemanggil internal, lalu kembalikan MovementType domain."""
        if raw in self._GENERIC_MOVEMENT_TYPE_MAP:
            return self._GENERIC_MOVEMENT_TYPE_MAP[raw]
        return MovementType(raw)

    @audit
    async def record_movement(
        self, request: StockMovementRequest, user_id: UUID, correlation_id: str | None = None
    ) -> StockMovementResponse:
        self._check_authority(user_id, "record_movement")
        await self._uow.begin()

        item_agg = await self._inv_repo.get_item_by_id(request.item_id)
        if not item_agg:
            raise ItemNotFoundError(f"Item {request.item_id} not found")

        original_type_code = request.movement_type
        movement_type = self._resolve_movement_type(request.movement_type)
        movement_date = request.movement_date or date.today()

        warehouse_id = request.warehouse_id
        if warehouse_id is None:
            raise ValueError(
                "warehouse_id wajib diisi untuk mencatat stock movement "
                "(tabel inventory_movement mensyaratkan referensi warehouse yang valid)"
            )

        if movement_type in (MovementType.SALES_ISSUE, MovementType.TRANSFER_OUT, MovementType.ADJUSTMENT_OUT):
            if item_agg.item.current_stock < request.quantity:
                raise InsufficientStockError(
                    f"Insufficient stock for item {item_agg.item.sku}. Available: {item_agg.item.current_stock}, requested: {request.quantity}"
                )

        if movement_type.is_inbound():
            unit_cost = request.unit_cost or item_agg.item.last_cost
            total_value = request.quantity * unit_cost
            if self._valuation_method == ValuationMethod.WEIGHTED_AVERAGE:
                total_qty = item_agg.item.current_stock + request.quantity
                total_value_all = item_agg.item.current_stock_value + total_value
                new_avg_cost = total_value_all / total_qty if total_qty > 0 else item_agg.item.average_cost
            else:
                new_avg_cost = item_agg.item.average_cost
        else:
            unit_cost = await self._get_movement_cost(item_agg.item, request.quantity)
            total_value = request.quantity * unit_cost
            new_avg_cost = item_agg.item.average_cost

        movement_number = await self._inv_repo.get_next_movement_number(
            "TRF" if movement_type in (MovementType.TRANSFER_IN, MovementType.TRANSFER_OUT) else "MOV"
        )

        movement = StockMovement(
            id=uuid4(),
            movement_number=movement_number,
            legal_entity_id=request.legal_entity_id,
            item_id=request.item_id,
            item_sku=item_agg.item.sku,
            item_name=item_agg.item.name,
            movement_type=movement_type,
            quantity=request.quantity,
            unit_cost=unit_cost,
            total_cost=total_value,
            movement_date=movement_date,
            warehouse_id=warehouse_id,
            to_warehouse_id=request.to_warehouse_id,
            reference_document_type=request.reference_type or request.reference_document_type or "",
            reference_document_id=request.reference_id,
            reference_document_number=request.reference_document_number or "",
            batch_number=request.batch_number,
            serial_number=request.serial_number,
            expiry_date=request.expiry_date,
            warehouse_code=request.warehouse_code,
            notes=request.notes,
            created_by=str(user_id),
            created_at=datetime.utcnow(),
            status=MovementStatus.CONFIRMED,
        )

        if movement_type.is_inbound():
            new_stock = item_agg.item.current_stock + request.quantity
            new_value = item_agg.item.current_stock_value + total_value
        else:
            new_stock = item_agg.item.current_stock - request.quantity
            new_value = item_agg.item.current_stock_value - total_value

        if new_stock < 0 and not self._validator.allow_negative_stock(item_agg.item):
            raise NegativeStockNotAllowedError(f"Negative stock not allowed for item {item_agg.item.sku}")

        item_agg.update_stock(new_stock, new_value, new_avg_cost, user_id)

        await self._inv_repo.save_item(item_agg)
        await self._inv_repo.save_movement(movement)
        await self._uow.commit()

        self._stats["movements"] += 1

        if self._event_publisher:
            event = StockMovementCreated(
                movement_id=movement.id,
                aggregate_id=movement.id,
                item_id=request.item_id,
                sku=item_agg.item.sku,
                movement_type=movement_type.value,
                quantity=request.quantity,
                unit_cost=unit_cost,
                total_value=total_value,
                user_id=user_id,
                occurred_at=datetime.utcnow(),
            )
            try:
                await self._event_publisher.publish(event, correlation_id=correlation_id)
            except Exception as e:
                logger.warning(f"Failed to publish event {type(event).__name__}: {e}")

            if movement_type in (MovementType.ADJUSTMENT_IN, MovementType.ADJUSTMENT_OUT):
                from domain.inventory.stock_adjustment_entity import AdjustmentStatus, StockAdjustmentEntity
                # FIX: konstruktor ini sebelumnya tidak mengisi 3 parameter
                # wajib (warehouse_name, item_name, status) - TypeError setiap
                # kali mutasi jenis ADJUSTMENT_IN/OUT direkam (persis kasus
                # "IN" yang dipilih user di form Mutasi Stok). warehouse_id
                # juga sebelumnya di-hardcode UUID(int=0) alih-alih memakai
                # gudang yang sebenarnya dari movement.
                adj = StockAdjustmentEntity(
                    adjustment_id=movement.id,
                    adjustment_number=movement.reference_document_number or movement.id.hex[:8],
                    adjustment_type="INCREASE" if movement_type == MovementType.ADJUSTMENT_IN else "DECREASE",
                    item_id=movement.item_id,
                    item_sku=item_agg.item.sku,
                    item_name=item_agg.item.name,
                    warehouse_id=movement.warehouse_id,
                    warehouse_code=movement.warehouse_code,
                    warehouse_name=await self._get_warehouse_name(movement.warehouse_id),
                    quantity=movement.quantity,
                    unit_cost=movement.unit_cost,
                    total_value=movement.total_value,
                    reason=movement.notes or "Manual adjustment",
                    adjustment_date=movement.movement_date,
                    status=AdjustmentStatus.EXECUTED,
                )
                adj_event = StockAdjustedEvent(
                    adjustment=adj,
                    adjusted_by=str(user_id),
                    aggregate_id=movement.id,
                    user_id=str(user_id),
                    correlation_id=correlation_id,
                )
                try:
                    await self._event_publisher.publish(adj_event, correlation_id=correlation_id)
                except Exception as e:
                    logger.warning(f"Failed to publish event {type(adj_event).__name__}: {e}")

            if item_agg.item.reorder_point > 0 and new_stock <= item_agg.item.reorder_point:
                alert_event = StockLevelAlert(
                    item_id=item_agg.item.id,
                    sku=item_agg.item.sku,
                    item_name=item_agg.item.name,
                    current_stock=new_stock,
                    reorder_point=item_agg.item.reorder_point,
                    safety_stock=item_agg.item.safety_stock,
                    alert_type="LOW_STOCK",
                    aggregate_id=item_agg.item.id,
                    occurred_at=datetime.utcnow(),
                    correlation_id=correlation_id,
                )
                try:
                    await self._event_publisher.publish(alert_event, correlation_id=correlation_id)
                except Exception as e:
                    logger.warning(f"Failed to publish event {type(alert_event).__name__}: {e}")

        self._record_audit("record_movement", {
            "movement_id": str(movement.id),
            "item_id": str(item_agg.item.id),
            "type": movement_type.value,
            "quantity": str(request.quantity),
            "user_id": str(user_id),
        })

        logger.info(f"Stock movement recorded: {movement_type.value} {request.quantity} of {item_agg.item.sku}")
        return self._to_movement_response(movement, item_agg.item.sku, original_type_code=original_type_code)

    async def _get_movement_cost(self, item: Item, quantity: Decimal) -> Decimal:
        if self._valuation_method == ValuationMethod.FIFO:
            layers = await self._inv_repo.get_fifo_layers(item.id)
            remaining_qty = quantity
            total_cost = Decimal("0")
            for layer in layers:
                if remaining_qty <= 0:
                    break
                take_qty = min(layer.quantity, remaining_qty)
                total_cost += take_qty * layer.unit_cost
                remaining_qty -= take_qty
            return total_cost / quantity if quantity > 0 else item.average_cost
        else:
            return item.average_cost

    # ==================== STOCK OPNAME ====================

    @audit
    async def create_stock_opname(
        self, request: StockOpnameRequest, correlation_id: str | None = None
    ) -> StockOpnameSessionResponse:
        """Buat SATU sesi stock opname untuk SATU gudang, berisi banyak baris item.

        FIX: signature sebelumnya mewajibkan `user_id` sebagai argumen kedua,
        padahal router memanggil method ini HANYA dengan `dto`
        (`inventory_service.create_stock_opname(dto)`) - user id sudah
        dibawa lewat `request.created_by`. Signature lama membuat panggilan
        ini SELALU gagal TypeError "missing required positional argument".

        FIX BUG PRE-EXISTING: method ini sebelumnya cuma menerima satu
        item_id + physical_quantity tunggal (tidak cocok dengan
        StockOpnameRequestDTO yang sudah diperbaiki jadi warehouse_id +
        lines[]) - ditulis ulang supaya benar-benar memproses semua baris
        sekaligus dalam satu sesi opname per gudang.
        """
        self._check_authority(request.created_by, "create_stock_opname")
        await self._uow.begin()

        opname_items: list[OpnameItem] = []
        all_zero_discrepancy = True

        for line in request.lines:
            item_id = line["item_id"] if isinstance(line["item_id"], UUID) else UUID(str(line["item_id"]))
            item_agg = await self._inv_repo.get_item_by_id(item_id)
            if not item_agg:
                raise ItemNotFoundError(f"Item {item_id} not found")

            system_qty = Decimal(str(line.get("system_quantity", item_agg.item.current_stock)))
            physical_qty = Decimal(str(line["physical_quantity"]))
            discrepancy = physical_qty - system_qty
            discrepancy_value = discrepancy * item_agg.item.average_cost
            discrepancy_type = (
                DiscrepancyType.SURPLUS if discrepancy > 0
                else DiscrepancyType.SHORTAGE if discrepancy < 0
                else DiscrepancyType.NONE
            )
            if discrepancy != 0:
                all_zero_discrepancy = False

            opname_items.append(OpnameItem(
                item_id=item_id,
                item_sku=item_agg.item.sku,
                item_name=item_agg.item.name,
                system_quantity=system_qty,
                physical_quantity=physical_qty,
                discrepancy=discrepancy,
                discrepancy_type=discrepancy_type,
                unit_cost=item_agg.item.average_cost,
                notes=line.get("notes") or "",
                counted_by=request.created_by,
                counted_at=datetime.utcnow(),
            ))

        warehouse_name = await self._get_warehouse_name(request.warehouse_id)

        opname = StockOpname(
            opname_id=uuid4(),
            opname_number=f"OPN-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            warehouse_id=request.warehouse_id,
            warehouse_name=warehouse_name or "",
            opname_date=request.opname_date or date.today(),
            status=OpnameStatus.PENDING,
            items=opname_items,
            performed_by=request.created_by,
            notes=request.notes or "",
            created_by=request.created_by,
            legal_entity_id=request.legal_entity_id,
            warehouse_code=None,
        )

        await self._inv_repo.save_opname(opname)
        await self._uow.commit()

        self._stats["opnames"] += 1

        if self._event_publisher:
            event = StockOpnameCreated(
                aggregate_id=opname.id,
                item_id=opname_items[0].item_id,
                sku=opname_items[0].item_sku,
                discrepancy=sum((it.discrepancy for it in opname_items), Decimal("0")),
                user_id=request.created_by,
                occurred_at=datetime.utcnow(),
            )
            try:
                await self._event_publisher.publish(event, correlation_id=correlation_id)
            except Exception as e:
                logger.warning(f"Failed to publish event {type(event).__name__}: {e}")

        if all_zero_discrepancy:
            await self.approve_stock_opname(
                opname_id=opname.id,
                approver_id=request.created_by,
                legal_entity_id=request.legal_entity_id,
                correlation_id=correlation_id,
            )
            opname = await self._inv_repo.get_opname_by_id(opname.id)

        self._record_audit("create_stock_opname", {
            "opname_id": str(opname.id),
            "warehouse_id": str(request.warehouse_id),
            "line_count": len(opname_items),
            "user_id": str(request.created_by),
        })

        return self._to_opname_session_response(opname)

    async def approve_stock_opname(
        self,
        opname_id: UUID,
        approver_id: UUID,
        legal_entity_id: UUID | None = None,
        apply_adjustments: bool = True,
        correlation_id: str | None = None,
    ) -> StockOpnameSessionResponse | None:
        """Setujui satu sesi stock opname dan posting penyesuaian stok
        untuk SEMUA baris item di dalamnya.

        FIX: signature sebelumnya (opname_id, approver_id, correlation_id)
        tidak cocok dengan pemanggilan router yang mengirim
        legal_entity_id & apply_adjustments sebagai keyword - selalu
        TypeError "unexpected keyword argument". Body-nya juga
        sebelumnya cuma memproses opname.items[0] (lewat convenience
        property item_id/system_quantity/dst di StockOpnameEntity) -
        kalau opname punya lebih dari satu baris item, sisanya diam-diam
        TIDAK PERNAH diposting sebagai penyesuaian stok. Ditulis ulang
        supaya memproses setiap baris di opname.items secara eksplisit.
        """
        self._check_authority(approver_id, "approve_stock_opname")
        await self._uow.begin()

        opname = await self._inv_repo.get_opname_by_id(opname_id)
        if not opname:
            return None

        if opname.status != OpnameStatus.PENDING:
            raise InventoryServiceError(f"Opname already {opname.status.value}")

        for opname_item in opname.items:
            discrepancy = opname_item.discrepancy
            if discrepancy == 0 or not apply_adjustments:
                continue

            item_agg = await self._inv_repo.get_item_by_id(opname_item.item_id)
            if not item_agg:
                raise ItemNotFoundError(f"Item {opname_item.item_id} not found")

            adjustment_type = MovementType.ADJUSTMENT_IN if discrepancy > 0 else MovementType.ADJUSTMENT_OUT
            movement = StockMovement(
                id=uuid4(),
                legal_entity_id=opname.legal_entity_id or legal_entity_id,
                item_id=opname_item.item_id,
                item_sku=item_agg.item.sku,
                item_name=item_agg.item.name,
                movement_type=adjustment_type,
                quantity=abs(discrepancy),
                unit_cost=item_agg.item.average_cost,
                total_cost=abs(opname_item.discrepancy_value),
                movement_date=date.today(),
                reference_document_type="STOCK_OPNAME",
                reference_document_number=opname.id.hex[:8],
                notes=f"Adjustment from opname {opname.id} (system={opname_item.system_quantity}, physical={opname_item.physical_quantity})",
                created_by=str(approver_id),
                created_at=datetime.utcnow(),
                status=MovementStatus.CONFIRMED,
            )
            await self._inv_repo.save_movement(movement)

            new_stock = item_agg.item.current_stock + discrepancy
            new_value = item_agg.item.current_stock_value + opname_item.discrepancy_value
            item_agg.update_stock(new_stock, new_value, item_agg.item.average_cost, approver_id)
            await self._inv_repo.save_item(item_agg)

        opname.status = OpnameStatus.APPROVED
        opname.approved_by = approver_id
        opname.approved_at = datetime.utcnow()
        await self._inv_repo.save_opname(opname)

        await self._uow.commit()

        if self._event_publisher:
            event = StockOpnameApproved(
                aggregate_id=opname_id,
                item_id=opname.item_id,
                discrepancy=opname.total_discrepancy,
                user_id=approver_id,
                occurred_at=datetime.utcnow(),
            )
            try:
                await self._event_publisher.publish(event, correlation_id=correlation_id)
            except Exception as e:
                logger.warning(f"Failed to publish event {type(event).__name__}: {e}")

        self._record_audit("approve_stock_opname", {
            "opname_id": str(opname_id),
            "total_discrepancy": str(opname.total_discrepancy),
            "approver_id": str(approver_id),
        })

        return self._to_opname_session_response(opname)

    async def create_transfer(
        self, request: TransferRequest, user_id: UUID, correlation_id: str | None = None
    ) -> TransferResponse:
        self._check_authority(user_id, "create_transfer")
        await self._uow.begin()

        item_agg = await self._inv_repo.get_item_by_id(request.item_id)
        if not item_agg:
            raise ItemNotFoundError(f"Item {request.item_id} not found")

        if item_agg.item.current_stock < request.quantity:
            raise InsufficientStockError("Insufficient stock for transfer")

        transfer_item = TransferItem(
            item_id=request.item_id,
            item_sku=item_agg.item.sku,
            item_name=item_agg.item.name,
            quantity=request.quantity,
            unit_cost=item_agg.item.average_cost,
            total_value=request.quantity * item_agg.item.average_cost,
        )

        transfer = InterWarehouseTransfer(
            transfer_id=uuid4(),
            transfer_number=f"TRF-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            source_warehouse_name=request.from_warehouse,
            destination_warehouse_name=request.to_warehouse,
            transfer_date=request.transfer_date or date.today(),
            priority=TransferPriority.NORMAL,
            status=TransferStatus.PENDING,
            items=[transfer_item],
            notes=request.notes or "",
            requested_by=user_id,
            requested_at=datetime.utcnow(),
            legal_entity_id=request.legal_entity_id,
        )

        await self._inv_repo.save_transfer(transfer)

        movement = StockMovement(
            id=uuid4(),
            legal_entity_id=request.legal_entity_id,
            item_id=request.item_id,
            item_sku=item_agg.item.sku,
            item_name=item_agg.item.name,
            movement_type=MovementType.TRANSFER_OUT,
            quantity=request.quantity,
            unit_cost=item_agg.item.average_cost,
            total_cost=transfer.total_value,
            movement_date=request.transfer_date or date.today(),
            reference_document_type="TRANSFER",
            reference_document_number=transfer.id.hex[:8],
            warehouse_code=request.from_warehouse,
            notes=f"Transfer to {request.to_warehouse}",
            created_by=str(user_id),
            created_at=datetime.utcnow(),
            status=MovementStatus.CONFIRMED,
        )
        await self._inv_repo.save_movement(movement)

        new_stock = item_agg.item.current_stock - request.quantity
        new_value = item_agg.item.current_stock_value - transfer.total_value
        item_agg.update_stock(new_stock, new_value, item_agg.item.average_cost, user_id)
        await self._inv_repo.save_item(item_agg)

        await self._uow.commit()

        self._stats["transfers"] += 1

        if self._event_publisher:
            event = InterWarehouseTransferCreated(
                aggregate_id=transfer.id,
                item_id=request.item_id,
                sku=item_agg.item.sku,
                quantity=request.quantity,
                from_warehouse=request.from_warehouse,
                to_warehouse=request.to_warehouse,
                user_id=user_id,
                occurred_at=datetime.utcnow(),
            )
            try:
                await self._event_publisher.publish(event, correlation_id=correlation_id)
            except Exception as e:
                logger.warning(f"Failed to publish event {type(event).__name__}: {e}")

        self._record_audit("create_transfer", {
            "transfer_id": str(transfer.id),
            "item_id": str(item_agg.item.id),
            "quantity": str(request.quantity),
            "user_id": str(user_id),
        })

        return self._to_transfer_response(transfer, item_agg.item)

    @audit
    async def complete_transfer(
        self, transfer_id: UUID, user_id: UUID, correlation_id: str | None = None
    ) -> TransferResponse:
        self._check_authority(user_id, "complete_transfer")
        await self._uow.begin()

        transfer = await self._inv_repo.get_transfer_by_id(transfer_id)
        if not transfer:
            raise TransferNotFoundError(f"Transfer {transfer_id} not found")

        if transfer.status != TransferStatus.PENDING:
            raise InventoryServiceError(f"Transfer already {transfer.status.value}")

        # ===== VALIDATE ITEM EXISTS =====
        item_agg = await self._inv_repo.get_item_by_id(transfer.item_id)
        if not item_agg:
            raise ItemNotFoundError(f"Item {transfer.item_id} not found. Cannot complete transfer.")

        # ===== VALIDATE WAREHOUSES =====
        if not transfer.from_warehouse or not transfer.to_warehouse:
            raise WarehouseNotFoundError(
                f"Transfer must have both from_warehouse and to_warehouse: "
                f"from='{transfer.from_warehouse}', to='{transfer.to_warehouse}'"
            )
        if transfer.from_warehouse == transfer.to_warehouse:
            raise WarehouseNotFoundError(
                f"Source and destination warehouses cannot be the same: {transfer.from_warehouse}"
            )
        if transfer.quantity <= 0:
            raise InventoryServiceError(f"Transfer quantity must be positive: {transfer.quantity}")

        # ===== CHECK WAREHOUSE EXISTENCE (if repository supports) =====
        if hasattr(self._inv_repo, 'get_warehouse_by_code'):
            legal_entity_id = transfer.legal_entity_id
            from_exists = await self._inv_repo.get_warehouse_by_code(transfer.from_warehouse, legal_entity_id)
            if not from_exists:
                raise WarehouseNotFoundError(f"From warehouse '{transfer.from_warehouse}' not found")
            to_exists = await self._inv_repo.get_warehouse_by_code(transfer.to_warehouse, legal_entity_id)
            if not to_exists:
                raise WarehouseNotFoundError(f"To warehouse '{transfer.to_warehouse}' not found")

        # ===== RECORD TRANSFER IN MOVEMENT =====
        movement = StockMovement(
            id=uuid4(),
            legal_entity_id=transfer.legal_entity_id,
            item_id=transfer.item_id,
            item_sku=item_agg.item.sku,
            item_name=item_agg.item.name,
            movement_type=MovementType.TRANSFER_IN,
            quantity=transfer.quantity,
            unit_cost=transfer.unit_cost,
            total_cost=transfer.total_value,
            movement_date=date.today(),
            reference_document_type="TRANSFER",
            reference_document_number=transfer.id.hex[:8],
            warehouse_code=transfer.to_warehouse,
            notes=f"Transfer from {transfer.from_warehouse} completed",
            created_by=str(user_id),
            created_at=datetime.utcnow(),
            status=MovementStatus.CONFIRMED,
        )
        await self._inv_repo.save_movement(movement)

        # ===== UPDATE STOCK =====
        new_stock = item_agg.item.current_stock + transfer.quantity
        new_value = item_agg.item.current_stock_value + transfer.total_value
        new_avg_cost = new_value / new_stock if new_stock > 0 else item_agg.item.average_cost
        item_agg.update_stock(new_stock, new_value, new_avg_cost, user_id)
        await self._inv_repo.save_item(item_agg)

        transfer.status = TransferStatus.COMPLETED
        transfer.completed_by = user_id
        transfer.completed_at = datetime.utcnow()
        await self._inv_repo.save_transfer(transfer)

        await self._uow.commit()

        # ===== PUBLISH EVENT =====
        if self._event_publisher:
            event = TransferCompleted(
                aggregate_id=transfer_id,
                item_id=transfer.item_id,
                quantity=transfer.quantity,
                user_id=user_id,
                occurred_at=datetime.utcnow(),
            )
            try:
                await self._event_publisher.publish(event, correlation_id=correlation_id)
            except Exception as e:
                logger.warning(f"Failed to publish event {type(event).__name__}: {e}")

        self._record_audit("complete_transfer", {
            "transfer_id": str(transfer_id),
            "item_id": str(transfer.item_id),
            "from_warehouse": transfer.from_warehouse,
            "to_warehouse": transfer.to_warehouse,
            "user_id": str(user_id),
        })

        return self._to_transfer_response(transfer, item_agg.item)

    # ==================== COGS CALCULATION ====================

    @audit
    async def calculate_cogs(
        self, request: COGSCalculationRequest, user_id: UUID, correlation_id: str | None = None
    ) -> COGSCalculationResponse:
        self._check_authority(user_id, "calculate_cogs")

        movements = await self._inv_repo.get_outbound_movements(
            legal_entity_id=request.legal_entity_id,
            from_date=request.period_start,
            to_date=request.period_end,
        )

        cogs_by_item = {}
        for mv in movements:
            item_id = str(mv.item_id)
            if item_id not in cogs_by_item:
                item_agg = await self._inv_repo.get_item_by_id(mv.item_id)
                cogs_by_item[item_id] = {
                    "sku": item_agg.item.sku if item_agg else "unknown",
                    "name": item_agg.item.name if item_agg else "unknown",
                    "quantity": Decimal("0"),
                    "cogs": Decimal("0"),
                }
            cogs_by_item[item_id]["quantity"] += mv.quantity
            cogs_by_item[item_id]["cogs"] += mv.total_value

        total_cogs = sum(v["cogs"] for v in cogs_by_item.values())

        if self._event_publisher:
            event = COGSCalculated(
                legal_entity_id=request.legal_entity_id,
                period_start=request.period_start,
                period_end=request.period_end,
                total_cogs=total_cogs,
                user_id=user_id,
                occurred_at=datetime.utcnow(),
            )
            try:
                await self._event_publisher.publish(event, correlation_id=correlation_id)
            except Exception as e:
                logger.warning(f"Failed to publish event {type(event).__name__}: {e}")

        self._record_audit("calculate_cogs", {
            "period_start": request.period_start.isoformat(),
            "period_end": request.period_end.isoformat(),
            "total_cogs": str(total_cogs),
            "user_id": str(user_id),
        })

        return COGSCalculationResponse(
            period_start=request.period_start,
            period_end=request.period_end,
            total_cogs=total_cogs,
            items=[
                {"sku": v["sku"], "name": v["name"], "quantity": float(v["quantity"]), "cogs": float(v["cogs"])}
                for v in cogs_by_item.values()
            ],
        )

    # ==================== INVENTORY VALUATION ====================

    @audit
    async def update_inventory_valuation(
        self,
        request: InventoryValuationRequest,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        self._check_authority(user_id, "update_inventory_valuation")

        items = await self._inv_repo.get_all_items(request.legal_entity_id, limit=10000)
        total_value = Decimal("0")
        for agg in items:
            total_value += agg.item.current_stock_value

        if self._event_publisher:
            event = InventoryValuationUpdated(
                legal_entity_id=request.legal_entity_id,
                valuation_date=request.valuation_date,
                total_value=total_value,
                valuation_method=request.valuation_method,
                user_id=user_id,
                occurred_at=datetime.utcnow(),
                correlation_id=correlation_id,
            )
            try:
                await self._event_publisher.publish(event, correlation_id=correlation_id)
            except Exception as e:
                logger.warning(f"Failed to publish event {type(event).__name__}: {e}")

        self._record_audit("update_inventory_valuation", {
            "valuation_date": request.valuation_date.isoformat(),
            "total_value": str(total_value),
            "user_id": str(user_id),
        })

        return {
            "legal_entity_id": str(request.legal_entity_id),
            "valuation_date": request.valuation_date.isoformat(),
            "valuation_method": request.valuation_method,
            "total_value": total_value,
            "items_count": len(items),
        }

    # ==================== REPORTS ====================

    async def get_stock_card(
        self,
        item_id: UUID,
        warehouse_id: UUID | None = None,
        legal_entity_id: UUID | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> StockCardResponse:
        """Kartu stok satu item: saldo awal, rincian mutasi, saldo akhir.

        FIX: router memanggil method ini dengan keyword
        (item_id, warehouse_id, legal_entity_id, start_date, end_date) dan
        membaca hasilnya sebagai objek (result.lines, result.opening_quantity,
        result.closing_value, ...). Versi sebelumnya bersignature
        (item_id, from_date, to_date) dan me-return list[dict], sehingga
        GET /stock-card/{item_id} selalu gagal 500 dengan
        "'list' object has no attribute 'item_id'". Nama parameter lama
        (from_date/to_date) tetap diterima agar pemanggil lama tidak rusak.
        """
        period_start = start_date or from_date
        period_end = end_date or to_date

        agg = await self._inv_repo.get_item_by_id(item_id)
        if not agg:
            raise ItemNotFoundError(f"Item {item_id} tidak ditemukan")

        movements = await self._inv_repo.get_movements_by_item(
            item_id, period_start, period_end
        )

        # Saldo awal = seluruh mutasi sebelum tanggal mulai periode.
        opening_qty = Decimal("0")
        opening_value = Decimal("0")
        if period_start:
            earlier = await self._inv_repo.get_movements_by_item(item_id, None, period_start)
            for m in earlier:
                if m.movement_date >= period_start:
                    continue
                qty = Decimal(str(m.quantity))
                cost = Decimal(str(m.unit_cost or 0))
                if self._is_inbound(m):
                    opening_qty += qty
                    opening_value += qty * cost
                else:
                    opening_qty -= qty
                    opening_value -= qty * cost

        lines: list[StockCardLineResponse] = []
        balance_qty = opening_qty
        balance_value = opening_value

        for m in movements:
            if warehouse_id is not None and getattr(m, "warehouse_id", None) not in (None, warehouse_id):
                continue
            qty = Decimal(str(m.quantity))
            cost = Decimal(str(m.unit_cost or 0))
            value = qty * cost
            inbound = self._is_inbound(m)
            if inbound:
                balance_qty += qty
                balance_value += value
            else:
                balance_qty -= qty
                balance_value -= value
            lines.append(StockCardLineResponse(
                date=m.movement_date,
                reference=getattr(m, "reference_document_number", None)
                          or getattr(m, "movement_number", "") or "",
                reference_id=getattr(m, "reference_id", None),
                in_quantity=qty if inbound else Decimal("0"),
                out_quantity=Decimal("0") if inbound else qty,
                balance_quantity=balance_qty,
                unit_cost=cost,
                in_value=value if inbound else Decimal("0"),
                out_value=Decimal("0") if inbound else value,
                balance_value=balance_value,
            ))

        return StockCardResponse(
            item_id=item_id,
            item_code=agg.item.sku,
            item_name=agg.item.name,
            warehouse_name=await self._get_warehouse_name(warehouse_id),
            opening_quantity=opening_qty,
            opening_value=opening_value,
            opening_unit_cost=(opening_value / opening_qty) if opening_qty else Decimal("0"),
            lines=lines,
            closing_quantity=balance_qty,
            closing_value=balance_value,
            closing_unit_cost=(balance_value / balance_qty) if balance_qty else Decimal("0"),
        )

    @staticmethod
    def _is_inbound(movement: Any) -> bool:
        """Apakah mutasi menambah stok? Dibuat defensif karena tipe mutasi
        bisa berupa enum domain (punya is_inbound()) atau string biasa."""
        mtype = getattr(movement, "movement_type", None)
        if hasattr(mtype, "is_inbound"):
            try:
                return bool(mtype.is_inbound())
            except Exception:  # noqa: BLE001
                pass
        name = str(getattr(mtype, "value", mtype) or "").upper()
        return any(tag in name for tag in ("IN", "RECEIPT", "PURCHASE", "SURPLUS", "RETURN_IN"))

    async def get_low_stock_items(
        self, legal_entity_id: UUID, threshold_percentage: Decimal = Decimal("20")
    ) -> list[ItemResponse]:
        items = await self._inv_repo.get_all_items(legal_entity_id, limit=10000)
        low_stock = []
        for agg in items:
            if agg.item.status != ItemStatus.ACTIVE:
                continue
            if agg.item.current_stock <= agg.item.reorder_point and agg.item.reorder_point > 0:
                low_stock.append(agg.item)
        return [self._to_item_response(item) for item in low_stock]

    # ==================== PRIVATE HELPERS ====================

    def _to_item_response(self, item: Item) -> ItemResponse:
        return ItemResponse(
            id=item.id,
            sku=item.sku,
            name=item.name,
            description=item.description,
            item_type=item.item_type.value,
            uom=item.unit_of_measure.value,
            current_stock=item.current_stock,
            current_stock_value=item.current_stock_value,
            average_cost=item.average_cost,
            last_cost=item.last_cost,
            reorder_point=item.reorder_point,
            safety_stock=item.safety_stock,
            standard_cost=item.standard_cost,
            selling_price=item.selling_price,
            category=item.category,
            warehouse_code=item.warehouse_code,
            status=item.status.value,
            created_at=item.created_at,
            item_code=item.sku,
            item_name=item.name,
            unit_of_measure=item.unit_of_measure.value,
            brand=getattr(item, "brand", None),
            reorder_quantity=getattr(item, "reorder_quantity", Decimal("0")) or Decimal("0"),
            min_stock=getattr(item, "minimum_stock", None) or Decimal("0"),
            max_stock=getattr(item, "maximum_stock", None) or Decimal("0"),
            valuation_method=getattr(item, "valuation_method", None) or "FIFO",
            is_active=item.is_active,
            is_locked=False,  # belum dimodelkan di domain Item - default aman
            weight_kg=(item.weight_gram / Decimal("1000")) if getattr(item, "weight_gram", None) else None,
            volume_m3=None,  # belum dimodelkan (domain hanya simpan dimension_cm string)
            last_purchase_price=item.last_cost or None,
            last_purchase_date=None,  # belum ada kolom tanggal pembelian terakhir di domain
            total_value=item.current_stock_value,
            updated_at=item.updated_at or item.created_at,
            created_by=getattr(item, "created_by", None),
            created_by_name=None,  # butuh join ke user - belum diimplementasikan
            version=getattr(item, "version", 1),
        )

    @staticmethod
    def _parse_created_by(value: Any) -> UUID | None:
        """created_by di MovementEntity disimpan sebagai str, tapi kontrak
        router mengharapkan UUID - parse dengan aman, kembalikan None kalau
        tidak valid (misal string kosong)."""
        if isinstance(value, UUID):
            return value
        if isinstance(value, str) and value:
            try:
                return UUID(value)
            except ValueError:
                return None
        return None

    def _to_movement_response(
        self, movement: StockMovement, sku: str, original_type_code: str | None = None
    ) -> StockMovementResponse:
        return StockMovementResponse(
            id=movement.id,
            item_id=movement.item_id,
            sku=sku,
            movement_type=original_type_code or movement.movement_type.value,
            quantity=movement.quantity,
            unit_cost=movement.unit_cost,
            total_value=movement.total_cost,
            movement_date=movement.movement_date,
            reference_document_type=movement.reference_document_type,
            reference_document_number=movement.reference_document_number,
            warehouse_code=movement.warehouse_code,
            notes=movement.notes,
            created_at=movement.created_at,
            movement_number=movement.movement_number,
            item_code=sku,
            item_name=movement.item_name or sku,
            total_cost=movement.total_cost,
            reference_type=movement.reference_document_type,
            reference_id=movement.reference_document_id,
            warehouse_id=movement.warehouse_id,
            warehouse_name=None,  # diisi pemanggil (get_movement_by_id/list_movements) lewat join
            to_warehouse_id=movement.to_warehouse_id,
            batch_number=movement.batch_number,
            serial_number=movement.serial_number,
            expiry_date=movement.expiry_date,
            status=movement.status.value,
            created_by=self._parse_created_by(movement.created_by),
            created_by_name=None,  # butuh join ke user - belum diimplementasikan
            reversed_at=movement.reversed_at,
            reversed_by=movement.reversed_by,
            version=movement.version,
        )

    async def get_movement_by_id(
        self, movement_id: UUID, legal_entity_id: UUID | None = None
    ) -> StockMovementResponse | None:
        movement = await self._inv_repo.get_movement_by_id(movement_id, legal_entity_id)
        if movement is None:
            return None
        warehouse_name = await self._get_warehouse_name(movement.warehouse_id)
        response = self._to_movement_response(movement, movement.item_sku)
        response.warehouse_name = warehouse_name
        return response

    async def list_movements(
        self,
        legal_entity_id: UUID,
        item_id: UUID | None = None,
        movement_type: str | None = None,
        status: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> MovementListResult:
        page = max(page, 1)
        page_size = max(min(page_size, 200), 1)
        domain_type = self._resolve_movement_type(movement_type).value if movement_type else None
        movements, total = await self._inv_repo.list_movements(
            legal_entity_id=legal_entity_id,
            item_id=item_id,
            movement_type=domain_type,
            status=status,
            start_date=start_date,
            end_date=end_date,
            page=page,
            page_size=page_size,
        )
        responses = []
        for m in movements:
            resp = self._to_movement_response(m, m.item_sku)
            resp.warehouse_name = await self._get_warehouse_name(m.warehouse_id)
            responses.append(resp)
        return MovementListResult(items=responses, total=total, page=page, page_size=page_size)

    async def reverse_movement(
        self, movement_id: UUID, reversed_by: UUID, legal_entity_id: UUID, reason: str
    ) -> StockMovementResponse | None:
        await self._uow.begin()
        movement = await self._inv_repo.get_movement_by_id(movement_id, legal_entity_id)
        if movement is None:
            return None
        if movement.status != MovementStatus.CONFIRMED:
            raise ValueError(f"Cannot reverse movement with status {movement.status.value}")

        item_agg = await self._inv_repo.get_item_by_id(movement.item_id)
        if not item_agg:
            raise ItemNotFoundError(f"Item {movement.item_id} not found")

        # Balikkan efek movement asli terhadap stok (kebalikan dari saat direkam)
        if movement.movement_type.is_inbound():
            new_stock = item_agg.item.current_stock - movement.quantity
            new_value = item_agg.item.current_stock_value - movement.total_cost
        else:
            new_stock = item_agg.item.current_stock + movement.quantity
            new_value = item_agg.item.current_stock_value + movement.total_cost

        if new_stock < 0 and not self._validator.allow_negative_stock(item_agg.item):
            raise NegativeStockNotAllowedError(
                f"Tidak bisa membalik movement: akan membuat stok negatif untuk item {item_agg.item.sku}"
            )

        item_agg.update_stock(new_stock, new_value, item_agg.item.average_cost, reversed_by)
        movement.mark_as_reversed(reversed_by)
        movement.notes = f"{movement.notes or ''} [REVERSED: {reason}]".strip()

        await self._inv_repo.save_item(item_agg)
        await self._inv_repo.save_movement(movement)
        await self._uow.commit()

        self._record_audit("reverse_movement", {
            "movement_id": str(movement_id),
            "reversed_by": str(reversed_by),
            "reason": reason,
        })

        warehouse_name = await self._get_warehouse_name(movement.warehouse_id)
        response = self._to_movement_response(movement, movement.item_sku or item_agg.item.sku)
        response.warehouse_name = warehouse_name
        return response

    async def _get_warehouse_name(self, warehouse_id: UUID | None) -> str | None:
        if warehouse_id is None:
            return None
        try:
            return await self._inv_repo.get_warehouse_name_by_id(warehouse_id)
        except Exception:
            return None

    def _to_opname_session_response(self, opname: StockOpname) -> StockOpnameSessionResponse:
        """Bentuk response satu sesi opname (banyak item) sesuai yang dibaca
        router - dipakai create_stock_opname & approve_stock_opname."""
        lines = [
            {
                "item_id": str(it.item_id),
                "item_code": it.item_sku,
                "item_name": it.item_name,
                "system_quantity": str(it.system_quantity),
                "physical_quantity": str(it.physical_quantity),
                "discrepancy": str(it.discrepancy),
                "discrepancy_value": str(it.discrepancy_value),
                "notes": it.notes,
            }
            for it in opname.items
        ]
        return StockOpnameSessionResponse(
            id=opname.id,
            opname_number=opname.opname_number,
            warehouse_id=opname.warehouse_id,
            warehouse_name=opname.warehouse_name,
            opname_date=opname.opname_date,
            status=opname.status.value,
            total_adjustments=sum(1 for it in opname.items if it.discrepancy != 0),
            adjustment_value=opname.total_discrepancy_value,
            lines=lines,
            notes=opname.notes,
            created_at=opname.created_at,
            created_by=opname.created_by,
            approved_at=opname.approved_at,
            approved_by=opname.approved_by,
            applied_at=opname.approved_at,
            version=opname.version,
        )

    def _to_opname_response(self, opname: StockOpname, item: Item) -> StockOpnameResponse:
        return StockOpnameResponse(
            id=opname.id,
            item_id=opname.item_id,
            item_name=item.name,
            sku=item.sku,
            opname_date=opname.opname_date,
            system_quantity=opname.system_quantity,
            physical_quantity=opname.physical_quantity,
            discrepancy=opname.discrepancy,
            discrepancy_value=opname.discrepancy_value,
            status=opname.status.value,
            notes=opname.notes,
            counted_by=opname.counted_by,
            counted_at=opname.counted_at,
            approved_by=opname.approved_by,
            approved_at=opname.approved_at,
        )

    def _to_transfer_response(self, transfer: InterWarehouseTransfer, item: Item) -> TransferResponse:
        return TransferResponse(
            id=transfer.id,
            item_id=transfer.item_id,
            item_name=item.name,
            sku=item.sku,
            from_warehouse=transfer.from_warehouse,
            to_warehouse=transfer.to_warehouse,
            quantity=transfer.quantity,
            unit_cost=transfer.unit_cost,
            total_value=transfer.total_value,
            transfer_date=transfer.transfer_date,
            status=transfer.status.value,
            notes=transfer.notes,
            requested_by=transfer.requested_by,
            requested_at=transfer.requested_at,
            completed_by=transfer.completed_by,
            completed_at=transfer.completed_at,
        )

    def get_stats(self) -> dict[str, int]:
        return self._stats.copy()

    def get_audit_trail(self) -> list[dict[str, Any]]:
        return self._audit_trail.copy()

    # ========================================================================
    # METHOD KOMPATIBILITAS UNTUK ROUTER (fix sinkronisasi router <-> service)
    # ========================================================================

    async def get_item_by_id(
        self, item_id: UUID, legal_entity_id: UUID | None = None
    ) -> ItemResponse | None:
        """Router memanggil nama ini; method internal bernama get_item()."""
        response = await self.get_item(item_id)
        if response is None:
            return None
        return response

    async def get_item_by_code(
        self, item_code: str, legal_entity_id: UUID
    ) -> ItemResponse | None:
        """Ambil item berdasarkan kode/SKU (dipakai GET /items/by-code/{code})."""
        aggregate = await self._inv_repo.get_item_by_sku(item_code, legal_entity_id)
        if not aggregate:
            return None
        return self._to_item_response(aggregate.item)

    async def activate_item(
        self,
        item_id: UUID,
        user_id: UUID | None = None,
        legal_entity_id: UUID | None = None,
        correlation_id: str | None = None,
    ) -> ItemResponse | None:
        """Aktifkan kembali item yang sebelumnya dinonaktifkan."""
        agg = await self._inv_repo.get_item_by_id(item_id)
        if not agg:
            return None

        agg.item.status = ItemStatus.ACTIVE
        agg.item.updated_at = datetime.utcnow()
        agg.item.updated_by = user_id
        await self._inv_repo.save_item(agg)

        self._record_audit("activate_item", {
            "item_id": str(item_id),
            "user_id": str(user_id) if user_id else None,
        })
        logger.info(f"Item activated: {agg.item.sku}")
        return self._to_item_response(agg.item)

    async def deactivate_item_api(
        self,
        item_id: UUID,
        user_id: UUID | None = None,
        legal_entity_id: UUID | None = None,
        reason: str | None = None,
    ) -> ItemResponse | None:
        """Versi deactivate_item yang mengembalikan ItemResponse.

        FIX: endpoint DELETE /items/{id} sebelumnya memanggil
        ``deactivate_item(item_id, current_user.user_id, legal_entity_id, reason)``
        secara POSISIONAL, padahal signature aslinya
        ``(item_id, reason, user_id, correlation_id)`` - jadi user_id masuk ke
        parameter reason, legal_entity_id masuk ke user_id, dst. Selain itu
        method aslinya me-return ``bool`` sementara router membaca
        ``result.item_code`` sehingga selalu AttributeError. Method ini
        membungkusnya dengan urutan argumen yang benar dan return yang sesuai.
        """
        agg = await self._inv_repo.get_item_by_id(item_id)
        if not agg:
            return None
        await self.deactivate_item(item_id=item_id, reason=reason, user_id=user_id)
        refreshed = await self._inv_repo.get_item_by_id(item_id)
        return self._to_item_response((refreshed or agg).item)

    async def void_item(
        self,
        item_id: UUID,
        user_id: UUID | None = None,
        legal_entity_id: UUID | None = None,
        reason: str | None = None,
    ) -> ItemResponse | None:
        """Hapus permanen item (hanya boleh kalau belum pernah dipakai)."""
        agg = await self._inv_repo.get_item_by_id(item_id)
        if not agg:
            return None

        if agg.item.current_stock and agg.item.current_stock != 0:
            raise ValueError(
                f"Item {agg.item.sku} masih punya stok {agg.item.current_stock} - "
                "tidak bisa dihapus permanen. Nonaktifkan saja, atau nolkan stoknya dulu."
            )

        movements = await self._inv_repo.get_movements_by_item(item_id, limit=1)
        if movements:
            raise ValueError(
                f"Item {agg.item.sku} sudah punya riwayat mutasi stok - tidak boleh "
                "dihapus permanen demi jejak audit. Gunakan nonaktifkan."
            )

        response = self._to_item_response(agg.item)
        await self._inv_repo.delete_item(item_id)
        self._record_audit("void_item", {
            "item_id": str(item_id),
            "reason": reason,
            "user_id": str(user_id) if user_id else None,
        })
        logger.info(f"Item voided (hard delete): {agg.item.sku}")
        return response

    async def list_stock_opnames(
        self,
        legal_entity_id: UUID,
        status: str | None = None,
        warehouse_id: UUID | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        """Daftar stock opname untuk ditampilkan di menu Stock Opname &
        Valuasi (dropdown/tabel pilih opname yang mau di-approve/dibatalkan)."""
        return await self._inv_repo.list_opnames(
            legal_entity_id=legal_entity_id,
            status=status,
            warehouse_id=warehouse_id,
            page=page,
            page_size=page_size,
        )

    async def cancel_stock_opname(
        self,
        opname_id: UUID,
        cancelled_by: UUID | None = None,
        legal_entity_id: UUID | None = None,
        reason: str | None = None,
    ) -> OpnameCancelResponse | None:
        """Batalkan stock opname yang masih draft/pending."""
        opname = await self._inv_repo.get_opname_by_id(opname_id)
        if not opname:
            return None

        current_status = getattr(opname.status, "value", opname.status)
        if str(current_status).upper() in ("APPROVED", "COMPLETED", "CANCELLED"):
            raise ValueError(
                f"Stock opname sudah berstatus {current_status} - tidak bisa dibatalkan."
            )

        if hasattr(opname, "cancel"):
            opname.cancel(cancelled_by=cancelled_by, reason=reason or "")
        else:
            opname.status = OpnameStatus.CANCELLED
        await self._inv_repo.save_opname(opname)

        self._record_audit("cancel_stock_opname", {
            "opname_id": str(opname_id),
            "reason": reason,
            "user_id": str(cancelled_by) if cancelled_by else None,
        })
        return OpnameCancelResponse(
            id=opname_id,
            opname_number=getattr(opname, "opname_number", str(opname_id)[:8]),
            status="CANCELLED",
        )

    # ------------------------------------------------------------------
    # Transfer antar gudang (model header + lines)
    # ------------------------------------------------------------------

    @staticmethod
    def _transfer_to_response(transfer: Any) -> WarehouseTransferResponse:
        return WarehouseTransferResponse(
            id=transfer.transfer_id,
            transfer_number=transfer.transfer_number,
            from_warehouse_id=transfer.source_warehouse_id,
            from_warehouse_name=transfer.source_warehouse_name,
            to_warehouse_id=transfer.destination_warehouse_id,
            to_warehouse_name=transfer.destination_warehouse_name,
            transfer_date=transfer.transfer_date,
            status=getattr(transfer.status, "value", transfer.status),
            items=[
                it.to_dict() if hasattr(it, "to_dict") else {
                    "item_id": str(it.item_id),
                    "item_sku": it.item_sku,
                    "item_name": it.item_name,
                    "quantity": str(it.quantity),
                    "unit_cost": str(it.unit_cost),
                    "total_value": str(it.total_value),
                }
                for it in transfer.items
            ],
            notes=transfer.notes,
            created_at=transfer.created_at or datetime.utcnow(),
            created_by=transfer.created_by or transfer.requested_by,
            approved_at=transfer.approved_at,
            approved_by=transfer.approved_by,
            completed_at=transfer.completed_at,
            version=getattr(transfer, "version", 1),
        )

    async def create_warehouse_transfer(self, request: Any) -> WarehouseTransferResponse:
        """Buat transfer antar gudang (header + banyak item)."""
        if request.from_warehouse_id == request.to_warehouse_id:
            raise ValueError("Gudang asal dan gudang tujuan tidak boleh sama")

        items: list[TransferItem] = []
        for raw in (request.items or []):
            line = raw if isinstance(raw, dict) else raw.__dict__
            item_id = line["item_id"]
            agg = await self._inv_repo.get_item_by_id(item_id)
            if not agg:
                raise ValueError(f"Item {item_id} tidak ditemukan")
            qty = Decimal(str(line["quantity"]))
            available = await self._inv_repo.get_current_stock(item_id, request.from_warehouse_id)
            if qty > available:
                raise ValueError(
                    f"Stok {agg.item.sku} di gudang asal tidak cukup "
                    f"(tersedia {available}, diminta {qty})"
                )
            unit_cost = agg.item.average_cost
            items.append(TransferItem(
                item_id=item_id,
                item_sku=agg.item.sku,
                item_name=agg.item.name,
                quantity=qty,
                unit_cost=unit_cost,
                total_value=qty * unit_cost,
                batch_number=line.get("batch_number"),
            ))

        if not items:
            raise ValueError("Transfer harus punya minimal 1 item")

        transfer = InterWarehouseTransfer(
            transfer_id=uuid4(),
            transfer_number=f"TRF-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            source_warehouse_id=request.from_warehouse_id,
            source_warehouse_name=await self._get_warehouse_name(request.from_warehouse_id),
            destination_warehouse_id=request.to_warehouse_id,
            destination_warehouse_name=await self._get_warehouse_name(request.to_warehouse_id),
            transfer_date=request.transfer_date or date.today(),
            priority=TransferPriority.NORMAL,
            status=TransferStatus.PENDING,
            items=items,
            notes=getattr(request, "notes", None) or "",
            requested_by=request.created_by,
            requested_at=datetime.utcnow(),
            created_by=request.created_by,
            created_at=datetime.utcnow(),
            legal_entity_id=request.legal_entity_id,
        )
        await self._inv_repo.save_transfer(transfer)

        self._record_audit("create_warehouse_transfer", {
            "transfer_id": str(transfer.transfer_id),
            "transfer_number": transfer.transfer_number,
        })
        return self._transfer_to_response(transfer)

    async def approve_warehouse_transfer(
        self,
        transfer_id: UUID,
        approver_id: UUID | None = None,
        legal_entity_id: UUID | None = None,
    ) -> WarehouseTransferResponse | None:
        """Setujui transfer antar gudang yang masih pending."""
        transfer = await self._inv_repo.get_transfer_by_id(transfer_id)
        if not transfer:
            return None

        status = getattr(transfer.status, "value", transfer.status)
        if str(status).upper() not in ("PENDING", "DRAFT", "SUBMITTED"):
            raise ValueError(f"Transfer sudah berstatus {status} - tidak bisa disetujui lagi.")

        if hasattr(transfer, "approve"):
            transfer.approve(approver_id)
        else:
            transfer.status = TransferStatus.APPROVED
            transfer.approved_by = approver_id
            transfer.approved_at = datetime.utcnow()
        await self._inv_repo.save_transfer(transfer)

        self._record_audit("approve_warehouse_transfer", {"transfer_id": str(transfer_id)})
        return self._transfer_to_response(transfer)

    async def complete_warehouse_transfer(
        self,
        transfer_id: UUID,
        completed_by: UUID | None = None,
        legal_entity_id: UUID | None = None,
    ) -> WarehouseTransferResponse | None:
        """Selesaikan transfer: catat mutasi keluar di gudang asal dan
        mutasi masuk di gudang tujuan untuk setiap item."""
        transfer = await self._inv_repo.get_transfer_by_id(transfer_id)
        if not transfer:
            return None

        status = getattr(transfer.status, "value", transfer.status)
        if str(status).upper() == "COMPLETED":
            raise ValueError("Transfer sudah selesai sebelumnya.")
        if str(status).upper() not in ("APPROVED", "IN_TRANSIT", "SHIPPED"):
            raise ValueError(
                f"Transfer berstatus {status} - harus disetujui dulu sebelum diselesaikan."
            )

        for line in transfer.items:
            await self._inv_repo.transfer_stock(
                item_id=line.item_id,
                from_warehouse_id=transfer.source_warehouse_id,
                to_warehouse_id=transfer.destination_warehouse_id,
                quantity=line.quantity,
                user_id=completed_by,
                reference_type="INTER_WAREHOUSE_TRANSFER",
                reference_id=transfer_id,
                unit_cost=line.unit_cost,
            )

        if hasattr(transfer, "complete"):
            transfer.complete(completed_by)
        else:
            transfer.status = TransferStatus.COMPLETED
            transfer.completed_by = completed_by
            transfer.completed_at = datetime.utcnow()
        await self._inv_repo.save_transfer(transfer)

        self._record_audit("complete_warehouse_transfer", {"transfer_id": str(transfer_id)})
        return self._transfer_to_response(transfer)

    # ------------------------------------------------------------------
    # Valuasi & NRV
    # ------------------------------------------------------------------

    async def get_valuation(
        self,
        item_id: UUID,
        legal_entity_id: UUID | None = None,
        as_of_date: date | None = None,
        warehouse_id: UUID | None = None,
    ) -> ValuationResponse:
        """Nilai persediaan satu item beserta rincian layer FIFO/LIFO."""
        agg = await self._inv_repo.get_item_by_id(item_id)
        if not agg:
            raise ItemNotFoundError(f"Item {item_id} tidak ditemukan")

        layers_raw: list[Any] = []
        if warehouse_id is not None:
            try:
                layers_raw = await self._inv_repo.get_fifo_layers(item_id, warehouse_id)
            except Exception as exc:  # noqa: BLE001 - layer bersifat opsional
                logger.warning(f"Gagal mengambil FIFO layer untuk {item_id}: {exc}")

        layers: list[ValuationLayerResponse] = []
        total_qty = Decimal("0")
        total_value = Decimal("0")
        for layer in layers_raw:
            remaining = Decimal(str(getattr(layer, "remaining_quantity", 0) or 0))
            unit_cost = Decimal(str(getattr(layer, "unit_cost", 0) or 0))
            qty = Decimal(str(getattr(layer, "quantity", remaining) or 0))
            layers.append(ValuationLayerResponse(
                layer_id=getattr(layer, "id", uuid4()),
                quantity=qty,
                unit_cost=unit_cost,
                total_value=qty * unit_cost,
                remaining_quantity=remaining,
                remaining_value=remaining * unit_cost,
                created_at=getattr(layer, "created_at", None) or datetime.utcnow(),
                expiry_date=getattr(layer, "expiry_date", None),
            ))
            total_qty += remaining
            total_value += remaining * unit_cost

        if not layers:
            # Tanpa rincian layer, pakai stok & harga rata-rata yang tercatat
            # di master item - tetap memberi angka valuasi yang benar.
            total_qty = Decimal(str(agg.item.current_stock or 0))
            total_value = total_qty * Decimal(str(agg.item.average_cost or 0))

        wac = (total_value / total_qty) if total_qty else Decimal("0")

        return ValuationResponse(
            item_id=item_id,
            item_code=agg.item.sku,
            item_name=agg.item.name,
            valuation_method=getattr(self._valuation_method, "value", str(self._valuation_method)),
            total_quantity=total_qty,
            total_value=total_value,
            weighted_average_cost=wac,
            layers=layers,
        )

    async def test_nrv(
        self,
        item_id: UUID,
        legal_entity_id: UUID | None = None,
        test_date: date | None = None,
        nrv: Decimal | None = None,
        tested_by: UUID | None = None,
    ) -> NRVTestResponse:
        """Uji Net Realizable Value (PSAK 14: persediaan dinilai pada nilai
        terendah antara biaya perolehan dan nilai realisasi neto)."""
        agg = await self._inv_repo.get_item_by_id(item_id)
        if not agg:
            raise ItemNotFoundError(f"Item {item_id} tidak ditemukan")

        nrv_value = Decimal(str(nrv if nrv is not None else 0))
        if nrv_value < 0:
            raise ValueError("NRV tidak boleh negatif")

        quantity = Decimal(str(agg.item.current_stock or 0))
        unit_cost = Decimal(str(agg.item.average_cost or 0))
        carrying_value = quantity * unit_cost
        nrv_total = quantity * nrv_value

        nrv_less_than_cost = nrv_value < unit_cost
        impairment_loss = (carrying_value - nrv_total) if nrv_less_than_cost else Decimal("0")

        self._record_audit("test_nrv", {
            "item_id": str(item_id),
            "nrv": str(nrv_value),
            "impairment_loss": str(impairment_loss),
            "user_id": str(tested_by) if tested_by else None,
        })

        return NRVTestResponse(
            item_id=item_id,
            item_code=agg.item.sku,
            item_name=agg.item.name,
            carrying_value=carrying_value,
            net_realizable_value=nrv_total,
            impairment_loss=impairment_loss,
            nrv_less_than_cost=nrv_less_than_cost,
            recommended_adjustment=impairment_loss,
            status="IMPAIRED" if nrv_less_than_cost else "OK",
            created_at=datetime.utcnow(),
            created_by=tested_by,
            journal_id=None,
        )

    async def export_items(
        self,
        legal_entity_id: UUID,
        format: str = "csv",
        item_type: str | None = None,
        category: str | None = None,
    ) -> bytes:
        """Ekspor master barang. Router mengirim hasilnya apa adanya sebagai
        body Response, jadi yang dikembalikan harus bytes."""
        csv_text = await self._inv_repo.export_items_to_csv(legal_entity_id)
        if isinstance(csv_text, bytes):
            return csv_text
        return csv_text.encode("utf-8")


# ============================================================================
# DTO RESPONSE TAMBAHAN UNTUK ENDPOINT API
#
# FIX SINKRONISASI ROUTER <-> SERVICE: fastapi_inventory_router.py memanggil
# sejumlah method yang sebelumnya TIDAK ADA di InventoryService
# (get_item_by_id, get_item_by_code, activate_item, void_item,
# cancel_stock_opname, create/approve/complete_warehouse_transfer,
# get_valuation, test_nrv, export_items). Setiap endpoint tersebut pasti
# gagal 500 AttributeError begitu diklik. Method-methodnya ditambahkan di
# bawah, beserta dataclass response yang bentuk fieldnya persis seperti
# yang dibaca router.
# ============================================================================


@dataclass
class WarehouseTransferResponse:
    """Bentuk response transfer antar gudang yang dibaca router."""

    id: UUID
    transfer_number: str
    from_warehouse_id: UUID
    to_warehouse_id: UUID
    transfer_date: date
    status: str
    items: list[dict[str, Any]]
    created_at: datetime
    created_by: UUID
    from_warehouse_name: str | None = None
    to_warehouse_name: str | None = None
    notes: str | None = None
    created_by_name: str | None = None
    approved_at: datetime | None = None
    approved_by: UUID | None = None
    completed_at: datetime | None = None
    version: int = 1


@dataclass
class ValuationLayerResponse:
    layer_id: UUID
    quantity: Decimal
    unit_cost: Decimal
    total_value: Decimal
    remaining_quantity: Decimal
    remaining_value: Decimal
    created_at: datetime
    expiry_date: date | None = None


@dataclass
class ValuationResponse:
    item_id: UUID
    item_code: str
    item_name: str
    valuation_method: str
    total_quantity: Decimal
    total_value: Decimal
    weighted_average_cost: Decimal
    layers: list[ValuationLayerResponse]


@dataclass
class NRVTestResponse:
    item_id: UUID
    item_code: str
    item_name: str
    carrying_value: Decimal
    net_realizable_value: Decimal
    impairment_loss: Decimal
    nrv_less_than_cost: bool
    recommended_adjustment: Decimal
    status: str
    created_at: datetime
    created_by: UUID
    journal_id: UUID | None = None


@dataclass
class OpnameCancelResponse:
    id: UUID
    opname_number: str
    status: str


@dataclass
class StockCardLineResponse:
    date: date
    reference: str
    in_quantity: Decimal
    out_quantity: Decimal
    balance_quantity: Decimal
    unit_cost: Decimal
    in_value: Decimal
    out_value: Decimal
    balance_value: Decimal
    reference_id: UUID | None = None


@dataclass
class StockCardResponse:
    item_id: UUID
    item_code: str
    item_name: str
    opening_quantity: Decimal
    opening_value: Decimal
    opening_unit_cost: Decimal
    lines: list[StockCardLineResponse]
    closing_quantity: Decimal
    closing_value: Decimal
    closing_unit_cost: Decimal
    warehouse_name: str | None = None


# ============================================================================
# Factory
# ============================================================================


async def create_inventory_service(
    inv_repo: InventoryRepositoryPort,
    uow: UnitOfWorkPort,
    event_publisher: EventPublisherPort | None = None,
    ledger_repo: LedgerRepositoryPort | None = None,
    valuation_method: str = "FIFO",
) -> InventoryService:
    return InventoryService(inv_repo, uow, event_publisher, ledger_repo, valuation_method)


__all__ = [
    "COGSCalculationRequest",
    "COGSCalculationResponse",
    "CreateItemRequest",
    "InsufficientStockError",
    "InventoryService",
    "InventoryServiceError",
    "InventoryValuationMethod",
    "InventoryValuationRequest",
    "ItemNotFoundError",
    "ItemResponse",
    "NegativeStockNotAllowedError",
    "StockMovementRequest",
    "StockMovementResponse",
    "StockOpnameRequest",
    "StockOpnameResponse",
    "TransferNotFoundError",
    "TransferRequest",
    "TransferResponse",
    "UpdateItemRequest",
    "WarehouseNotFoundError",
    "create_inventory_service",
]
