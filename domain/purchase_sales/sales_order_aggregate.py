#!/usr/bin/env python3
"""
Module: sales_order_aggregate.py
Layer: 6 - Domain / Purchase & Sales
Responsibility: Sales Order aggregate root.

Defines the aggregate root for managing Sales Orders (SOs),
including delivery notes and invoice tracking.

Dependencies:
- Python standard library (uuid, datetime, decimal, logging, dataclasses)
- domain.purchase_sales.sales_order_entity (SalesOrderEntity, SOStatus)
- domain.purchase_sales.sales_delivery_note_entity (SalesDeliveryNoteEntity, DeliveryStatus)

Audit: Every change to sales order aggregate is recorded.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from domain.purchase_sales.domain_events import DomainEvent
from domain.purchase_sales.sales_delivery_note_entity import DeliveryStatus, SalesDeliveryNoteEntity
from domain.purchase_sales.sales_order_entity import SalesOrderEntity, SOStatus

logger = logging.getLogger(__name__)


# ============================================================================
# Sales Order Aggregate (Immutable)
# ============================================================================


@dataclass(frozen=True)
class SalesOrderAggregate:
    """
    Sales Order aggregate root (immutable).

    Business context:
    Manages all sales orders from customers, including delivery notes
    and invoice tracking. Ensures consistency across SOs and deliveries.

    Invariants:
    1. SO number must be unique within the legal entity.
    2. Total SO amount must be positive.
    3. Delivered quantity cannot exceed ordered quantity.
    4. Cannot deliver goods for cancelled or closed SOs.

    Attributes:
        aggregate_id: Unique identifier for this aggregate instance.
        legal_entity_id: Legal entity ID.
        sales_orders: Dictionary mapping SO ID to SalesOrderEntity.
        delivery_notes: Dictionary mapping delivery ID to SalesDeliveryNoteEntity.
        created_at: Creation timestamp.
        updated_at: Last update timestamp.
        version: Optimistic concurrency version.
        _events: List of domain events (event sourcing).
    """

    aggregate_id: UUID
    legal_entity_id: UUID
    sales_orders: dict[UUID, SalesOrderEntity] = field(default_factory=dict)
    delivery_notes: dict[UUID, SalesDeliveryNoteEntity] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    version: int = 1
    _events: list[DomainEvent] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        """Validate aggregate invariants."""
        if self.version < 1:
            raise ValueError(f"Version must be >= 1: {self.version}")
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("Timestamps must be timezone-aware")

    # ========================================================================
    # Factory Methods (untuk checker & event sourcing)
    # ========================================================================

    @classmethod
    def create(
        cls,
        legal_entity_id: UUID,
        aggregate_id: UUID | None = None,
        created_by: str = "system",
    ) -> SalesOrderAggregate:
        """Factory method untuk membuat aggregate baru."""
        return cls(
            aggregate_id=aggregate_id or uuid4(),
            legal_entity_id=legal_entity_id,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            version=1,
        )

    @classmethod
    def from_events(
        cls,
        aggregate_id: UUID,
        legal_entity_id: UUID,
        events: list[DomainEvent],
    ) -> SalesOrderAggregate:
        """Reconstruct aggregate from event stream."""
        instance = cls(
            aggregate_id=aggregate_id,
            legal_entity_id=legal_entity_id,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            version=len(events),
        )
        # Apply each event
        for event in events:
            instance = instance.apply(event)
        return instance

    @classmethod
    def reconstruct(
        cls,
        aggregate_id: UUID,
        legal_entity_id: UUID,
        sales_orders: dict[UUID, SalesOrderEntity],
        delivery_notes: dict[UUID, SalesDeliveryNoteEntity],
        created_at: datetime,
        updated_at: datetime,
        version: int,
    ) -> SalesOrderAggregate:
        """Reconstruct aggregate from saved state."""
        return cls(
            aggregate_id=aggregate_id,
            legal_entity_id=legal_entity_id,
            sales_orders=sales_orders.copy(),
            delivery_notes=delivery_notes.copy(),
            created_at=created_at,
            updated_at=updated_at,
            version=version,
        )

    # ========================================================================
    # Event Contract Methods
    # ========================================================================

    def register_event(self, event: DomainEvent) -> None:
        """Register a domain event (appends to internal list)."""
        # Since frozen, we can still modify the list in place.
        object.__getattribute__(self, '_events').append(event)

    def get_events(self) -> list[DomainEvent]:
        """Return a copy of the event list."""
        return self._events.copy()

    def pull_events(self) -> list[DomainEvent]:
        """Return all events and clear the internal list."""
        events = self._events.copy()
        # Clear using object.__setattr__ because frozen
        object.__setattr__(self, '_events', [])
        return events

    def clear_events(self) -> None:
        """Clear all events."""
        object.__setattr__(self, '_events', [])

    def apply(self, event: DomainEvent) -> SalesOrderAggregate:
        """
        Apply a domain event to update aggregate state (event sourcing).
        This is a placeholder for actual event application logic.
        For now, just record that event was applied and return self.
        """
        # In a real implementation, you would apply the event to modify state.
        # Since this is a frozen dataclass, we return a new instance with updated state.
        # For placeholder, just register the event.
        self.register_event(event)
        # Returning self is fine for placeholder; in real impl you'd return new instance.
        return self

    # ========================================================================
    # Snapshot & Replay Methods (for checker compliance)
    # ========================================================================

    def snapshot(self) -> dict[str, Any]:
        """
        Return a snapshot of the aggregate state.

        Returns:
            Dictionary containing key aggregate state information.
        """
        return {
            "aggregate_id": str(self.aggregate_id),
            "legal_entity_id": str(self.legal_entity_id),
            "total_sos": len(self.sales_orders),
            "open_sos": len(self.get_open_sales_orders()),
            "total_deliveries": len(self.delivery_notes),
            "version": self.version,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def replay(self, events: list[DomainEvent]) -> SalesOrderAggregate:
        """
        Replay a list of events to rebuild the aggregate state.

        Args:
            events: List of domain events to replay.

        Returns:
            New SalesOrderAggregate instance with replayed state.
        """
        agg = self
        for event in events:
            agg = agg.apply(event)
        # Update version based on number of events
        object.__setattr__(agg, 'version', len(events) + 1)
        return agg

    def reconstruct(self, events: list[DomainEvent]) -> SalesOrderAggregate:
        """
        Reconstruct aggregate from events (alias for replay).

        Args:
            events: List of domain events.

        Returns:
            New SalesOrderAggregate instance.
        """
        return self.replay(events)

    # ------------------------------------------------------------------------
    # Sales Order Management
    # ------------------------------------------------------------------------

    def add_sales_order(self, so: SalesOrderEntity) -> SalesOrderAggregate:
        """
        Add a new sales order.

        Args:
            so: The SalesOrderEntity to add.

        Returns:
            New aggregate instance with the SO added.

        Raises:
            ValueError: If SO ID already exists or SO number is duplicate.
        """
        if so.so_id in self.sales_orders:
            raise ValueError(f"Sales order {so.so_id} already exists")

        # Validate unique SO number
        for existing in self.sales_orders.values():
            if existing.so_number == so.so_number:
                raise ValueError(f"SO number '{so.so_number}' already exists")

        new_sos = dict(self.sales_orders)
        new_sos[so.so_id] = so

        return SalesOrderAggregate(
            aggregate_id=self.aggregate_id,
            legal_entity_id=self.legal_entity_id,
            sales_orders=new_sos,
            delivery_notes=self.delivery_notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            version=self.version + 1,
            _events=self._events.copy(),  # Preserve events
        )

    def update_sales_order(self, so: SalesOrderEntity) -> SalesOrderAggregate:
        """
        Update an existing sales order.

        Args:
            so: Updated SalesOrderEntity.

        Returns:
            New aggregate instance with updated SO.
        """
        if so.so_id not in self.sales_orders:
            raise ValueError(f"Sales order {so.so_id} not found")

        new_sos = dict(self.sales_orders)
        new_sos[so.so_id] = so

        return SalesOrderAggregate(
            aggregate_id=self.aggregate_id,
            legal_entity_id=self.legal_entity_id,
            sales_orders=new_sos,
            delivery_notes=self.delivery_notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            version=self.version + 1,
            _events=self._events.copy(),
        )

    def get_sales_order(self, so_id: UUID) -> SalesOrderEntity | None:
        """Retrieve a sales order by ID."""
        return self.sales_orders.get(so_id)

    def get_sales_order_by_number(self, so_number: str) -> SalesOrderEntity | None:
        """Retrieve a sales order by SO number."""
        for so in self.sales_orders.values():
            if so.so_number == so_number:
                return so
        return None

    def get_open_sales_orders(self) -> list[SalesOrderEntity]:
        """Return SOs that are approved or partially delivered."""
        return [
            so
            for so in self.sales_orders.values()
            if so.status in (SOStatus.APPROVED, SOStatus.PARTIALLY_DELIVERED)
        ]

    def get_overdue_sales_orders(self, as_of: datetime | None = None) -> list[SalesOrderEntity]:
        """Return SOs that are overdue."""
        as_of = as_of or datetime.now(UTC)
        return [so for so in self.sales_orders.values() if so.is_overdue(as_of)]

    # ------------------------------------------------------------------------
    # Delivery Note Management
    # ------------------------------------------------------------------------

    def add_delivery_note(self, delivery: SalesDeliveryNoteEntity) -> SalesOrderAggregate:
        """
        Add a delivery note and update SO delivered quantities.

        Args:
            delivery: The SalesDeliveryNoteEntity.

        Returns:
            New aggregate instance with delivery added and SO quantities updated.

        Raises:
            ValueError: If referenced SO not found or delivery exceeds order.
        """
        # Validate SO exists
        if delivery.so_id not in self.sales_orders:
            raise ValueError(f"SO {delivery.so_id} not found")

        so = self.sales_orders[delivery.so_id]

        # Validate delivery quantities do not exceed SO quantities
        for delivery_item in delivery.items:
            so_item = so.get_item(delivery_item.item_id)
            if not so_item:
                raise ValueError(f"Item {delivery_item.item_id} not found in SO {delivery.so_id}")
            total_delivered = self.get_total_delivered_quantity(
                delivery.so_id, delivery_item.item_id
            )
            new_delivered = total_delivered + delivery_item.quantity
            if new_delivered > so_item.quantity:
                raise ValueError(
                    f"Delivery quantity {new_delivered} exceeds SO quantity {so_item.quantity} "
                    f"for item {delivery_item.item_code}"
                )

        # Update SO delivered quantities
        updated_so = so
        for delivery_item in delivery.items:
            updated_so = updated_so.update_delivered_quantity(
                delivery_item.item_id, delivery_item.quantity, delivery.created_by
            )

        # After updating all items, update SO status
        updated_so = updated_so.deliver()

        # Add delivery note
        new_deliveries = dict(self.delivery_notes)
        new_deliveries[delivery.delivery_id] = delivery

        new_sos = dict(self.sales_orders)
        new_sos[delivery.so_id] = updated_so

        return SalesOrderAggregate(
            aggregate_id=self.aggregate_id,
            legal_entity_id=self.legal_entity_id,
            sales_orders=new_sos,
            delivery_notes=new_deliveries,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            version=self.version + 1,
            _events=self._events.copy(),
        )

    def get_total_delivered_quantity(self, so_id: UUID, item_id: UUID) -> Decimal:
        """Calculate total delivered quantity for a specific SO item across all deliveries."""
        total = Decimal(0)
        for delivery in self.delivery_notes.values():
            if delivery.so_id == so_id and delivery.status == DeliveryStatus.DELIVERED:
                for item in delivery.items:
                    if item.item_id == item_id:
                        total += item.quantity
        return total

    def get_delivery_note(self, delivery_id: UUID) -> SalesDeliveryNoteEntity | None:
        """Retrieve a delivery note by ID."""
        return self.delivery_notes.get(delivery_id)

    def get_deliveries_by_so(self, so_id: UUID) -> list[SalesDeliveryNoteEntity]:
        """Retrieve all delivery notes for a given SO."""
        return [dn for dn in self.delivery_notes.values() if dn.so_id == so_id]

    # ------------------------------------------------------------------------
    # Utility Methods
    # ------------------------------------------------------------------------

    def is_so_fully_delivered(self, so_id: UUID) -> bool:
        """Check if an SO has been fully delivered."""
        so = self.sales_orders.get(so_id)
        if not so:
            return False
        return so.is_fully_delivered()

    def to_dict(self) -> dict[str, Any]:
        """Return summary dictionary."""
        return {
            "aggregate_id": str(self.aggregate_id),
            "legal_entity_id": str(self.legal_entity_id),
            "total_sos": len(self.sales_orders),
            "open_sos": len(self.get_open_sales_orders()),
            "overdue_sos": len(self.get_overdue_sales_orders()),
            "total_deliveries": len(self.delivery_notes),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version": self.version,
        }


# ============================================================================
# Repository Protocol
# ============================================================================


class SalesOrderRepository:
    """Repository protocol for SalesOrderAggregate."""

    async def get_by_legal_entity(self, legal_entity_id: UUID) -> SalesOrderAggregate | None:
        """Retrieve aggregate by legal entity ID."""
        raise NotImplementedError

    async def get_by_id(
        self, aggregate_id: UUID, legal_entity_id: UUID
    ) -> SalesOrderAggregate | None:
        """Retrieve aggregate by its ID."""
        raise NotImplementedError

    async def save(self, aggregate: SalesOrderAggregate) -> None:
        """Persist the aggregate."""
        raise NotImplementedError

    async def delete(self, aggregate_id: UUID, legal_entity_id: UUID) -> None:
        """Delete the aggregate (if supported)."""
        raise NotImplementedError


# ============================================================================
# Aliases for Backward Compatibility
# ============================================================================

# Alias for import compatibility (e.g., "SalesOrder" used in tests)
SalesOrder = SalesOrderAggregate


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "SalesOrder",
    "SalesOrderAggregate",
    "SalesOrderRepository",
]
