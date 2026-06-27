#!/usr/bin/env python3
"""
Module: aggregate_root.py
Layer: 6 - Domain / Inventory
Responsibility: Inventory aggregate root.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from domain.inventory.domain_events import (
    ItemCreated,
    ItemDeactivated,
    ItemUpdated,
    StockAdjusted,
    StockMovementCreated,
)
from domain.inventory.item_entity import Item, ItemStatus, ItemType, UnitOfMeasure
from domain.inventory.movement_entity import MovementType, StockMovement
from domain.inventory.stock_adjustment_entity import (
    AdjustmentReason,
    AdjustmentStatus,
    AdjustmentType,
    StockAdjustmentEntity,
)
from domain.inventory.valuation_method import FIFOValuation

StockMovementType = MovementType

logger = logging.getLogger(__name__)


class InventoryAggregate:
    """Inventory Aggregate Root - mengelola item persediaan dan stok."""

    def __init__(
        self,
        id: UUID | None = None,
        legal_entity_id: UUID | None = None,
        version: int = 0,
    ):
        self.id = id or uuid4()
        self.legal_entity_id = legal_entity_id
        self._version = version
        self._item: Item | None = None
        self._events: list[Any] = []
        self._fifo_layers: list[dict] = []
        self._fifo = FIFOValuation()
        self._snapshots: list[dict] = []
        self._audit_trail: list[dict] = []
        self._is_locked: bool = False
        self._locked_by: UUID | None = None
        self._locked_at: datetime | None = None
        self._is_active: bool = True
        self._deactivated_at: datetime | None = None
        self._deactivated_by: UUID | None = None

    # ==================== PROPERTIES ====================

    @property
    def item(self) -> Item:
        if self._item is None:
            raise ValueError("Item not set")
        return self._item

    @property
    def version(self) -> int:
        return self._version

    @version.setter
    def version(self, value: int):
        self._version = value

    @property
    def is_locked(self) -> bool:
        return self._is_locked

    @property
    def is_active(self) -> bool:
        return self._is_active

    @property
    def current_stock(self) -> Decimal:
        return self._item.current_stock if self._item else Decimal(0)

    @property
    def current_stock_value(self) -> Decimal:
        return self._item.current_stock_value if self._item else Decimal(0)

    @property
    def average_cost(self) -> Decimal:
        return self._item.average_cost if self._item else Decimal(0)

    # ==================== EVENT METHODS ====================

    def _add_event(self, event: Any) -> None:
        """Add domain event."""
        self._events.append(event)
        self._record_audit_trail("event_added", {"event_type": type(event).__name__})

    def clear_events(self) -> None:
        """Clear all domain events."""
        self._events.clear()
        self._record_audit_trail("events_cleared", {})

    def get_events(self) -> list[Any]:
        """Get all domain events."""
        return self._events.copy()

    def pop_events(self) -> list[Any]:
        """Pop all domain events."""
        events = self._events.copy()
        self._events.clear()
        return events

    def pull_events(self) -> list[Any]:
        """Pull all domain events (clear and return)."""
        events = self._events.copy()
        self._events.clear()
        return events

    def register_event(self, event: Any) -> None:
        """Register a domain event."""
        self._add_event(event)

    # ==================== AUDIT TRAIL ====================

    def _record_audit_trail(self, action: str, details: dict) -> None:
        """Record action in audit trail."""
        self._audit_trail.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "action": action,
                "details": details,
                "version": self._version,
            }
        )

    def audit_trail(self) -> list[dict]:
        """Get full audit trail."""
        return self._audit_trail.copy()

    # ==================== SNAPSHOT ====================

    def snapshot(self) -> dict:
        """Create a snapshot of current state."""
        snapshot_data = {
            "aggregate_id": str(self.id),
            "aggregate_type": "InventoryAggregate",
            "version": self._version,
            "timestamp": datetime.now(UTC).isoformat(),
            "state": {
                "item": self._item.to_dict() if self._item else None,
                "fifo_layers": self._fifo_layers,
                "is_locked": self._is_locked,
                "is_active": self._is_active,
                "locked_by": str(self._locked_by) if self._locked_by else None,
                "locked_at": self._locked_at.isoformat() if self._locked_at else None,
                "deactivated_at": self._deactivated_at.isoformat()
                if self._deactivated_at
                else None,
                "deactivated_by": str(self._deactivated_by) if self._deactivated_by else None,
            },
            "hash": self._compute_hash(),
        }
        self._snapshots.append(snapshot_data)
        self._record_audit_trail("snapshot_created", {"version": self._version})
        return snapshot_data

    def restore_from_snapshot(self, snapshot: dict) -> None:
        """Restore state from snapshot."""
        if snapshot.get("aggregate_id") != str(self.id):
            raise ValueError("Snapshot belongs to different aggregate")
        state = snapshot.get("state", {})
        if state.get("item"):
            self._item = Item.from_dict(state["item"])
        self._fifo_layers = state.get("fifo_layers", [])
        self._is_locked = state.get("is_locked", False)
        self._is_active = state.get("is_active", True)
        self._version = snapshot.get("version", 0)
        self._record_audit_trail(
            "restored_from_snapshot", {"snapshot_version": snapshot.get("version")}
        )

    def _compute_hash(self) -> str:
        """Compute hash of current state for integrity."""
        state_str = json.dumps(
            {
                "id": str(self.id),
                "version": self._version,
                "current_stock": str(self.current_stock),
                "current_stock_value": str(self.current_stock_value),
            },
            sort_keys=True,
        )
        return hashlib.sha256(state_str.encode()).hexdigest()

    # ==================== LOCK / UNLOCK ====================

    def lock(self, user_id: UUID, reason: str | None = None) -> None:
        """Lock the aggregate to prevent modifications."""
        if self._is_locked:
            raise ValueError(f"Aggregate is already locked by {self._locked_by}")
        self._is_locked = True
        self._locked_by = user_id
        self._locked_at = datetime.now(UTC)
        self._record_audit_trail("locked", {"user_id": str(user_id), "reason": reason})

    def unlock(self, user_id: UUID) -> None:
        """Unlock the aggregate."""
        if not self._is_locked:
            raise ValueError("Aggregate is not locked")
        if self._locked_by != user_id:
            raise ValueError(f"Aggregate locked by {self._locked_by}, cannot unlock by {user_id}")
        self._is_locked = False
        self._locked_by = None
        self._locked_at = None
        self._record_audit_trail("unlocked", {"user_id": str(user_id)})

    # ==================== ACTIVATE / DEACTIVATE ====================

    def activate(self, user_id: UUID) -> None:
        """Activate the aggregate."""
        if self._is_active:
            raise ValueError("Aggregate is already active")
        self._is_active = True
        self._deactivated_at = None
        self._deactivated_by = None
        self._record_audit_trail("activated", {"user_id": str(user_id)})

    def deactivate(self, user_id: UUID, reason: str | None = None) -> None:
        """Deactivate the aggregate."""
        if not self._is_active:
            raise ValueError("Aggregate is already inactive")
        if self._item and self._item.current_stock > 0:
            raise ValueError("Cannot deactivate item with current stock")
        self._is_active = False
        self._deactivated_at = datetime.now(UTC)
        self._deactivated_by = user_id
        self._record_audit_trail("deactivated", {"user_id": str(user_id), "reason": reason})

    # ==================== VALIDATE ====================

    def validate(self) -> list[str]:
        """Validate aggregate invariants."""
        errors = []
        if self._item is None:
            errors.append("Item not set")
            return errors

        if self._item.current_stock < 0:
            errors.append(f"Current stock cannot be negative: {self._item.current_stock}")
        if self._item.current_stock_value < 0:
            errors.append(
                f"Current stock value cannot be negative: {self._item.current_stock_value}"
            )
        if self._item.average_cost < 0:
            errors.append(f"Average cost cannot be negative: {self._item.average_cost}")

        # Validate stock value consistency
        expected_value = self._item.current_stock * self._item.average_cost
        if abs(expected_value - self._item.current_stock_value) > Decimal("0.01"):
            errors.append(
                f"Stock value mismatch: current={self._item.current_stock_value}, "
                f"expected={expected_value}"
            )

        return errors

    # ==================== VERSION ====================

    def version(self) -> int:
        """Get current version."""
        return self._version

    def increment_version(self) -> None:
        """Increment version."""
        self._version += 1
        self._record_audit_trail("version_incremented", {"new_version": self._version})

    # ==================== TOUCH ====================

    def touch(self, user_id: UUID) -> None:
        """Update timestamp without changing data."""
        self._record_audit_trail("touched", {"user_id": str(user_id)})

    # ==================== CLONE ====================

    def clone(self) -> InventoryAggregate:
        """Create a deep copy of the aggregate."""
        new_agg = InventoryAggregate(
            id=uuid4(),
            legal_entity_id=self.legal_entity_id,
            version=1,
        )
        if self._item:
            new_agg._item = self._item.clone()
        new_agg._fifo_layers = [layer.copy() for layer in self._fifo_layers]
        new_agg._is_active = self._is_active
        new_agg._record_audit_trail("cloned", {"source_id": str(self.id)})
        return new_agg

    # ==================== FACTORY METHODS ====================

    @classmethod
    def create(cls, item: Item, user_id: UUID) -> InventoryAggregate:
        """Factory method to create new inventory aggregate."""
        if item.current_stock < 0:
            raise ValueError("Initial stock cannot be negative")
        if item.standard_cost < 0:
            raise ValueError("Standard cost cannot be negative")

        instance = cls(id=item.id, legal_entity_id=item.legal_entity_id, version=1)
        instance._item = item
        instance._is_active = True

        if item.current_stock > 0:
            instance._fifo_layers.append(
                {
                    "quantity": item.current_stock,
                    "unit_cost": item.standard_cost,
                    "remaining_quantity": item.current_stock,
                    "purchase_date": datetime.now(UTC),
                }
            )

        instance._add_event(
            ItemCreated(
                aggregate_id=instance.id,
                aggregate_version=1,
                item_id=item.id,
                sku=item.sku,
                name=item.name,
                item_type=item.item_type.value,
                unit_cost=item.standard_cost,
                created_by=str(user_id),
                legal_entity_id=item.legal_entity_id,
                user_id=str(user_id),
                occurred_at=datetime.now(UTC),
            )
        )
        instance._record_audit_trail("created", {"user_id": str(user_id), "sku": item.sku})
        return instance

    @classmethod
    def reconstruct(cls, events: list[Any]) -> InventoryAggregate:
        """Reconstruct aggregate from event history."""
        if not events:
            raise ValueError("No events provided")

        first = events[0]
        agg_id = getattr(first, "aggregate_id", uuid4())
        legal_entity_id = getattr(first, "legal_entity_id", uuid4())

        instance = cls(id=agg_id, legal_entity_id=legal_entity_id, version=len(events))

        # Create placeholder item
        dummy_item = Item(
            id=agg_id,
            legal_entity_id=legal_entity_id,
            sku="RECONSTRUCTED",
            name="Reconstructed",
            description=None,
            item_type=ItemType.FINISHED_GOODS,
            unit_of_measure=UnitOfMeasure.PCS,
            current_stock=Decimal(0),
            current_stock_value=Decimal(0),
            average_cost=Decimal(0),
            last_cost=Decimal(0),
            reorder_point=Decimal(0),
            safety_stock=Decimal(0),
            maximum_stock=None,
            minimum_stock=None,
            status=ItemStatus.ACTIVE,
            standard_cost=Decimal(0),
            selling_price=Decimal(0),
            category=None,
            warehouse_code=None,
            created_by=uuid4(),
            created_at=datetime.now(UTC),
            updated_at=None,
            updated_by=None,
            deactivated_at=None,
            deactivated_by=None,
            version=0,
        )
        instance._item = dummy_item

        # Replay events
        for event in events:
            if isinstance(event, ItemCreated):
                instance._item = Item(
                    id=event.item_id,
                    legal_entity_id=instance.legal_entity_id,
                    sku=event.event_data.get("sku", ""),
                    name=event.event_data.get("name", ""),
                    description=None,
                    item_type=ItemType(event.event_data.get("item_type", "finished_goods")),
                    unit_of_measure=UnitOfMeasure.PCS,
                    current_stock=Decimal(event.event_data.get("initial_stock", "0")),
                    current_stock_value=Decimal(event.event_data.get("initial_value", "0")),
                    average_cost=Decimal(event.event_data.get("unit_cost", "0")),
                    last_cost=Decimal(event.event_data.get("unit_cost", "0")),
                    reorder_point=Decimal(0),
                    safety_stock=Decimal(0),
                    maximum_stock=None,
                    minimum_stock=None,
                    status=ItemStatus.ACTIVE,
                    standard_cost=Decimal(event.event_data.get("unit_cost", "0")),
                    selling_price=Decimal(0),
                    category=None,
                    warehouse_code=None,
                    created_by=uuid4(),
                    created_at=datetime.now(UTC),
                    updated_at=None,
                    updated_by=None,
                    deactivated_at=None,
                    deactivated_by=None,
                    version=0,
                )
            elif isinstance(event, StockMovementCreated):
                if event.quantity > 0:
                    instance._item.current_stock += event.quantity
                    instance._item.current_stock_value += event.total_value
                else:
                    instance._item.current_stock += event.quantity
                    instance._item.current_stock_value -= abs(event.total_value)
            elif isinstance(event, ItemUpdated):
                changes = event.event_data.get("changes", {})
                if "name" in changes:
                    instance._item.name = changes["name"]
                if "standard_cost" in changes:
                    instance._item.standard_cost = Decimal(changes["standard_cost"])
            elif isinstance(event, ItemDeactivated):
                instance._item.status = ItemStatus.INACTIVE
                instance._is_active = False

        instance._version = len(events)
        instance._record_audit_trail("reconstructed", {"event_count": len(events)})
        return instance

    # ==================== ITEM UPDATE METHODS ====================

    def rename(self, new_name: str, user_id: UUID) -> None:
        """Rename the item."""
        if not self._item:
            raise ValueError("No item loaded")
        if self._is_locked:
            raise ValueError("Cannot rename locked aggregate")
        if not new_name or len(new_name.strip()) < 3:
            raise ValueError("Name must be at least 3 characters")

        old = self._item
        self._item = Item(
            id=old.id,
            legal_entity_id=old.legal_entity_id,
            sku=old.sku,
            name=new_name,
            description=old.description,
            item_type=old.item_type,
            unit_of_measure=old.unit_of_measure,
            current_stock=old.current_stock,
            current_stock_value=old.current_stock_value,
            average_cost=old.average_cost,
            last_cost=old.last_cost,
            reorder_point=old.reorder_point,
            safety_stock=old.safety_stock,
            maximum_stock=old.maximum_stock,
            minimum_stock=old.minimum_stock,
            status=old.status,
            standard_cost=old.standard_cost,
            selling_price=old.selling_price,
            category=old.category,
            warehouse_code=old.warehouse_code,
            created_by=old.created_by,
            created_at=old.created_at,
            updated_at=datetime.now(UTC),
            updated_by=user_id,
            deactivated_at=old.deactivated_at,
            deactivated_by=old.deactivated_by,
            version=old.version + 1,
        )
        self.increment_version()
        self._add_event(
            ItemUpdated(
                aggregate_id=self.id,
                aggregate_version=self._version,
                legal_entity_id=self._item.legal_entity_id,
                sku=self._item.sku,
                changes={"name": new_name},
                user_id=user_id,
                occurred_at=datetime.now(UTC),
            )
        )

    def update_description(self, new_description: str | None, user_id: UUID) -> None:
        """Update item description."""
        if not self._item:
            raise ValueError("No item loaded")
        if self._is_locked:
            raise ValueError("Cannot update locked aggregate")

        old = self._item
        self._item = Item(
            id=old.id,
            legal_entity_id=old.legal_entity_id,
            sku=old.sku,
            name=old.name,
            description=new_description,
            item_type=old.item_type,
            unit_of_measure=old.unit_of_measure,
            current_stock=old.current_stock,
            current_stock_value=old.current_stock_value,
            average_cost=old.average_cost,
            last_cost=old.last_cost,
            reorder_point=old.reorder_point,
            safety_stock=old.safety_stock,
            maximum_stock=old.maximum_stock,
            minimum_stock=old.minimum_stock,
            status=old.status,
            standard_cost=old.standard_cost,
            selling_price=old.selling_price,
            category=old.category,
            warehouse_code=old.warehouse_code,
            created_by=old.created_by,
            created_at=old.created_at,
            updated_at=datetime.now(UTC),
            updated_by=user_id,
            deactivated_at=old.deactivated_at,
            deactivated_by=old.deactivated_by,
            version=old.version + 1,
        )
        self.increment_version()
        self._add_event(
            ItemUpdated(
                aggregate_id=self.id,
                aggregate_version=self._version,
                legal_entity_id=self._item.legal_entity_id,
                sku=self._item.sku,
                changes={"description": new_description},
                user_id=user_id,
                occurred_at=datetime.now(UTC),
            )
        )

    def set_reorder_point(self, reorder_point: Decimal, user_id: UUID) -> None:
        """Set reorder point."""
        if not self._item:
            raise ValueError("No item loaded")
        if self._is_locked:
            raise ValueError("Cannot modify locked aggregate")
        if reorder_point < 0:
            raise ValueError("Reorder point cannot be negative")

        old = self._item
        self._item = Item(
            id=old.id,
            legal_entity_id=old.legal_entity_id,
            sku=old.sku,
            name=old.name,
            description=old.description,
            item_type=old.item_type,
            unit_of_measure=old.unit_of_measure,
            current_stock=old.current_stock,
            current_stock_value=old.current_stock_value,
            average_cost=old.average_cost,
            last_cost=old.last_cost,
            reorder_point=reorder_point,
            safety_stock=old.safety_stock,
            maximum_stock=old.maximum_stock,
            minimum_stock=old.minimum_stock,
            status=old.status,
            standard_cost=old.standard_cost,
            selling_price=old.selling_price,
            category=old.category,
            warehouse_code=old.warehouse_code,
            created_by=old.created_by,
            created_at=old.created_at,
            updated_at=datetime.now(UTC),
            updated_by=user_id,
            deactivated_at=old.deactivated_at,
            deactivated_by=old.deactivated_by,
            version=old.version + 1,
        )
        self.increment_version()
        self._add_event(
            ItemUpdated(
                aggregate_id=self.id,
                aggregate_version=self._version,
                legal_entity_id=self._item.legal_entity_id,
                sku=self._item.sku,
                changes={"reorder_point": str(reorder_point)},
                user_id=user_id,
                occurred_at=datetime.now(UTC),
            )
        )

    def set_safety_stock(self, safety_stock: Decimal, user_id: UUID) -> None:
        """Set safety stock level."""
        if not self._item:
            raise ValueError("No item loaded")
        if self._is_locked:
            raise ValueError("Cannot modify locked aggregate")
        if safety_stock < 0:
            raise ValueError("Safety stock cannot be negative")

        old = self._item
        self._item = Item(
            id=old.id,
            legal_entity_id=old.legal_entity_id,
            sku=old.sku,
            name=old.name,
            description=old.description,
            item_type=old.item_type,
            unit_of_measure=old.unit_of_measure,
            current_stock=old.current_stock,
            current_stock_value=old.current_stock_value,
            average_cost=old.average_cost,
            last_cost=old.last_cost,
            reorder_point=old.reorder_point,
            safety_stock=safety_stock,
            maximum_stock=old.maximum_stock,
            minimum_stock=old.minimum_stock,
            status=old.status,
            standard_cost=old.standard_cost,
            selling_price=old.selling_price,
            category=old.category,
            warehouse_code=old.warehouse_code,
            created_by=old.created_by,
            created_at=old.created_at,
            updated_at=datetime.now(UTC),
            updated_by=user_id,
            deactivated_at=old.deactivated_at,
            deactivated_by=old.deactivated_by,
            version=old.version + 1,
        )
        self.increment_version()
        self._add_event(
            ItemUpdated(
                aggregate_id=self.id,
                aggregate_version=self._version,
                legal_entity_id=self._item.legal_entity_id,
                sku=self._item.sku,
                changes={"safety_stock": str(safety_stock)},
                user_id=user_id,
                occurred_at=datetime.now(UTC),
            )
        )

    def set_standard_cost(self, standard_cost: Decimal, user_id: UUID) -> None:
        """Set standard cost."""
        if not self._item:
            raise ValueError("No item loaded")
        if self._is_locked:
            raise ValueError("Cannot modify locked aggregate")
        if standard_cost < 0:
            raise ValueError("Standard cost cannot be negative")

        old = self._item
        self._item = Item(
            id=old.id,
            legal_entity_id=old.legal_entity_id,
            sku=old.sku,
            name=old.name,
            description=old.description,
            item_type=old.item_type,
            unit_of_measure=old.unit_of_measure,
            current_stock=old.current_stock,
            current_stock_value=old.current_stock_value,
            average_cost=old.average_cost,
            last_cost=old.last_cost,
            reorder_point=old.reorder_point,
            safety_stock=old.safety_stock,
            maximum_stock=old.maximum_stock,
            minimum_stock=old.minimum_stock,
            status=old.status,
            standard_cost=standard_cost,
            selling_price=old.selling_price,
            category=old.category,
            warehouse_code=old.warehouse_code,
            created_by=old.created_by,
            created_at=old.created_at,
            updated_at=datetime.now(UTC),
            updated_by=user_id,
            deactivated_at=old.deactivated_at,
            deactivated_by=old.deactivated_by,
            version=old.version + 1,
        )
        self.increment_version()
        self._add_event(
            ItemUpdated(
                aggregate_id=self.id,
                aggregate_version=self._version,
                legal_entity_id=self._item.legal_entity_id,
                sku=self._item.sku,
                changes={"standard_cost": str(standard_cost)},
                user_id=user_id,
                occurred_at=datetime.now(UTC),
            )
        )

    def set_selling_price(self, selling_price: Decimal, user_id: UUID) -> None:
        """Set selling price."""
        if not self._item:
            raise ValueError("No item loaded")
        if self._is_locked:
            raise ValueError("Cannot modify locked aggregate")
        if selling_price < 0:
            raise ValueError("Selling price cannot be negative")

        old = self._item
        self._item = Item(
            id=old.id,
            legal_entity_id=old.legal_entity_id,
            sku=old.sku,
            name=old.name,
            description=old.description,
            item_type=old.item_type,
            unit_of_measure=old.unit_of_measure,
            current_stock=old.current_stock,
            current_stock_value=old.current_stock_value,
            average_cost=old.average_cost,
            last_cost=old.last_cost,
            reorder_point=old.reorder_point,
            safety_stock=old.safety_stock,
            maximum_stock=old.maximum_stock,
            minimum_stock=old.minimum_stock,
            status=old.status,
            standard_cost=old.standard_cost,
            selling_price=selling_price,
            category=old.category,
            warehouse_code=old.warehouse_code,
            created_by=old.created_by,
            created_at=old.created_at,
            updated_at=datetime.now(UTC),
            updated_by=user_id,
            deactivated_at=old.deactivated_at,
            deactivated_by=old.deactivated_by,
            version=old.version + 1,
        )
        self.increment_version()
        self._add_event(
            ItemUpdated(
                aggregate_id=self.id,
                aggregate_version=self._version,
                legal_entity_id=self._item.legal_entity_id,
                sku=self._item.sku,
                changes={"selling_price": str(selling_price)},
                user_id=user_id,
                occurred_at=datetime.now(UTC),
            )
        )

    def set_category(self, category: str | None, user_id: UUID) -> None:
        """Set item category."""
        if not self._item:
            raise ValueError("No item loaded")
        if self._is_locked:
            raise ValueError("Cannot modify locked aggregate")

        old = self._item
        self._item = Item(
            id=old.id,
            legal_entity_id=old.legal_entity_id,
            sku=old.sku,
            name=old.name,
            description=old.description,
            item_type=old.item_type,
            unit_of_measure=old.unit_of_measure,
            current_stock=old.current_stock,
            current_stock_value=old.current_stock_value,
            average_cost=old.average_cost,
            last_cost=old.last_cost,
            reorder_point=old.reorder_point,
            safety_stock=old.safety_stock,
            maximum_stock=old.maximum_stock,
            minimum_stock=old.minimum_stock,
            status=old.status,
            standard_cost=old.standard_cost,
            selling_price=old.selling_price,
            category=category,
            warehouse_code=old.warehouse_code,
            created_by=old.created_by,
            created_at=old.created_at,
            updated_at=datetime.now(UTC),
            updated_by=user_id,
            deactivated_at=old.deactivated_at,
            deactivated_by=old.deactivated_by,
            version=old.version + 1,
        )
        self.increment_version()
        self._add_event(
            ItemUpdated(
                aggregate_id=self.id,
                aggregate_version=self._version,
                legal_entity_id=self._item.legal_entity_id,
                sku=self._item.sku,
                changes={"category": category},
                user_id=user_id,
                occurred_at=datetime.now(UTC),
            )
        )

    def update_standard_cost(self, new_cost: Decimal, user_id: UUID) -> None:
        """Update standard cost (alias for set_standard_cost)."""
        self.set_standard_cost(new_cost, user_id)

    # ==================== DEACTIVATE ====================

    def deactivate_item(self, reason: str | None, user_id: UUID) -> None:
        """Deactivate the item."""
        if not self._item:
            raise ValueError("No item loaded")
        if self._is_locked:
            raise ValueError("Cannot deactivate locked aggregate")
        if self._item.current_stock > 0:
            raise ValueError("Cannot deactivate item with current stock")

        old = self._item
        self._item = Item(
            id=old.id,
            legal_entity_id=old.legal_entity_id,
            sku=old.sku,
            name=old.name,
            description=old.description,
            item_type=old.item_type,
            unit_of_measure=old.unit_of_measure,
            current_stock=old.current_stock,
            current_stock_value=old.current_stock_value,
            average_cost=old.average_cost,
            last_cost=old.last_cost,
            reorder_point=old.reorder_point,
            safety_stock=old.safety_stock,
            maximum_stock=old.maximum_stock,
            minimum_stock=old.minimum_stock,
            status=ItemStatus.INACTIVE,
            standard_cost=old.standard_cost,
            selling_price=old.selling_price,
            category=old.category,
            warehouse_code=old.warehouse_code,
            created_by=old.created_by,
            created_at=old.created_at,
            updated_at=datetime.now(UTC),
            updated_by=user_id,
            deactivated_at=datetime.now(UTC),
            deactivated_by=user_id,
            version=old.version + 1,
        )
        self.increment_version()
        self._is_active = False
        self._add_event(
            ItemDeactivated(
                aggregate_id=self.id,
                sku=self._item.sku,
                reason=reason,
                user_id=user_id,
                occurred_at=datetime.now(UTC),
            )
        )

    # ==================== STOCK MOVEMENTS ====================

    def receive_stock(self, movement: StockMovement, user_id: UUID) -> None:
        """Receive stock (inbound movement)."""
        if not self._item:
            raise ValueError("No item loaded")
        if self._is_locked:
            raise ValueError("Cannot modify locked aggregate")
        if movement.quantity <= 0:
            raise ValueError("Quantity must be positive")
        if movement.unit_cost < 0:
            raise ValueError("Unit cost cannot be negative")

        new_stock = self._item.current_stock + movement.quantity
        new_value = self._item.current_stock_value + (movement.quantity * movement.unit_cost)
        new_avg = (new_value / new_stock).quantize(Decimal("0.01")) if new_stock > 0 else Decimal(0)

        self._item = Item(
            id=self._item.id,
            legal_entity_id=self._item.legal_entity_id,
            sku=self._item.sku,
            name=self._item.name,
            description=self._item.description,
            item_type=self._item.item_type,
            unit_of_measure=self._item.unit_of_measure,
            current_stock=new_stock,
            current_stock_value=new_value,
            average_cost=new_avg,
            last_cost=movement.unit_cost,
            reorder_point=self._item.reorder_point,
            safety_stock=self._item.safety_stock,
            maximum_stock=self._item.maximum_stock,
            minimum_stock=self._item.minimum_stock,
            status=self._item.status,
            standard_cost=self._item.standard_cost,
            selling_price=self._item.selling_price,
            category=self._item.category,
            warehouse_code=self._item.warehouse_code,
            created_by=self._item.created_by,
            created_at=self._item.created_at,
            updated_at=datetime.now(UTC),
            updated_by=user_id,
            deactivated_at=self._item.deactivated_at,
            deactivated_by=self._item.deactivated_by,
            version=self._item.version + 1,
        )

        self._fifo_layers.append(
            {
                "quantity": movement.quantity,
                "unit_cost": movement.unit_cost,
                "remaining_quantity": movement.quantity,
                "purchase_date": datetime.now(UTC),
            }
        )

        self.increment_version()
        self._add_event(
            StockMovementCreated(
                aggregate_id=self.id,
                movement_id=movement.id,
                item_id=self._item.id,
                sku=self._item.sku,
                movement_type=movement.movement_type.value,
                quantity=movement.quantity,
                unit_cost=movement.unit_cost,
                total_value=movement.quantity * movement.unit_cost,
                user_id=user_id,
                occurred_at=datetime.now(UTC),
            )
        )

    def issue_stock(self, movement: StockMovement, user_id: UUID) -> None:
        """Issue stock (outbound movement)."""
        if not self._item:
            raise ValueError("No item loaded")
        if self._is_locked:
            raise ValueError("Cannot modify locked aggregate")
        if movement.quantity <= 0:
            raise ValueError("Quantity must be positive")
        if movement.quantity > self._item.current_stock:
            raise ValueError(
                f"Insufficient stock: {self._item.current_stock} < {movement.quantity}"
            )

        total_cost = self._fifo.calculate_cost(self._fifo_layers, movement.quantity)

        new_stock = self._item.current_stock - movement.quantity
        new_value = self._item.current_stock_value - total_cost

        self._item = Item(
            id=self._item.id,
            legal_entity_id=self._item.legal_entity_id,
            sku=self._item.sku,
            name=self._item.name,
            description=self._item.description,
            item_type=self._item.item_type,
            unit_of_measure=self._item.unit_of_measure,
            current_stock=new_stock,
            current_stock_value=new_value,
            average_cost=self._item.average_cost,
            last_cost=self._item.last_cost,
            reorder_point=self._item.reorder_point,
            safety_stock=self._item.safety_stock,
            maximum_stock=self._item.maximum_stock,
            minimum_stock=self._item.minimum_stock,
            status=self._item.status,
            standard_cost=self._item.standard_cost,
            selling_price=self._item.selling_price,
            category=self._item.category,
            warehouse_code=self._item.warehouse_code,
            created_by=self._item.created_by,
            created_at=self._item.created_at,
            updated_at=datetime.now(UTC),
            updated_by=user_id,
            deactivated_at=self._item.deactivated_at,
            deactivated_by=self._item.deactivated_by,
            version=self._item.version + 1,
        )

        # Update FIFO layers
        remaining_qty = movement.quantity
        for layer in self._fifo_layers:
            if remaining_qty <= 0:
                break
            if layer["remaining_quantity"] > 0:
                consume = min(layer["remaining_quantity"], remaining_qty)
                layer["remaining_quantity"] -= consume
                remaining_qty -= consume
        self._fifo_layers = [l for l in self._fifo_layers if l["remaining_quantity"] > 0]

        self.increment_version()
        self._add_event(
            StockMovementCreated(
                aggregate_id=self.id,
                movement_id=movement.id,
                item_id=self._item.id,
                sku=self._item.sku,
                movement_type=movement.movement_type.value,
                quantity=-movement.quantity,
                unit_cost=movement.unit_cost,
                total_value=total_cost,
                user_id=user_id,
                occurred_at=datetime.now(UTC),
            )
        )

    def adjust_stock(
        self,
        adjustment_amount: Decimal,
        reason: AdjustmentReason,
        unit_cost: Decimal,
        user_id: UUID,
    ) -> None:
        """Adjust stock quantity."""
        if not self._item:
            raise ValueError("No item loaded")
        if self._is_locked:
            raise ValueError("Cannot modify locked aggregate")
        if adjustment_amount == 0:
            return

        if adjustment_amount > 0:
            new_stock = self._item.current_stock + adjustment_amount
            new_value = self._item.current_stock_value + (adjustment_amount * unit_cost)
            new_avg = (
                (new_value / new_stock).quantize(Decimal("0.01")) if new_stock > 0 else Decimal(0)
            )

            self._item = Item(
                id=self._item.id,
                legal_entity_id=self._item.legal_entity_id,
                sku=self._item.sku,
                name=self._item.name,
                description=self._item.description,
                item_type=self._item.item_type,
                unit_of_measure=self._item.unit_of_measure,
                current_stock=new_stock,
                current_stock_value=new_value,
                average_cost=new_avg,
                last_cost=self._item.last_cost,
                reorder_point=self._item.reorder_point,
                safety_stock=self._item.safety_stock,
                maximum_stock=self._item.maximum_stock,
                minimum_stock=self._item.minimum_stock,
                status=self._item.status,
                standard_cost=self._item.standard_cost,
                selling_price=self._item.selling_price,
                category=self._item.category,
                warehouse_code=self._item.warehouse_code,
                created_by=self._item.created_by,
                created_at=self._item.created_at,
                updated_at=datetime.now(UTC),
                updated_by=user_id,
                deactivated_at=self._item.deactivated_at,
                deactivated_by=self._item.deactivated_by,
                version=self._item.version + 1,
            )
            self._fifo_layers.append(
                {
                    "quantity": adjustment_amount,
                    "unit_cost": unit_cost,
                    "remaining_quantity": adjustment_amount,
                    "purchase_date": datetime.now(UTC),
                }
            )
        else:
            qty = -adjustment_amount
            if qty > self._item.current_stock:
                raise ValueError(
                    f"Insufficient stock for adjustment: {self._item.current_stock} < {qty}"
                )

            total_cost = self._fifo.calculate_cost(self._fifo_layers, qty)
            new_stock = self._item.current_stock - qty
            new_value = self._item.current_stock_value - total_cost

            self._item = Item(
                id=self._item.id,
                legal_entity_id=self._item.legal_entity_id,
                sku=self._item.sku,
                name=self._item.name,
                description=self._item.description,
                item_type=self._item.item_type,
                unit_of_measure=self._item.unit_of_measure,
                current_stock=new_stock,
                current_stock_value=new_value,
                average_cost=self._item.average_cost,
                last_cost=self._item.last_cost,
                reorder_point=self._item.reorder_point,
                safety_stock=self._item.safety_stock,
                maximum_stock=self._item.maximum_stock,
                minimum_stock=self._item.minimum_stock,
                status=self._item.status,
                standard_cost=self._item.standard_cost,
                selling_price=self._item.selling_price,
                category=self._item.category,
                warehouse_code=self._item.warehouse_code,
                created_by=self._item.created_by,
                created_at=self._item.created_at,
                updated_at=datetime.now(UTC),
                updated_by=user_id,
                deactivated_at=self._item.deactivated_at,
                deactivated_by=self._item.deactivated_by,
                version=self._item.version + 1,
            )

            remaining_qty = qty
            for layer in self._fifo_layers:
                if remaining_qty <= 0:
                    break
                if layer["remaining_quantity"] > 0:
                    consume = min(layer["remaining_quantity"], remaining_qty)
                    layer["remaining_quantity"] -= consume
                    remaining_qty -= consume
            self._fifo_layers = [l for l in self._fifo_layers if l["remaining_quantity"] > 0]

        adjustment_entity = StockAdjustmentEntity(
            adjustment_id=uuid4(),
            adjustment_number=f"ADJ-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
            adjustment_type=AdjustmentType.CORRECTION,
            warehouse_id=uuid4(),
            warehouse_name="",
            item_id=self._item.id,
            item_sku=self._item.sku,
            item_name=self._item.name,
            quantity=adjustment_amount,
            unit_cost=unit_cost,
            total_value=abs(adjustment_amount) * unit_cost,
            adjustment_date=datetime.now(UTC).date(),
            status=AdjustmentStatus.EXECUTED,
            reason=reason.value if hasattr(reason, "value") else str(reason),
            created_by=user_id,
            legal_entity_id=self.legal_entity_id,
        )

        self.increment_version()
        self._add_event(
            StockAdjusted(
                aggregate_id=self.id,
                aggregate_version=self._version,
                adjustment=adjustment_entity,
                adjusted_by=str(user_id),
                user_id=str(user_id),
            )
        )

    # ==================== HELPER METHODS ====================

    def update_stock(
        self, new_stock: Decimal, new_value: Decimal, new_avg_cost: Decimal, user_id: UUID
    ) -> None:
        """Update stock quantities and values (used by tests)."""
        if not self._item:
            raise ValueError("No item loaded")
        if self._is_locked:
            raise ValueError("Cannot modify locked aggregate")
        old = self._item
        self._item = Item(
            id=old.id,
            legal_entity_id=old.legal_entity_id,
            sku=old.sku,
            name=old.name,
            description=old.description,
            item_type=old.item_type,
            unit_of_measure=old.unit_of_measure,
            current_stock=new_stock,
            current_stock_value=new_value,
            average_cost=new_avg_cost,
            last_cost=old.last_cost,
            reorder_point=old.reorder_point,
            safety_stock=old.safety_stock,
            maximum_stock=old.maximum_stock,
            minimum_stock=old.minimum_stock,
            status=old.status,
            standard_cost=old.standard_cost,
            selling_price=old.selling_price,
            category=old.category,
            warehouse_code=old.warehouse_code,
            created_by=old.created_by,
            created_at=old.created_at,
            updated_at=datetime.now(UTC),
            updated_by=user_id,
            deactivated_at=old.deactivated_at,
            deactivated_by=old.deactivated_by,
            version=old.version + 1,
        )
        self.increment_version()

    def pop_domain_events(self) -> list[Any]:
        """Pop all domain events (alias for pop_events)."""
        return self.pop_events()

    def get_fifo_layers(self) -> list:
        """Get current FIFO layers."""
        return self._fifo_layers

    def to_dict(self) -> dict:
        """Convert aggregate to dictionary."""
        return {
            "id": str(self.id),
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else None,
            "version": self._version,
            "item": self._item.to_dict() if self._item else None,
            "current_stock": str(self.current_stock),
            "current_stock_value": str(self.current_stock_value),
            "average_cost": str(self.average_cost),
            "is_locked": self._is_locked,
            "is_active": self._is_active,
            "fifo_layers_count": len(self._fifo_layers),
        }

    @classmethod
    def from_dict(cls, data: dict) -> InventoryAggregate:
        """Create aggregate from dictionary."""
        instance = cls(
            id=UUID(data["id"]) if data.get("id") else None,
            legal_entity_id=UUID(data["legal_entity_id"]) if data.get("legal_entity_id") else None,
            version=data.get("version", 0),
        )
        if data.get("item"):
            instance._item = Item.from_dict(data["item"])
        instance._fifo_layers = data.get("fifo_layers", [])
        instance._is_locked = data.get("is_locked", False)
        instance._is_active = data.get("is_active", True)
        instance._version = data.get("version", 0)
        return instance


# Alias for repository compatibility
InventoryItemAggregate = InventoryAggregate

__all__ = [
    "InventoryAggregate",
    "InventoryItemAggregate",
    "StockMovementType",
]
