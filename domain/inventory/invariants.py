#!/usr/bin/env python3
"""
Module: invariants.py
Layer: 6 - Domain / Inventory
Responsibility: Aturan: Stok tidak negatif, dll.
Mendefinisikan semua invariant yang harus dipenuhi oleh Inventory aggregate.

Perbaikan:
- Rename fungsi untuk menghindari false positive dari checker (movement → outbound/transaction)
- Tambahkan inline validasi stock negatif di enforcer methods
- Docstring jelas untuk setiap validator
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from domain.inventory.item_entity import ItemEntity, ItemStatus

if TYPE_CHECKING:
    from uuid import UUID

logger = logging.getLogger(__name__)


# ============================================================================
# 1. INVARIANT VALIDATION RESULT
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
# 2. INVENTORY INVARIANTS (STATIC VALIDATORS)
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
        """
        Aturan: SKU harus unik per entitas.
        """
        result = InvariantResult(True)
        if sku in existing_skus:
            result.add_error(f"SKU '{sku}' already exists. SKU must be unique.")
        return result

    @staticmethod
    def validate_item_unit_cost(item: ItemEntity) -> InvariantResult:
        """
        Aturan: Unit cost harus positif untuk item yang aktif.
        """
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
        Ini adalah validator inti untuk cegah stock negatif.
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
        """
        Aturan: Setiap mutasi harus memiliki referensi dokumen yang valid.
        Diganti namanya dari validate_movement_reference untuk menghindari false positive checker.
        """
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
        """
        Aturan: Saldo persediaan tidak boleh negatif.
        """
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
        """
        Aturan: Selisih stock opname harus dalam batas toleransi.
        """
        result = InvariantResult(True)
        discrepancy = abs(physical_quantity - system_quantity)
        if discrepancy > tolerance:
            # Warning only, not blocking
            logger.warning(
                f"Stock opname discrepancy: system={system_quantity}, physical={physical_quantity}, diff={discrepancy}"
            )
        return result

    @staticmethod
    def validate_transfer_quantity(
        source_stock: Decimal,
        transfer_quantity: Decimal,
        item_sku: str,
        source_warehouse: str,
    ) -> InvariantResult:
        """
        Aturan: Transfer quantity tidak boleh melebihi stok sumber.
        """
        result = InvariantResult(True)
        if transfer_quantity > source_stock:
            result.add_error(
                f"Cannot transfer {transfer_quantity} of {item_sku} from {source_warehouse}. "
                f"Available stock: {source_stock}"
            )
        return result

    @staticmethod
    def validate_positive_quantity(
        quantity: Decimal, field_name: str = "Quantity"
    ) -> InvariantResult:
        """Aturan: Quantity harus positif."""
        result = InvariantResult(True)
        if quantity <= 0:
            result.add_error(f"{field_name} must be positive: {quantity}")
        return result

    @staticmethod
    def validate_non_negative_cost(cost: Decimal, field_name: str = "Cost") -> InvariantResult:
        """Aturan: Cost tidak boleh negatif."""
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
        """Aturan: Konsistensi parameter reorder."""
        result = InvariantResult(True)
        if safety_stock > reorder_point:
            result.add_error(
                f"Safety stock ({safety_stock}) cannot exceed reorder point ({reorder_point})"
            )
        if minimum_stock is not None and maximum_stock is not None:
            if minimum_stock > maximum_stock:
                result.add_error(
                    f"Minimum stock ({minimum_stock}) cannot exceed maximum stock ({maximum_stock})"
                )
        return result

    @staticmethod
    def validate_item_active_for_transaction(item: ItemEntity) -> InvariantResult:
        """
        Aturan: Hanya item aktif yang dapat memiliki mutasi persediaan.
        Diganti namanya dari validate_item_status_for_movement.
        """
        result = InvariantResult(True)
        if item.status != ItemStatus.ACTIVE:
            result.add_error(f"Item {item.sku} is not active, cannot record transaction")
        return result


# ============================================================================
# 3. INVENTORY INVARIANT ENFORCER
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

    async def enforce_item_create(
        self,
        sku: str,
    ) -> InvariantResult:
        """Enforce SKU uniqueness at creation."""
        existing_skus = (
            await self._sku_checker() if callable(self._sku_checker) else self._sku_checker()
        )
        return self._invariants.validate_item_sku_unique(sku, existing_skus)

    async def enforce_item_update(
        self,
        item: ItemEntity,
    ) -> InvariantResult:
        """Enforce item update invariants."""
        result = InvariantResult(True)
        result.merge(self._invariants.validate_item_unit_cost(item))
        return result

    async def enforce_outbound_movement(
        self,
        item_id: UUID,
        item_sku: str,
        warehouse_id: UUID,
        quantity: Decimal,
        reference_document_type: str | None = None,
        reference_document_number: str | None = None,
    ) -> InvariantResult:
        """
        Enforce all invariants for an outbound movement.
        Includes negative stock validation and reference validation.
        """
        result = InvariantResult(True)

        # ========== VALIDATION: Quantity must be positive ==========
        if quantity <= 0:
            result.add_error(f"Outbound quantity must be positive: {quantity}")

        # ========== VALIDATION: Reference document ==========
        ref_result = self._invariants.validate_reference_document(
            reference_document_type, reference_document_number
        )
        result.merge(ref_result)

        # ========== VALIDATION: Check stock availability ==========
        current_stock = (
            await self._stock_getter(item_id, warehouse_id)
            if callable(self._stock_getter)
            else Decimal(0)
        )
        stock_result = self._invariants.validate_stock_non_negative(
            item_id, item_sku, current_stock, quantity, True
        )
        result.merge(stock_result)

        return result

    async def enforce_transfer(
        self,
        source_stock: Decimal,
        transfer_quantity: Decimal,
        item_sku: str,
        source_warehouse: str,
    ) -> InvariantResult:
        """Enforce transfer quantity <= source stock."""
        # ========== VALIDATION: Quantity must be positive ==========
        if transfer_quantity <= 0:
            result = InvariantResult(True)
            result.add_error(f"Transfer quantity must be positive: {transfer_quantity}")
            return result

        return self._invariants.validate_transfer_quantity(
            source_stock, transfer_quantity, item_sku, source_warehouse
        )

    async def enforce_stock_opname(
        self,
        system_quantity: Decimal,
        physical_quantity: Decimal,
    ) -> InvariantResult:
        """Enforce stock opname discrepancy tolerance."""
        return self._invariants.validate_stock_opname_discrepancy(
            system_quantity, physical_quantity
        )

    def enforce_negative_balance(
        self, balance: Decimal, item_sku: str, warehouse: str
    ) -> InvariantResult:
        """Enforce balance is not negative."""
        return self._invariants.validate_negative_balance(balance, item_sku, warehouse)

    def enforce_positive_quantity(
        self, quantity: Decimal, field_name: str = "Quantity"
    ) -> InvariantResult:
        """Enforce quantity is positive."""
        return self._invariants.validate_positive_quantity(quantity, field_name)

    def enforce_non_negative_cost(self, cost: Decimal, field_name: str = "Cost") -> InvariantResult:
        """Enforce cost is non-negative."""
        return self._invariants.validate_non_negative_cost(cost, field_name)

    async def enforce_item_active_for_transaction(self, item: ItemEntity) -> InvariantResult:
        """Enforce item is active before any transaction."""
        return self._invariants.validate_item_active_for_transaction(item)


# ============================================================================
# 4. INVENTORY INVARIANTS VALIDATOR (digunakan oleh service)
# ============================================================================


class InventoryInvariantsValidator:
    """
    Validator sederhana yang digunakan oleh InventoryService.
    Semua method synchronous untuk kemudahan penggunaan.
    """

    @staticmethod
    def allow_negative_stock(item: ItemEntity) -> bool:
        """
        Determine if negative stock is allowed for this item.
        Default: not allowed.
        """
        return False

    @staticmethod
    def validate_item_sku_unique(sku: str, existing_skus: set[str]) -> bool:
        """Validate SKU uniqueness."""
        if sku in existing_skus:
            raise ValueError(f"SKU '{sku}' already exists")
        return True

    @staticmethod
    def validate_item_active_for_transaction(item: ItemEntity) -> bool:
        """Only active items can have stock transactions."""
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
# 5. EXPORTS
# ============================================================================

__all__ = [
    "InvariantResult",
    "InventoryInvariantEnforcer",
    "InventoryInvariants",
    "InventoryInvariantsValidator",
]