#!/usr/bin/env python3

"""
Module: procurement_saga_state.py

Layer: 8 - Application / Sagas

Responsibility:
    Definisi state (data context) untuk procurement saga.
    Menyimpan informasi PO, GRN, invoice, payment, dll.

Dependencies:
    - dataclasses, uuid, datetime, decimal
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4


@dataclass(kw_only=True)
class ProcurementSagaState:
    """
    State context for procurement saga.
    Immutable state machine data (though typically mutated in saga execution).
    """

    saga_id: UUID
    legal_entity_id: UUID
    vendor_id: UUID
    items: list[dict[str, Any]]
    user_id: UUID | None
    correlation_id: str | None

    # PO related
    po_id: UUID | None = None
    po_number: str | None = None

    # GRN related
    grn_id: UUID | None = None
    grn_number: str | None = None

    # Invoice related
    invoice_id: UUID | None = None
    invoice_number: str | None = None

    # Payment related
    payment_id: UUID | None = None
    payment_number: str | None = None

    # Inventory
    inventory_movement_ids: list[UUID] = field(default_factory=list)

    # Financial
    total_amount: Decimal = Decimal("0")

    # Saga lifecycle
    status: str = "INITIATED"  # INITIATED, PO_CREATED, GRN_CREATED, INVOICE_CREATED, PAYMENT_CREATED, COMPLETED, FAILED
    errors: list[str] = field(default_factory=list)

    # Timestamps
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        """Validate invariant rules."""
        if not self.items:
            raise ValueError("Items list cannot be empty")
        if self.total_amount < 0:
            raise ValueError("Total amount cannot be negative")
        if self.status not in {
            "INITIATED",
            "PO_CREATED",
            "GRN_CREATED",
            "INVOICE_CREATED",
            "PAYMENT_CREATED",
            "COMPLETED",
            "FAILED",
        }:
            raise ValueError(f"Invalid status: {self.status}")

    # -------------------------------------------------------------------------
    # State mutation helpers (return a new instance for immutability)
    # -------------------------------------------------------------------------

    def _copy_and_update(self, **kwargs) -> ProcurementSagaState:
        """Create a new instance with updated fields."""
        return ProcurementSagaState(
            saga_id=self.saga_id,
            legal_entity_id=self.legal_entity_id,
            vendor_id=self.vendor_id,
            items=self.items.copy(),
            user_id=self.user_id,
            correlation_id=self.correlation_id,
            po_id=kwargs.get("po_id", self.po_id),
            po_number=kwargs.get("po_number", self.po_number),
            grn_id=kwargs.get("grn_id", self.grn_id),
            grn_number=kwargs.get("grn_number", self.grn_number),
            invoice_id=kwargs.get("invoice_id", self.invoice_id),
            invoice_number=kwargs.get("invoice_number", self.invoice_number),
            payment_id=kwargs.get("payment_id", self.payment_id),
            payment_number=kwargs.get("payment_number", self.payment_number),
            inventory_movement_ids=kwargs.get(
                "inventory_movement_ids", self.inventory_movement_ids.copy()
            ),
            total_amount=kwargs.get("total_amount", self.total_amount),
            status=kwargs.get("status", self.status),
            errors=kwargs.get("errors", self.errors.copy()),
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
        )

    def update_status(self, new_status: str) -> ProcurementSagaState:
        """Transition to a new status."""
        valid_transitions = {
            "INITIATED": ["PO_CREATED", "FAILED"],
            "PO_CREATED": ["GRN_CREATED", "FAILED"],
            "GRN_CREATED": ["INVOICE_CREATED", "FAILED"],
            "INVOICE_CREATED": ["PAYMENT_CREATED", "FAILED"],
            "PAYMENT_CREATED": ["COMPLETED", "FAILED"],
            "COMPLETED": [],
            "FAILED": [],
        }
        allowed = valid_transitions.get(self.status, [])
        if new_status not in allowed:
            raise ValueError(f"Cannot transition from {self.status} to {new_status}")
        return self._copy_and_update(status=new_status)

    def add_error(self, error_message: str) -> ProcurementSagaState:
        """Add an error message and optionally set status to FAILED."""
        new_errors = self.errors + [error_message]
        new_status = "FAILED" if self.status != "COMPLETED" else self.status
        return self._copy_and_update(errors=new_errors, status=new_status)

    def mark_completed(self) -> ProcurementSagaState:
        """Mark saga as completed."""
        if self.status == "FAILED":
            raise ValueError("Cannot complete a failed saga")
        return self.update_status("COMPLETED")

    def mark_failed(self, error_message: str) -> ProcurementSagaState:
        """Mark saga as failed with an error."""
        return self.add_error(error_message)

    def set_po(self, po_id: UUID, po_number: str) -> ProcurementSagaState:
        """Record PO creation."""
        return self._copy_and_update(po_id=po_id, po_number=po_number).update_status("PO_CREATED")

    def set_grn(self, grn_id: UUID, grn_number: str) -> ProcurementSagaState:
        """Record GRN creation."""
        return self._copy_and_update(grn_id=grn_id, grn_number=grn_number).update_status(
            "GRN_CREATED"
        )

    def set_invoice(self, invoice_id: UUID, invoice_number: str) -> ProcurementSagaState:
        """Record invoice creation."""
        return self._copy_and_update(
            invoice_id=invoice_id, invoice_number=invoice_number
        ).update_status("INVOICE_CREATED")

    def set_payment(self, payment_id: UUID, payment_number: str) -> ProcurementSagaState:
        """Record payment creation."""
        return self._copy_and_update(
            payment_id=payment_id, payment_number=payment_number
        ).update_status("PAYMENT_CREATED")

    def add_inventory_movement(self, movement_id: UUID) -> ProcurementSagaState:
        """Add an inventory movement ID."""
        new_movements = self.inventory_movement_ids + [movement_id]
        return self._copy_and_update(inventory_movement_ids=new_movements)

    # -------------------------------------------------------------------------
    # Serialization
    # -------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Convert state to dictionary for persistence."""
        return {
            "saga_id": str(self.saga_id),
            "legal_entity_id": str(self.legal_entity_id),
            "vendor_id": str(self.vendor_id),
            "items": self.items,
            "user_id": str(self.user_id) if self.user_id else None,
            "correlation_id": self.correlation_id,
            "po_id": str(self.po_id) if self.po_id else None,
            "po_number": self.po_number,
            "grn_id": str(self.grn_id) if self.grn_id else None,
            "grn_number": self.grn_number,
            "invoice_id": str(self.invoice_id) if self.invoice_id else None,
            "invoice_number": self.invoice_number,
            "payment_id": str(self.payment_id) if self.payment_id else None,
            "payment_number": self.payment_number,
            "inventory_movement_ids": [str(mid) for mid in self.inventory_movement_ids],
            "total_amount": str(self.total_amount),  # Decimal to string for JSON
            "status": self.status,
            "errors": self.errors,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProcurementSagaState:
        """Reconstruct state from dictionary."""
        return cls(
            saga_id=UUID(data["saga_id"]),
            legal_entity_id=UUID(data["legal_entity_id"]),
            vendor_id=UUID(data["vendor_id"]),
            items=data["items"],
            user_id=UUID(data["user_id"]) if data.get("user_id") else None,
            correlation_id=data.get("correlation_id"),
            po_id=UUID(data["po_id"]) if data.get("po_id") else None,
            po_number=data.get("po_number"),
            grn_id=UUID(data["grn_id"]) if data.get("grn_id") else None,
            grn_number=data.get("grn_number"),
            invoice_id=UUID(data["invoice_id"]) if data.get("invoice_id") else None,
            invoice_number=data.get("invoice_number"),
            payment_id=UUID(data["payment_id"]) if data.get("payment_id") else None,
            payment_number=data.get("payment_number"),
            inventory_movement_ids=[UUID(mid) for mid in data.get("inventory_movement_ids", [])],
            total_amount=Decimal(str(data.get("total_amount", 0))),
            status=data.get("status", "INITIATED"),
            errors=data.get("errors", []),
            created_at=datetime.fromisoformat(data["created_at"])
            if isinstance(data["created_at"], str)
            else data["created_at"],
            updated_at=datetime.fromisoformat(data["updated_at"])
            if isinstance(data["updated_at"], str)
            else data["updated_at"],
        )


# -----------------------------------------------------------------------------
# Factory
# -----------------------------------------------------------------------------


def create_procurement_saga_state(
    legal_entity_id: UUID,
    vendor_id: UUID,
    items: list[dict[str, Any]],
    user_id: UUID | None = None,
    correlation_id: str | None = None,
    total_amount: Decimal | None = None,
) -> ProcurementSagaState:
    """Factory to create a new procurement saga state with generated saga_id."""
    if total_amount is None:
        # Calculate total amount from items if not provided
        total = Decimal("0")
        for item in items:
            qty = Decimal(str(item.get("quantity", 0)))
            price = Decimal(str(item.get("unit_price", 0)))
            total += qty * price
        total_amount = total

    return ProcurementSagaState(
        saga_id=uuid4(),
        legal_entity_id=legal_entity_id,
        vendor_id=vendor_id,
        items=items,
        user_id=user_id,
        correlation_id=correlation_id,
        total_amount=total_amount,
        status="INITIATED",
    )


__all__ = ["ProcurementSagaState", "create_procurement_saga_state"]
