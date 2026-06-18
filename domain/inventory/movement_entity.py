#!/usr/bin/env python3
"""
Module: movement_entity.py
Layer: 6 - Domain / Inventory
Responsibility: Mutasi persediaan (masuk/keluar).
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


class MovementType(Enum):
    """Tipe mutasi persediaan."""

    PURCHASE_RECEIPT = "purchase_receipt"
    PURCHASE_RETURN = "purchase_return"
    PRODUCTION_COMPLETION = "production_completion"
    PRODUCTION_ISSUE = "production_issue"
    TRANSFER_IN = "transfer_in"
    TRANSFER_OUT = "transfer_out"
    RETURN_FROM_CUSTOMER = "return_customer"
    RETURN_TO_SUPPLIER = "return_supplier"
    ADJUSTMENT_IN = "adjustment_in"
    ADJUSTMENT_OUT = "adjustment_out"
    INITIAL_STOCK = "initial_stock"
    SALES_ISSUE = "sales_issue"
    SALES_RETURN = "sales_return"
    DAMAGED = "damaged"
    EXPIRED = "expired"
    SAMPLE_ISSUE = "sample_issue"
    DONATION = "donation"
    WRITE_OFF = "write_off"

    def is_inbound(self) -> bool:
        """Check if movement is inbound."""
        return self in (
            MovementType.PURCHASE_RECEIPT,
            MovementType.PRODUCTION_COMPLETION,
            MovementType.TRANSFER_IN,
            MovementType.RETURN_FROM_CUSTOMER,
            MovementType.ADJUSTMENT_IN,
            MovementType.INITIAL_STOCK,
            MovementType.SALES_RETURN,
        )

    def is_outbound(self) -> bool:
        """Check if movement is outbound."""
        return not self.is_inbound()


class MovementStatus(Enum):
    """Status mutasi persediaan."""

    DRAFT = "draft"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    REVERSED = "reversed"
    PENDING = "pending"
    COMPLETED = "completed"


class MovementEntity:
    """Entitas mutasi persediaan."""

    def __init__(
        self,
        movement_id: UUID | None = None,
        id: UUID | None = None,
        movement_type: MovementType | None = None,
        movement_number: str = "",
        item_id: UUID | None = None,
        item_sku: str = "",
        item_name: str = "",
        warehouse_id: UUID | None = None,
        quantity: Decimal = Decimal(0),
        unit_cost: Decimal = Decimal(0),
        total_cost: Decimal = Decimal(0),
        movement_date: date | None = None,
        status: MovementStatus = MovementStatus.CONFIRMED,
        reference_document_type: str = "",
        reference_document_id: UUID | None = None,
        reference_document_number: str = "",
        created_by: str = "",
        created_at: datetime | None = None,
        description: str = "",
        source_warehouse_id: UUID | None = None,
        destination_warehouse_id: UUID | None = None,
        batch_number: str | None = None,
        expiry_date: date | None = None,
        updated_at: datetime | None = None,
        version: int = 1,
        legal_entity_id: UUID | None = None,
        warehouse_code: str | None = None,
        notes: str | None = None,
        reference_document_number_str: str | None = None,
        so_line_id: UUID | None = None,
        po_line_id: UUID | None = None,
        wo_line_id: UUID | None = None,
        **kwargs,
    ):
        final_id = id or movement_id
        self.movement_id = final_id or uuid4()
        self.movement_type = movement_type
        self.movement_number = movement_number
        self.item_id = item_id
        self.item_sku = item_sku
        self.item_name = item_name
        self.warehouse_id = warehouse_id
        self.quantity = quantity
        self.unit_cost = unit_cost
        self.total_cost = total_cost
        self.movement_date = movement_date or date.today()
        self.status = status
        self.reference_document_type = reference_document_type
        self.reference_document_id = reference_document_id
        self.reference_document_number = reference_document_number
        self.created_by = created_by
        self.created_at = created_at or datetime.now(UTC)
        self.description = description
        self.source_warehouse_id = source_warehouse_id
        self.destination_warehouse_id = destination_warehouse_id
        self.batch_number = batch_number
        self.expiry_date = expiry_date
        self.updated_at = updated_at or datetime.now(UTC)
        self.version = version
        self.legal_entity_id = legal_entity_id
        self.warehouse_code = warehouse_code
        self.notes = notes
        self.reference_document_number_str = reference_document_number_str
        self.so_line_id = so_line_id
        self.po_line_id = po_line_id
        self.wo_line_id = wo_line_id

        self._validate()

    def _validate(self) -> None:
        """Validate invariants."""
        if self.quantity <= 0:
            raise ValueError(f"Movement quantity must be positive: {self.quantity}")
        if self.unit_cost < 0:
            raise ValueError(f"Unit cost cannot be negative: {self.unit_cost}")
        if self.movement_type is None:
            raise ValueError("Movement type is required")

    @property
    def id(self) -> UUID:
        return self.movement_id

    @property
    def is_inbound(self) -> bool:
        return self.movement_type.is_inbound() if self.movement_type else False

    @property
    def is_outbound(self) -> bool:
        return self.movement_type.is_outbound() if self.movement_type else False

    # ==================== FACTORY METHODS ====================

    @classmethod
    def create_receipt(
        cls,
        item_id: UUID,
        item_sku: str,
        item_name: str,
        warehouse_id: UUID,
        quantity: Decimal,
        unit_cost: Decimal,
        movement_date: date,
        reference_document_type: str,
        reference_document_id: UUID,
        reference_document_number: str,
        created_by: str = "",
        description: str = "",
        batch_number: str | None = None,
        legal_entity_id: UUID | None = None,
        warehouse_code: str | None = None,
        po_line_id: UUID | None = None,
    ) -> MovementEntity:
        """Create a purchase receipt movement."""
        total_cost = quantity * unit_cost
        return cls(
            movement_id=uuid4(),
            movement_type=MovementType.PURCHASE_RECEIPT,
            movement_number=f"RCV-{reference_document_number}",
            item_id=item_id,
            item_sku=item_sku,
            item_name=item_name,
            warehouse_id=warehouse_id,
            quantity=quantity,
            unit_cost=unit_cost,
            total_cost=total_cost,
            movement_date=movement_date,
            status=MovementStatus.CONFIRMED,
            reference_document_type=reference_document_type,
            reference_document_id=reference_document_id,
            reference_document_number=reference_document_number,
            created_by=created_by,
            created_at=datetime.now(UTC),
            description=description,
            batch_number=batch_number,
            legal_entity_id=legal_entity_id,
            warehouse_code=warehouse_code,
            po_line_id=po_line_id,
        )

    @classmethod
    def create_issue(
        cls,
        item_id: UUID,
        item_sku: str,
        item_name: str,
        warehouse_id: UUID,
        quantity: Decimal,
        unit_cost: Decimal,
        movement_date: date,
        reference_document_type: str,
        reference_document_id: UUID,
        reference_document_number: str,
        created_by: str = "",
        description: str = "",
        legal_entity_id: UUID | None = None,
        warehouse_code: str | None = None,
        so_line_id: UUID | None = None,
    ) -> MovementEntity:
        """Create a sales issue movement."""
        total_cost = quantity * unit_cost
        return cls(
            movement_id=uuid4(),
            movement_type=MovementType.SALES_ISSUE,
            movement_number=f"ISS-{reference_document_number}",
            item_id=item_id,
            item_sku=item_sku,
            item_name=item_name,
            warehouse_id=warehouse_id,
            quantity=quantity,
            unit_cost=unit_cost,
            total_cost=total_cost,
            movement_date=movement_date,
            status=MovementStatus.CONFIRMED,
            reference_document_type=reference_document_type,
            reference_document_id=reference_document_id,
            reference_document_number=reference_document_number,
            created_by=created_by,
            created_at=datetime.now(UTC),
            description=description,
            legal_entity_id=legal_entity_id,
            warehouse_code=warehouse_code,
            so_line_id=so_line_id,
        )

    @classmethod
    def create_transfer(
        cls,
        item_id: UUID,
        item_sku: str,
        item_name: str,
        source_warehouse_id: UUID,
        destination_warehouse_id: UUID,
        quantity: Decimal,
        unit_cost: Decimal,
        movement_date: date,
        reference_document_number: str,
        created_by: str = "",
        description: str = "",
        legal_entity_id: UUID | None = None,
        source_warehouse_code: str | None = None,
        dest_warehouse_code: str | None = None,
    ) -> tuple[MovementEntity, MovementEntity]:
        """Create transfer movements (out and in)."""
        out_movement = cls(
            movement_id=uuid4(),
            movement_type=MovementType.TRANSFER_OUT,
            movement_number=f"TRF-{reference_document_number}-OUT",
            item_id=item_id,
            item_sku=item_sku,
            item_name=item_name,
            warehouse_id=source_warehouse_id,
            quantity=quantity,
            unit_cost=unit_cost,
            total_cost=quantity * unit_cost,
            movement_date=movement_date,
            status=MovementStatus.CONFIRMED,
            reference_document_type="TRANSFER",
            reference_document_id=uuid4(),
            reference_document_number=reference_document_number,
            created_by=created_by,
            created_at=datetime.now(UTC),
            description=description,
            destination_warehouse_id=destination_warehouse_id,
            legal_entity_id=legal_entity_id,
            warehouse_code=source_warehouse_code,
        )
        in_movement = cls(
            movement_id=uuid4(),
            movement_type=MovementType.TRANSFER_IN,
            movement_number=f"TRF-{reference_document_number}-IN",
            item_id=item_id,
            item_sku=item_sku,
            item_name=item_name,
            warehouse_id=destination_warehouse_id,
            quantity=quantity,
            unit_cost=unit_cost,
            total_cost=quantity * unit_cost,
            movement_date=movement_date,
            status=MovementStatus.CONFIRMED,
            reference_document_type="TRANSFER",
            reference_document_id=uuid4(),
            reference_document_number=reference_document_number,
            created_by=created_by,
            created_at=datetime.now(UTC),
            description=description,
            source_warehouse_id=source_warehouse_id,
            legal_entity_id=legal_entity_id,
            warehouse_code=dest_warehouse_code,
        )
        return out_movement, in_movement

    @classmethod
    def create_adjustment(
        cls,
        item_id: UUID,
        warehouse_id: UUID,
        quantity: Decimal,
        reason: str,
        created_by: str = "",
        unit_cost: Decimal = Decimal(0),
        legal_entity_id: UUID | None = None,
        warehouse_code: str | None = None,
    ) -> MovementEntity:
        """Create an adjustment movement."""
        movement_type = MovementType.ADJUSTMENT_IN if quantity > 0 else MovementType.ADJUSTMENT_OUT
        abs_qty = abs(quantity)
        total_cost = abs_qty * unit_cost
        return cls(
            movement_id=uuid4(),
            movement_type=movement_type,
            movement_number=f"ADJ-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
            item_id=item_id,
            item_sku="",
            item_name="",
            warehouse_id=warehouse_id,
            quantity=abs_qty,
            unit_cost=unit_cost,
            total_cost=total_cost,
            movement_date=date.today(),
            status=MovementStatus.CONFIRMED,
            reference_document_type="ADJUSTMENT",
            reference_document_id=uuid4(),
            reference_document_number=f"ADJ-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
            created_by=created_by,
            created_at=datetime.now(UTC),
            description=reason,
            legal_entity_id=legal_entity_id,
            warehouse_code=warehouse_code,
            notes=reason,
        )

    @classmethod
    def create_production_issue(
        cls,
        item_id: UUID,
        item_sku: str,
        item_name: str,
        warehouse_id: UUID,
        quantity: Decimal,
        unit_cost: Decimal,
        movement_date: date,
        work_order_id: UUID,
        work_order_number: str,
        created_by: str = "",
        legal_entity_id: UUID | None = None,
    ) -> MovementEntity:
        """Create a production issue movement."""
        total_cost = quantity * unit_cost
        return cls(
            movement_id=uuid4(),
            movement_type=MovementType.PRODUCTION_ISSUE,
            movement_number=f"PROD-{work_order_number}-ISS",
            item_id=item_id,
            item_sku=item_sku,
            item_name=item_name,
            warehouse_id=warehouse_id,
            quantity=quantity,
            unit_cost=unit_cost,
            total_cost=total_cost,
            movement_date=movement_date,
            status=MovementStatus.CONFIRMED,
            reference_document_type="WORK_ORDER",
            reference_document_id=work_order_id,
            reference_document_number=work_order_number,
            created_by=created_by,
            created_at=datetime.now(UTC),
            description=f"Production issue for WO {work_order_number}",
            legal_entity_id=legal_entity_id,
            wo_line_id=work_order_id,
        )

    @classmethod
    def create_production_completion(
        cls,
        item_id: UUID,
        item_sku: str,
        item_name: str,
        warehouse_id: UUID,
        quantity: Decimal,
        unit_cost: Decimal,
        movement_date: date,
        work_order_id: UUID,
        work_order_number: str,
        created_by: str = "",
        legal_entity_id: UUID | None = None,
    ) -> MovementEntity:
        """Create a production completion movement."""
        total_cost = quantity * unit_cost
        return cls(
            movement_id=uuid4(),
            movement_type=MovementType.PRODUCTION_COMPLETION,
            movement_number=f"PROD-{work_order_number}-CMP",
            item_id=item_id,
            item_sku=item_sku,
            item_name=item_name,
            warehouse_id=warehouse_id,
            quantity=quantity,
            unit_cost=unit_cost,
            total_cost=total_cost,
            movement_date=movement_date,
            status=MovementStatus.CONFIRMED,
            reference_document_type="WORK_ORDER",
            reference_document_id=work_order_id,
            reference_document_number=work_order_number,
            created_by=created_by,
            created_at=datetime.now(UTC),
            description=f"Production completion for WO {work_order_number}",
            legal_entity_id=legal_entity_id,
            wo_line_id=work_order_id,
        )

    @classmethod
    def create_return_to_supplier(
        cls,
        item_id: UUID,
        item_sku: str,
        item_name: str,
        warehouse_id: UUID,
        quantity: Decimal,
        unit_cost: Decimal,
        movement_date: date,
        purchase_order_id: UUID,
        purchase_order_number: str,
        created_by: str = "",
        legal_entity_id: UUID | None = None,
    ) -> MovementEntity:
        """Create a return to supplier movement."""
        total_cost = quantity * unit_cost
        return cls(
            movement_id=uuid4(),
            movement_type=MovementType.RETURN_TO_SUPPLIER,
            movement_number=f"RTS-{purchase_order_number}",
            item_id=item_id,
            item_sku=item_sku,
            item_name=item_name,
            warehouse_id=warehouse_id,
            quantity=quantity,
            unit_cost=unit_cost,
            total_cost=total_cost,
            movement_date=movement_date,
            status=MovementStatus.CONFIRMED,
            reference_document_type="PURCHASE_ORDER",
            reference_document_id=purchase_order_id,
            reference_document_number=purchase_order_number,
            created_by=created_by,
            created_at=datetime.now(UTC),
            description=f"Return to supplier for PO {purchase_order_number}",
            legal_entity_id=legal_entity_id,
            po_line_id=purchase_order_id,
        )

    @classmethod
    def create_sales_return(
        cls,
        item_id: UUID,
        item_sku: str,
        item_name: str,
        warehouse_id: UUID,
        quantity: Decimal,
        unit_cost: Decimal,
        movement_date: date,
        sales_order_id: UUID,
        sales_order_number: str,
        created_by: str = "",
        legal_entity_id: UUID | None = None,
    ) -> MovementEntity:
        """Create a sales return movement."""
        total_cost = quantity * unit_cost
        return cls(
            movement_id=uuid4(),
            movement_type=MovementType.SALES_RETURN,
            movement_number=f"SR-{sales_order_number}",
            item_id=item_id,
            item_sku=item_sku,
            item_name=item_name,
            warehouse_id=warehouse_id,
            quantity=quantity,
            unit_cost=unit_cost,
            total_cost=total_cost,
            movement_date=movement_date,
            status=MovementStatus.CONFIRMED,
            reference_document_type="SALES_ORDER",
            reference_document_id=sales_order_id,
            reference_document_number=sales_order_number,
            created_by=created_by,
            created_at=datetime.now(UTC),
            description=f"Sales return for SO {sales_order_number}",
            legal_entity_id=legal_entity_id,
            so_line_id=sales_order_id,
        )

    # ==================== BUSINESS METHODS ====================

    def confirm(self, confirmed_by: str) -> MovementEntity:
        """Confirm the movement."""
        if self.status != MovementStatus.DRAFT:
            raise ValueError(f"Cannot confirm movement in status {self.status.value}")
        return MovementEntity(
            movement_id=self.movement_id,
            movement_type=self.movement_type,
            movement_number=self.movement_number,
            item_id=self.item_id,
            item_sku=self.item_sku,
            item_name=self.item_name,
            warehouse_id=self.warehouse_id,
            quantity=self.quantity,
            unit_cost=self.unit_cost,
            total_cost=self.total_cost,
            movement_date=self.movement_date,
            status=MovementStatus.CONFIRMED,
            reference_document_type=self.reference_document_type,
            reference_document_id=self.reference_document_id,
            reference_document_number=self.reference_document_number,
            created_by=self.created_by,
            created_at=self.created_at,
            description=self.description,
            source_warehouse_id=self.source_warehouse_id,
            destination_warehouse_id=self.destination_warehouse_id,
            batch_number=self.batch_number,
            expiry_date=self.expiry_date,
            updated_at=datetime.now(UTC),
            version=self.version + 1,
            legal_entity_id=self.legal_entity_id,
            warehouse_code=self.warehouse_code,
            notes=self.notes,
            so_line_id=self.so_line_id,
            po_line_id=self.po_line_id,
            wo_line_id=self.wo_line_id,
        )

    def cancel(self, cancelled_by: str, reason: str) -> MovementEntity:
        """Cancel the movement."""
        if self.status not in (MovementStatus.DRAFT, MovementStatus.CONFIRMED):
            raise ValueError(f"Cannot cancel movement in status {self.status.value}")
        return MovementEntity(
            movement_id=self.movement_id,
            movement_type=self.movement_type,
            movement_number=self.movement_number,
            item_id=self.item_id,
            item_sku=self.item_sku,
            item_name=self.item_name,
            warehouse_id=self.warehouse_id,
            quantity=self.quantity,
            unit_cost=self.unit_cost,
            total_cost=self.total_cost,
            movement_date=self.movement_date,
            status=MovementStatus.CANCELLED,
            reference_document_type=self.reference_document_type,
            reference_document_id=self.reference_document_id,
            reference_document_number=self.reference_document_number,
            created_by=self.created_by,
            created_at=self.created_at,
            description=f"{self.description}\nCancelled: {reason} by {cancelled_by}",
            source_warehouse_id=self.source_warehouse_id,
            destination_warehouse_id=self.destination_warehouse_id,
            batch_number=self.batch_number,
            expiry_date=self.expiry_date,
            updated_at=datetime.now(UTC),
            version=self.version + 1,
            legal_entity_id=self.legal_entity_id,
            warehouse_code=self.warehouse_code,
            notes=f"{self.notes}\nCancelled: {reason}" if self.notes else f"Cancelled: {reason}",
            so_line_id=self.so_line_id,
            po_line_id=self.po_line_id,
            wo_line_id=self.wo_line_id,
        )

    def reverse(self, reversed_by: str, reason: str) -> MovementEntity:
        """Reverse the movement (create opposite movement)."""
        if self.status != MovementStatus.CONFIRMED:
            raise ValueError(f"Cannot reverse movement in status {self.status.value}")
        # Create reversal movement
        reversal_type = (
            MovementType.PURCHASE_RETURN
            if self.movement_type == MovementType.PURCHASE_RECEIPT
            else MovementType.SALES_RETURN
            if self.movement_type == MovementType.SALES_ISSUE
            else self.movement_type
        )
        return MovementEntity(
            movement_id=uuid4(),
            movement_type=reversal_type,
            movement_number=f"REV-{self.movement_number}",
            item_id=self.item_id,
            item_sku=self.item_sku,
            item_name=self.item_name,
            warehouse_id=self.warehouse_id,
            quantity=self.quantity,
            unit_cost=self.unit_cost,
            total_cost=self.total_cost,
            movement_date=date.today(),
            status=MovementStatus.CONFIRMED,
            reference_document_type="REVERSAL",
            reference_document_id=self.movement_id,
            reference_document_number=self.movement_number,
            created_by=reversed_by,
            created_at=datetime.now(UTC),
            description=f"Reversal of {self.movement_number}: {reason}",
            source_warehouse_id=self.destination_warehouse_id,
            destination_warehouse_id=self.source_warehouse_id,
            batch_number=self.batch_number,
            expiry_date=self.expiry_date,
            version=1,
            legal_entity_id=self.legal_entity_id,
            warehouse_code=self.warehouse_code,
            notes=reason,
        )

    # ==================== DICTIONARY METHODS ====================

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "movement_id": str(self.movement_id),
            "movement_type": self.movement_type.value if self.movement_type else None,
            "movement_number": self.movement_number,
            "item_id": str(self.item_id),
            "item_sku": self.item_sku,
            "item_name": self.item_name,
            "warehouse_id": str(self.warehouse_id) if self.warehouse_id else None,
            "quantity": str(self.quantity),
            "unit_cost": str(self.unit_cost),
            "total_cost": str(self.total_cost),
            "movement_date": self.movement_date.isoformat(),
            "status": self.status.value,
            "reference_document_type": self.reference_document_type,
            "reference_document_id": str(self.reference_document_id)
            if self.reference_document_id
            else None,
            "reference_document_number": self.reference_document_number,
            "description": self.description,
            "created_at": self.created_at.isoformat(),
            "version": self.version,
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else None,
            "warehouse_code": self.warehouse_code,
            "notes": self.notes,
            "batch_number": self.batch_number,
            "expiry_date": self.expiry_date.isoformat() if self.expiry_date else None,
            "source_warehouse_id": str(self.source_warehouse_id)
            if self.source_warehouse_id
            else None,
            "destination_warehouse_id": str(self.destination_warehouse_id)
            if self.destination_warehouse_id
            else None,
            "so_line_id": str(self.so_line_id) if self.so_line_id else None,
            "po_line_id": str(self.po_line_id) if self.po_line_id else None,
            "wo_line_id": str(self.wo_line_id) if self.wo_line_id else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MovementEntity:
        """Create from dictionary."""
        return cls(
            movement_id=UUID(data["movement_id"]) if data.get("movement_id") else None,
            movement_type=MovementType(data["movement_type"])
            if data.get("movement_type")
            else None,
            movement_number=data.get("movement_number", ""),
            item_id=UUID(data["item_id"]) if data.get("item_id") else None,
            item_sku=data.get("item_sku", ""),
            item_name=data.get("item_name", ""),
            warehouse_id=UUID(data["warehouse_id"]) if data.get("warehouse_id") else None,
            quantity=Decimal(data["quantity"]) if data.get("quantity") else Decimal(0),
            unit_cost=Decimal(data["unit_cost"]) if data.get("unit_cost") else Decimal(0),
            total_cost=Decimal(data["total_cost"]) if data.get("total_cost") else Decimal(0),
            movement_date=date.fromisoformat(data["movement_date"])
            if data.get("movement_date")
            else date.today(),
            status=MovementStatus(data["status"])
            if data.get("status")
            else MovementStatus.CONFIRMED,
            reference_document_type=data.get("reference_document_type", ""),
            reference_document_id=UUID(data["reference_document_id"])
            if data.get("reference_document_id")
            else None,
            reference_document_number=data.get("reference_document_number", ""),
            created_by=data.get("created_by", ""),
            created_at=datetime.fromisoformat(data["created_at"])
            if data.get("created_at")
            else datetime.now(UTC),
            description=data.get("description", ""),
            source_warehouse_id=UUID(data["source_warehouse_id"])
            if data.get("source_warehouse_id")
            else None,
            destination_warehouse_id=UUID(data["destination_warehouse_id"])
            if data.get("destination_warehouse_id")
            else None,
            batch_number=data.get("batch_number"),
            expiry_date=date.fromisoformat(data["expiry_date"])
            if data.get("expiry_date")
            else None,
            updated_at=datetime.now(UTC),
            version=data.get("version", 1),
            legal_entity_id=UUID(data["legal_entity_id"]) if data.get("legal_entity_id") else None,
            warehouse_code=data.get("warehouse_code"),
            notes=data.get("notes"),
            so_line_id=UUID(data["so_line_id"]) if data.get("so_line_id") else None,
            po_line_id=UUID(data["po_line_id"]) if data.get("po_line_id") else None,
            wo_line_id=UUID(data["wo_line_id"]) if data.get("wo_line_id") else None,
        )


# ==================== ALIAS ====================

StockMovement = MovementEntity


# ==================== REPOSITORY PROTOCOL ====================


class MovementRepository:
    """Repository protocol for MovementEntity."""

    async def get_by_id(self, movement_id: UUID, legal_entity_id: UUID) -> MovementEntity | None:
        raise NotImplementedError

    async def get_by_item(
        self,
        item_id: UUID,
        legal_entity_id: UUID,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[MovementEntity]:
        raise NotImplementedError

    async def get_by_reference(
        self,
        reference_document_type: str,
        reference_document_id: UUID,
        legal_entity_id: UUID,
    ) -> list[MovementEntity]:
        raise NotImplementedError

    async def get_by_warehouse(
        self,
        warehouse_id: UUID,
        legal_entity_id: UUID,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[MovementEntity]:
        raise NotImplementedError

    async def get_by_batch(
        self,
        batch_number: str,
        legal_entity_id: UUID,
    ) -> list[MovementEntity]:
        raise NotImplementedError

    async def save(self, movement: MovementEntity, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    async def delete(self, movement_id: UUID, legal_entity_id: UUID) -> None:
        raise NotImplementedError


__all__ = [
    "MovementEntity",
    "MovementRepository",
    "MovementStatus",
    "MovementType",
    "StockMovement",
]
