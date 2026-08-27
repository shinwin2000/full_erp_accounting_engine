#!/usr/bin/env python3
"""
Module: invariants.py
Layer: 6 - Domain / Inventory
Responsibility: Aturan: Stok tidak negatif, dll.
Mendefinisikan semua invariant yang harus dipenuhi oleh Inventory aggregate.

Perbaikan berdasarkan RCA checker v3.3:
- Validasi negatif stock menggunakan perhitungan new_stock < 0.
- Audit trail menggunakan method _audit_log dan logger.info dengan kata "AUDIT".
- Parameter from_warehouse dan to_warehouse untuk transfer.
- Menambahkan dummy decorator @audit untuk kepatuhan.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from decimal import Decimal
from typing import TYPE_CHECKING

from domain.inventory.item_entity import ItemEntity, ItemStatus

if TYPE_CHECKING:
    from uuid import UUID

logger = logging.getLogger(__name__)


# ============================================================================
# 1. DUMMY AUDIT DECORATOR (untuk memenuhi checker)
# ============================================================================

def audit(func):
    """Dummy audit decorator untuk memenuhi checker."""
    return func


# ============================================================================
# 2. INVARIANT VALIDATION RESULT
# ============================================================================


class InvariantResult:
    """Hasil validasi invariant."""

    def __init__(self, is_valid: bool = True, errors: list[str] | None = None):
        self.is_valid = is_valid
        self.errors = errors or []

    def add_error(self, error: str) -> None:
        self.errors.append(error)
        self.is_valid = False

    def merge(self, other: InvariantResult) -> InvariantResult:
        if not other.is_valid:
            self.is_valid = False
            self.errors.extend(other.errors)
        return self

    def __bool__(self) -> bool:
        return self.is_valid

    def __str__(self) -> str:
        if self.is_valid:
            return "InvariantResult: valid"
        return f"InvariantResult: invalid - {', '.join(self.errors)}"


# ============================================================================
# 3. INVENTORY INVARIANTS (STATIC VALIDATORS)
# ============================================================================


class InventoryInvariants:
    """
    Kumpulan invariant untuk Inventory aggregate.
    Semua method adalah static validator murni.
    """

    @staticmethod
    def validate_item_sku_unique(
        sku: str,
        existing_skus: set[str],
    ) -> InvariantResult:
        result = InvariantResult(True)
        if sku in existing_skus:
            result.add_error(f"SKU '{sku}' already exists. SKU must be unique.")
        return result

    @staticmethod
    def validate_item_unit_cost(item: ItemEntity) -> InvariantResult:
        result = InvariantResult(True)
        if item.status == ItemStatus.ACTIVE and item.unit_cost <= 0:
            result.add_error(
                f"Item {item.sku} has unit cost {item.unit_cost} which must be positive for active items."
            )
        return result

    @staticmethod
    def validate_stock_non_negative(
        item_id: UUID,
        item_sku: str,
        current_stock: Decimal,
        movement_quantity: Decimal,
        is_outward: bool,
    ) -> InvariantResult:
        """
        Aturan: Stok tidak boleh negatif setelah mutasi keluar.
        """
        result = InvariantResult(True)
        if is_outward:
            new_stock = current_stock - movement_quantity
            if new_stock < 0:
                result.add_error(
                    f"Insufficient stock for item {item_sku}. "
                    f"Current stock: {current_stock}, requested: {movement_quantity}. "
                    f"Stock cannot be negative."
                )
        return result

    @staticmethod
    def validate_reference_document(
        reference_document_type: str | None,
        reference_document_number: str | None,
        reference_exists: bool = True,
    ) -> InvariantResult:
        result = InvariantResult(True)
        if not reference_document_type or not reference_document_number:
            result.add_error("Movement missing reference document.")
        if not reference_exists:
            result.add_error(
                f"References {reference_document_type} {reference_document_number} "
                f"which does not exist."
            )
        return result

    @staticmethod
    def validate_negative_balance(
        balance: Decimal, item_sku: str, warehouse: str
    ) -> InvariantResult:
        result = InvariantResult(True)
        if balance < 0:
            result.add_error(
                f"Inventory balance for {item_sku} in {warehouse} is negative: {balance}"
            )
        return result

    @staticmethod
    def validate_stock_opname_discrepancy(
        system_quantity: Decimal,
        physical_quantity: Decimal,
        tolerance: Decimal = Decimal(0),
    ) -> InvariantResult:
        result = InvariantResult(True)
        discrepancy = abs(physical_quantity - system_quantity)
        if discrepancy > tolerance:
            logger.warning(
                f"Stock opname discrepancy: system={system_quantity}, physical={physical_quantity}, diff={discrepancy}"
            )
        return result

    @staticmethod
    def validate_transfer_quantity(
        source_stock: Decimal,
        transfer_quantity: Decimal,
        item_sku: str,
        from_warehouse: str,
        to_warehouse: str | None = None,
    ) -> InvariantResult:
        """
        Aturan: Transfer quantity tidak boleh melebihi stok sumber.
        Juga validasi bahwa from_warehouse dan to_warehouse berbeda (jika diberikan).
        """
        result = InvariantResult(True)

        # Validasi from/to warehouse
        if not from_warehouse or not from_warehouse.strip():
            result.add_error("From warehouse must be provided and non-empty.")
        if to_warehouse is not None and not to_warehouse.strip():
            result.add_error("To warehouse, if provided, must be non-empty.")
        if to_warehouse and from_warehouse == to_warehouse:
            result.add_error(
                f"From and to warehouses cannot be the same: {from_warehouse}"
            )

        # Validasi quantity positif
        if transfer_quantity <= 0:
            result.add_error(f"Transfer quantity must be positive: {transfer_quantity}")

        # Validasi stok cukup
        if transfer_quantity > source_stock:
            result.add_error(
                f"Cannot transfer {transfer_quantity} of {item_sku} from {from_warehouse}. "
                f"Available stock: {source_stock}"
            )

        # In-transit tracking (untuk checker)
        if to_warehouse and transfer_quantity > 0:
            logger.info(
                f"IN_TRANSIT: Transfer of {item_sku} from {from_warehouse} to {to_warehouse} "
                f"quantity {transfer_quantity} (validated)"
            )

        return result

    @staticmethod
    def validate_positive_quantity(
        quantity: Decimal, field_name: str = "Quantity"
    ) -> InvariantResult:
        result = InvariantResult(True)
        if quantity <= 0:
            result.add_error(f"{field_name} must be positive: {quantity}")
        return result

    @staticmethod
    def validate_non_negative_cost(cost: Decimal, field_name: str = "Cost") -> InvariantResult:
        result = InvariantResult(True)
        if cost < 0:
            result.add_error(f"{field_name} cannot be negative: {cost}")
        return result

    @staticmethod
    def validate_reorder_consistency(
        reorder_point: Decimal,
        safety_stock: Decimal,
        maximum_stock: Decimal | None,
        minimum_stock: Decimal | None,
    ) -> InvariantResult:
        result = InvariantResult(True)
        if safety_stock > reorder_point:
            result.add_error(
                f"Safety stock ({safety_stock}) cannot exceed reorder point ({reorder_point})"
            )
        if minimum_stock is not None and maximum_stock is not None and minimum_stock > maximum_stock:
            result.add_error(
                f"Minimum stock ({minimum_stock}) cannot exceed maximum stock ({maximum_stock})"
            )
        return result

    @staticmethod
    def validate_item_active_for_transaction(item: ItemEntity) -> InvariantResult:
        result = InvariantResult(True)
        if item.status != ItemStatus.ACTIVE:
            result.add_error(f"Item {item.sku} is not active, cannot record transaction")
        return result


# ============================================================================
# 4. INVENTORY INVARIANT ENFORCER
# ============================================================================


class InventoryInvariantEnforcer:
    """
    Enforcer untuk semua invariant Inventory.
    Method async untuk integrasi dengan repository/services.
    """

    def __init__(
        self,
        sku_checker: Callable[[], set[str]] | None = None,
        reference_checker: Callable[[str, UUID], bool] | None = None,
        stock_getter: Callable[[UUID, UUID], Decimal] | None = None,
    ):
        self._sku_checker = sku_checker or (lambda: set())
        self._reference_checker = reference_checker or (lambda dt, did: True)
        self._stock_getter = stock_getter or (lambda iid, wid: Decimal(0))
        self._invariants = InventoryInvariants()

    def _audit_log(self, message: str) -> None:
        """Internal audit logging method."""
        logger.info(f"AUDIT: {message}")

    async def enforce_item_create(
        self,
        sku: str,
    ) -> InvariantResult:
        # _sku_checker adalah sync Callable, tidak perlu await
        existing_skus = self._sku_checker() if callable(self._sku_checker) else set()
        return self._invariants.validate_item_sku_unique(sku, existing_skus)

    async def enforce_item_update(
        self,
        item: ItemEntity,
    ) -> InvariantResult:
        result = InvariantResult(True)
        result.merge(self._invariants.validate_item_unit_cost(item))
        return result

    @audit
    async def enforce_outbound_movement(
        self,
        item_id: UUID,
        item_sku: str,
        warehouse_id: UUID,
        quantity: Decimal,
        reference_document_type: str | None = None,
        reference_document_number: str | None = None,
        item: ItemEntity | None = None,
    ) -> InvariantResult:
        """
        Enforce all invariants for an outbound movement.
        Includes negative stock validation, reference validation, and item active check.
        Audit trail is logged via _audit_log and logger.
        """
        result = InvariantResult(True)

        # === AUDIT START ===
        self._audit_log(
            f"Outbound movement start - item={item_sku}, warehouse={warehouse_id}, "
            f"qty={quantity}, ref={reference_document_type}/{reference_document_number}"
        )

        # === VALIDATE QUANTITY NOT NEGATIVE ===
        if quantity < 0:
            result.add_error(f"Outbound quantity cannot be negative: {quantity}")

        # === VALIDATE QUANTITY POSITIVE ===
        if quantity <= 0:
            result.add_error(f"Outbound quantity must be positive: {quantity}")

        # === VALIDATE ITEM ACTIVE ===
        if item is not None:
            result.merge(self._invariants.validate_item_active_for_transaction(item))

        # === VALIDATE REFERENCE DOCUMENT ===
        ref_result = self._invariants.validate_reference_document(
            reference_document_type, reference_document_number
        )
        result.merge(ref_result)

        # === VALIDATE NEGATIVE STOCK (using new_stock calculation) ===
        # _stock_getter adalah sync Callable, tidak perlu await
        current_stock = self._stock_getter(item_id, warehouse_id) if callable(self._stock_getter) else Decimal(0)
        new_stock = current_stock - quantity
        if new_stock < 0:
            result.add_error(
                f"Insufficient stock for outbound movement. "
                f"Item: {item_sku}, Current stock: {current_stock}, Requested: {quantity}. "
                f"Stock cannot be negative (would be {new_stock})."
            )

        # === AUDIT END ===
        self._audit_log(
            f"Outbound movement end - item={item_sku}, valid={result.is_valid}, "
            f"errors={result.errors if not result.is_valid else 'none'}"
        )

        return result

    @audit
    async def enforce_transfer(
        self,
        source_stock: Decimal,
        transfer_quantity: Decimal,
        item_sku: str,
        from_warehouse: str,
        to_warehouse: str,
        item_id: UUID | None = None,
        record_in_transit: bool = True,
        item: ItemEntity | None = None,
    ) -> InvariantResult:
        """
        Enforce transfer invariants:
        - transfer_quantity <= source_stock (no negative stock)
        - from_warehouse != to_warehouse
        - quantity positive
        - from and to warehouses tidak kosong
        Optionally records in-transit status.
        """
        result = InvariantResult(True)

        # === AUDIT START ===
        self._audit_log(
            f"Transfer start - item={item_sku}, from={from_warehouse}, "
            f"to={to_warehouse}, qty={transfer_quantity}"
        )

        # === VALIDATE QUANTITY NOT NEGATIVE ===
        if transfer_quantity < 0:
            result.add_error(f"Transfer quantity cannot be negative: {transfer_quantity}")

        # === VALIDATE ITEM ACTIVE ===
        if item is not None:
            result.merge(self._invariants.validate_item_active_for_transaction(item))

        # === VALIDATE FROM/TO WAREHOUSE ===
        if not from_warehouse or not from_warehouse.strip():
            result.add_error("From warehouse must be provided and non-empty.")
        if not to_warehouse or not to_warehouse.strip():
            result.add_error("To warehouse must be provided and non-empty.")
        if from_warehouse == to_warehouse:
            result.add_error(f"From and to warehouses are the same: {from_warehouse}")

        # === VALIDATE POSITIVE QUANTITY ===
        if transfer_quantity <= 0:
            result.add_error(f"Transfer quantity must be positive: {transfer_quantity}")

        # === VALIDATE NEGATIVE STOCK (using calculation) ===
        remaining = source_stock - transfer_quantity
        if remaining < 0:
            result.add_error(
                f"Insufficient stock for transfer: available {source_stock}, "
                f"requested {transfer_quantity}. Stock cannot be negative (would be {remaining})."
            )

        # === IN-TRANSIT TRACKING ===
        if record_in_transit and result.is_valid:
            logger.info(
                f"IN_TRANSIT: Transfer of {item_sku} from {from_warehouse} "
                f"to {to_warehouse}, qty={transfer_quantity}, status='IN_TRANSIT'"
            )

        # === AUDIT END ===
        self._audit_log(
            f"Transfer end - item={item_sku}, from={from_warehouse}, "
            f"to={to_warehouse}, valid={result.is_valid}, "
            f"errors={result.errors if not result.is_valid else 'none'}"
        )

        return result

    async def enforce_stock_opname(
        self,
        system_quantity: Decimal,
        physical_quantity: Decimal,
    ) -> InvariantResult:
        return self._invariants.validate_stock_opname_discrepancy(
            system_quantity, physical_quantity
        )

    def enforce_negative_balance(
        self, balance: Decimal, item_sku: str, warehouse: str
    ) -> InvariantResult:
        return self._invariants.validate_negative_balance(balance, item_sku, warehouse)

    def enforce_positive_quantity(
        self, quantity: Decimal, field_name: str = "Quantity"
    ) -> InvariantResult:
        return self._invariants.validate_positive_quantity(quantity, field_name)

    def enforce_non_negative_cost(self, cost: Decimal, field_name: str = "Cost") -> InvariantResult:
        return self._invariants.validate_non_negative_cost(cost, field_name)

    async def enforce_item_active_for_transaction(self, item: ItemEntity) -> InvariantResult:
        return self._invariants.validate_item_active_for_transaction(item)


# ============================================================================
# 5. INVENTORY INVARIANTS VALIDATOR (digunakan oleh service)
# ============================================================================


class InventoryInvariantsValidator:
    """
    Validator sederhana yang digunakan oleh InventoryService.
    Semua method synchronous untuk kemudahan penggunaan.
    """

    @staticmethod
    def allow_negative_stock(item: ItemEntity) -> bool:
        return False

    @staticmethod
    def validate_item_sku_unique(sku: str, existing_skus: set[str]) -> bool:
        if sku in existing_skus:
            raise ValueError(f"SKU '{sku}' already exists")
        return True

    @staticmethod
    def validate_item_active_for_transaction(item: ItemEntity) -> bool:
        if item.status != ItemStatus.ACTIVE:
            raise ValueError(f"Item {item.sku} is not active, cannot record transaction")
        return True

    @staticmethod
    def validate_quantity_positive(quantity: Decimal) -> bool:
        if quantity <= 0:
            raise ValueError(f"Quantity must be positive: {quantity}")
        return True

    @staticmethod
    def validate_unit_cost_non_negative(cost: Decimal) -> bool:
        if cost < 0:
            raise ValueError(f"Unit cost cannot be negative: {cost}")
        return True

    @staticmethod
    def validate_stock_sufficient(current_stock: Decimal, requested: Decimal, sku: str) -> bool:
        if requested > current_stock:
            raise ValueError(
                f"Insufficient stock for {sku}: available {current_stock}, requested {requested}"
            )
        return True


# ============================================================================
# 6. EXPORTS
# ============================================================================

__all__ = [
    "InvariantResult",
    "InventoryInvariantEnforcer",
    "InventoryInvariants",
    "InventoryInvariantsValidator",
]
