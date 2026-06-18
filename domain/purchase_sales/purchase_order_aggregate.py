#!/usr/bin/env python3
"""
Module: purchase_order_aggregate.py
Layer: 6 - Domain / Purchase & Sales
Responsibility: Purchase Order aggregate root.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from domain.purchase_sales.domain_events import (
    DomainEvent,
    GoodsReceiptCreatedEvent,
    PurchaseOrderApprovedEvent,
    PurchaseOrderCreatedEvent,
)
from domain.purchase_sales.goods_receipt_note_entity import GoodsReceiptNoteEntity, GRNStatus
from domain.purchase_sales.purchase_order_entity import POStatus, PurchaseOrderEntity

logger = logging.getLogger(__name__)


@dataclass
class PurchaseOrderAggregate:
    aggregate_id: UUID
    legal_entity_id: UUID
    purchase_orders: dict[UUID, PurchaseOrderEntity] = field(default_factory=dict)
    goods_receipts: dict[UUID, GoodsReceiptNoteEntity] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    version: int = 1
    _events: list[DomainEvent] = field(default_factory=list, repr=False)
    _audit_trail: list[dict] = field(default_factory=list, repr=False)
    _snapshots: list[dict] = field(default_factory=list, repr=False)
    _is_locked: bool = False
    _locked_by: str | None = None
    _locked_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError(f"Version must be >= 1: {self.version}")
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("Timestamps must be timezone-aware")

    @property
    def id(self) -> UUID:
        return self.aggregate_id

    @property
    def is_locked(self) -> bool:
        return self._is_locked

    def _add_event(self, event: DomainEvent) -> None:
        self._events.append(event)
        self._record_audit("event_added", {"event_type": event.event_type.value})

    def clear_events(self) -> None:
        self._events.clear()
        self._record_audit("events_cleared", {})

    def get_events(self) -> list[DomainEvent]:
        return self._events.copy()

    def pop_events(self) -> list[DomainEvent]:
        events = self._events.copy()
        self._events.clear()
        return events

    def _record_audit(self, action: str, details: dict) -> None:
        self._audit_trail.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "action": action,
                "details": details,
                "version": self.version,
            }
        )

    def get_audit_trail(self) -> list[dict]:
        return self._audit_trail.copy()

    def snapshot(self) -> dict:
        snapshot_data = {
            "aggregate_id": str(self.aggregate_id),
            "aggregate_type": "PurchaseOrderAggregate",
            "version": self.version,
            "timestamp": datetime.now(UTC).isoformat(),
            "state": {
                "legal_entity_id": str(self.legal_entity_id),
                "total_pos": len(self.purchase_orders),
                "total_grns": len(self.goods_receipts),
            },
            "hash": self._compute_hash(),
        }
        self._snapshots.append(snapshot_data)
        return snapshot_data

    def _compute_hash(self) -> str:
        state_str = json.dumps(
            {
                "id": str(self.aggregate_id),
                "version": self.version,
                "total_pos": len(self.purchase_orders),
            },
            sort_keys=True,
        )
        return hashlib.sha256(state_str.encode()).hexdigest()

    def lock(self, user_id: str, reason: str | None = None) -> PurchaseOrderAggregate:
        if self._is_locked:
            raise ValueError(f"Aggregate is already locked by {self._locked_by}")
        self._record_audit("locked", {"user_id": user_id, "reason": reason})
        self._is_locked = True
        self._locked_by = user_id
        self._locked_at = datetime.now(UTC)
        return self

    def unlock(self, user_id: str) -> PurchaseOrderAggregate:
        if not self._is_locked:
            raise ValueError("Aggregate is not locked")
        if self._locked_by != user_id:
            raise ValueError(f"Aggregate locked by {self._locked_by}, cannot unlock by {user_id}")
        self._record_audit("unlocked", {"user_id": user_id})
        self._is_locked = False
        self._locked_by = None
        self._locked_at = None
        return self

    def increment_version(self) -> None:
        self.version += 1
        self.updated_at = datetime.now(UTC)

    # ==================== PURCHASE ORDER MANAGEMENT ====================

    def add_purchase_order(
        self, po: PurchaseOrderEntity, created_by: str
    ) -> PurchaseOrderAggregate:
        if self._is_locked:
            raise ValueError("Cannot add PO to locked aggregate")
        if po.po_id in self.purchase_orders:
            raise ValueError(f"Purchase order {po.po_id} already exists")
        for existing in self.purchase_orders.values():
            if existing.po_number == po.po_number:
                raise ValueError(f"PO number '{po.po_number}' already exists")

        new_pos = dict(self.purchase_orders)
        new_pos[po.po_id] = po

        self._add_event(
            PurchaseOrderCreatedEvent(
                aggregate_id=self.aggregate_id,
                aggregate_version=self.version + 1,
                purchase_order=po,
                created_by=created_by,
            )
        )

        self.increment_version()
        return PurchaseOrderAggregate(
            aggregate_id=self.aggregate_id,
            legal_entity_id=self.legal_entity_id,
            purchase_orders=new_pos,
            goods_receipts=self.goods_receipts,
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
        )

    def update_purchase_order(
        self, po: PurchaseOrderEntity, updated_by: str
    ) -> PurchaseOrderAggregate:
        if self._is_locked:
            raise ValueError("Cannot update PO in locked aggregate")
        if po.po_id not in self.purchase_orders:
            raise ValueError(f"Purchase order {po.po_id} not found")

        new_pos = dict(self.purchase_orders)
        new_pos[po.po_id] = po

        self._record_audit("po_updated", {"po_id": str(po.po_id), "updated_by": updated_by})
        self.increment_version()
        return PurchaseOrderAggregate(
            aggregate_id=self.aggregate_id,
            legal_entity_id=self.legal_entity_id,
            purchase_orders=new_pos,
            goods_receipts=self.goods_receipts,
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
        )

    def approve_purchase_order(self, po_id: UUID, approved_by: str) -> PurchaseOrderAggregate:
        if self._is_locked:
            raise ValueError("Cannot approve PO in locked aggregate")
        po = self.purchase_orders.get(po_id)
        if not po:
            raise ValueError(f"Purchase order {po_id} not found")

        approved_po = po.approve(approved_by)
        new_pos = dict(self.purchase_orders)
        new_pos[po_id] = approved_po

        self._add_event(
            PurchaseOrderApprovedEvent(
                aggregate_id=self.aggregate_id,
                aggregate_version=self.version + 1,
                purchase_order=approved_po,
                approved_by=approved_by,
            )
        )

        self.increment_version()
        return PurchaseOrderAggregate(
            aggregate_id=self.aggregate_id,
            legal_entity_id=self.legal_entity_id,
            purchase_orders=new_pos,
            goods_receipts=self.goods_receipts,
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
        )

    def cancel_purchase_order(
        self, po_id: UUID, reason: str, cancelled_by: str
    ) -> PurchaseOrderAggregate:
        if self._is_locked:
            raise ValueError("Cannot cancel PO in locked aggregate")
        po = self.purchase_orders.get(po_id)
        if not po:
            raise ValueError(f"Purchase order {po_id} not found")

        cancelled_po = po.cancel(cancelled_by, reason)
        new_pos = dict(self.purchase_orders)
        new_pos[po_id] = cancelled_po

        self._record_audit(
            "po_cancelled", {"po_id": str(po_id), "reason": reason, "cancelled_by": cancelled_by}
        )
        self.increment_version()
        return PurchaseOrderAggregate(
            aggregate_id=self.aggregate_id,
            legal_entity_id=self.legal_entity_id,
            purchase_orders=new_pos,
            goods_receipts=self.goods_receipts,
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
        )

    def get_purchase_order(self, po_id: UUID) -> PurchaseOrderEntity | None:
        return self.purchase_orders.get(po_id)

    def get_purchase_order_by_number(self, po_number: str) -> PurchaseOrderEntity | None:
        for po in self.purchase_orders.values():
            if po.po_number == po_number:
                return po
        return None

    def get_open_purchase_orders(self) -> list[PurchaseOrderEntity]:
        return [
            po
            for po in self.purchase_orders.values()
            if po.status in (POStatus.APPROVED, POStatus.PARTIALLY_RECEIVED)
        ]

    def get_overdue_purchase_orders(
        self, as_of: datetime | None = None
    ) -> list[PurchaseOrderEntity]:
        as_of = as_of or datetime.now(UTC)
        return [po for po in self.purchase_orders.values() if po.is_overdue(as_of)]

    # ==================== GOODS RECEIPT MANAGEMENT ====================

    def add_goods_receipt(
        self, grn: GoodsReceiptNoteEntity, created_by: str
    ) -> PurchaseOrderAggregate:
        if self._is_locked:
            raise ValueError("Cannot add GRN to locked aggregate")
        if grn.po_id not in self.purchase_orders:
            raise ValueError(f"PO {grn.po_id} not found")

        po = self.purchase_orders[grn.po_id]

        # Validate receipt quantities
        for grn_item in grn.items:
            total_received = self.get_total_received_quantity(grn.po_id, grn_item.item_id)
            new_received = total_received + grn_item.quantity
            po_item = po.get_item(grn_item.item_id)
            if not po_item:
                raise ValueError(f"Item {grn_item.item_id} not found in PO {grn.po_id}")
            if new_received > po_item.quantity:
                raise ValueError(
                    f"Receipt quantity {new_received} exceeds PO quantity {po_item.quantity} for item {grn_item.item_code}"
                )

        # Update PO received quantities
        updated_po = po
        for grn_item in grn.items:
            updated_po = updated_po.update_received_quantity(
                grn_item.item_id, grn_item.quantity, created_by
            )

        updated_po = updated_po.receive()

        new_grns = dict(self.goods_receipts)
        new_grns[grn.grn_id] = grn
        new_pos = dict(self.purchase_orders)
        new_pos[grn.po_id] = updated_po

        self._add_event(
            GoodsReceiptCreatedEvent(
                aggregate_id=self.aggregate_id,
                aggregate_version=self.version + 1,
                grn=grn,
                created_by=created_by,
            )
        )

        self.increment_version()
        return PurchaseOrderAggregate(
            aggregate_id=self.aggregate_id,
            legal_entity_id=self.legal_entity_id,
            purchase_orders=new_pos,
            goods_receipts=new_grns,
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
        )

    def get_total_received_quantity(self, po_id: UUID, item_id: UUID) -> Decimal:
        total = Decimal(0)
        for grn in self.goods_receipts.values():
            if grn.po_id == po_id and grn.status == GRNStatus.CONFIRMED:
                for item in grn.items:
                    if item.item_id == item_id:
                        total += item.quantity
        return total

    def get_goods_receipt(self, grn_id: UUID) -> GoodsReceiptNoteEntity | None:
        return self.goods_receipts.get(grn_id)

    def get_grns_by_po(self, po_id: UUID) -> list[GoodsReceiptNoteEntity]:
        return [grn for grn in self.goods_receipts.values() if grn.po_id == po_id]

    def is_po_fully_received(self, po_id: UUID) -> bool:
        po = self.purchase_orders.get(po_id)
        if not po:
            return False
        return po.is_fully_received()

    def to_dict(self) -> dict[str, Any]:
        return {
            "aggregate_id": str(self.aggregate_id),
            "legal_entity_id": str(self.legal_entity_id),
            "total_pos": len(self.purchase_orders),
            "open_pos": len(self.get_open_purchase_orders()),
            "overdue_pos": len(self.get_overdue_purchase_orders()),
            "total_grns": len(self.goods_receipts),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version": self.version,
            "is_locked": self._is_locked,
        }

    @classmethod
    def create(cls, legal_entity_id: UUID, created_by: str) -> PurchaseOrderAggregate:
        return cls(
            aggregate_id=uuid4(),
            legal_entity_id=legal_entity_id,
            created_by=created_by,
        )


class PurchaseOrderRepository:
    async def get_by_legal_entity(self, legal_entity_id: UUID) -> PurchaseOrderAggregate | None:
        raise NotImplementedError

    async def get_by_id(
        self, aggregate_id: UUID, legal_entity_id: UUID
    ) -> PurchaseOrderAggregate | None:
        raise NotImplementedError

    async def save(self, aggregate: PurchaseOrderAggregate) -> None:
        raise NotImplementedError

    async def delete(self, aggregate_id: UUID, legal_entity_id: UUID) -> None:
        raise NotImplementedError


__all__ = [
    "PurchaseOrderAggregate",
    "PurchaseOrderRepository",
]
