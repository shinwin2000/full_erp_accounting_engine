#!/usr/bin/env python3
"""
Module: psak_14_inventories.py
Layer: 7 - Policy Engine & Standards / PSAK

Responsibility:
    PSAK 14: Persediaan (setara dengan IAS 2).
    Mengatur perlakuan akuntansi untuk persediaan, termasuk penentuan
    biaya perolehan, pengakuan sebagai beban, dan penurunan nilai
    persediaan ke nilai realisasi bersih (NRV). Melarang penggunaan
    metode LIFO. Mendukung metode FIFO dan rata-rata tertimbang.

Dependencies:
    - datetime, decimal, enum, typing, dataclasses, uuid, hashlib, logging

Audit:
    Setiap pergerakan persediaan, perubahan biaya, dan write-down dicatat.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================
class PSAK14CostFormula(Enum):
    FIFO = "fifo"
    WEIGHTED_AVERAGE = "rata_rata_tertimbang"
    SPECIFIC_IDENTIFICATION = "identifikasi_khusus"


class PSAK14ValuationMethod(Enum):
    LOWER_OF_COST_OR_NRV = "lower_of_cost_or_nrv"
    COST = "biaya"
    NRV = "nilai_realisasi_bersih"


class PSAK14MovementType(Enum):
    PURCHASE = "pembelian"
    SALE = "penjualan"
    RETURN = "retur"
    ADJUSTMENT = "penyesuaian"
    TRANSFER = "transfer"


class PSAK14ComplianceLevel(Enum):
    FULL = "penuh"
    SUBSTANTIAL = "substansial"
    PARTIAL = "sebagian"
    NON_COMPLIANT = "tidak_patuh"


# ============================================================================
# Exceptions
# ============================================================================
class PSAK14Error(Exception):
    pass


class InsufficientInventoryError(PSAK14Error):
    pass


class InvalidCostFormulaError(PSAK14Error):
    pass


# ============================================================================
# Data Classes
# ============================================================================
@dataclass
class PSAK14InventoryItem:
    """Item persediaan individual."""

    item_id: UUID
    item_code: str
    description: str
    unit_of_measure: str
    cost_formula: PSAK14CostFormula
    quantity_on_hand: Decimal = Decimal(0)
    total_cost: Decimal = Decimal(0)
    weighted_average_cost: Decimal = Decimal(0)
    nrv_per_unit: Decimal = Decimal(0)
    write_down_allowance: Decimal = Decimal(0)
    valuation_basis: PSAK14ValuationMethod = PSAK14ValuationMethod.LOWER_OF_COST_OR_NRV
    last_valuation_date: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def unit_cost(self) -> Decimal:
        if self.quantity_on_hand > 0:
            return self.total_cost / self.quantity_on_hand
        return Decimal(0)

    @property
    def carrying_amount(self) -> Decimal:
        if self.valuation_basis == PSAK14ValuationMethod.LOWER_OF_COST_OR_NRV:
            unit_nrv = self.nrv_per_unit
            nrv_total = self.quantity_on_hand * unit_nrv
            write_down_needed = max(Decimal(0), self.total_cost - nrv_total)
            return self.total_cost - write_down_needed
        elif self.valuation_basis == PSAK14ValuationMethod.NRV:
            return self.quantity_on_hand * self.nrv_per_unit
        else:
            return self.total_cost

    @property
    def effective_unit_value(self) -> Decimal:
        if self.quantity_on_hand > 0:
            return self.carrying_amount / self.quantity_on_hand
        return Decimal(0)

    def to_dict(self) -> dict:
        return {
            "item_id": str(self.item_id),
            "item_code": self.item_code,
            "description": self.description,
            "unit_of_measure": self.unit_of_measure,
            "cost_formula": self.cost_formula.value,
            "quantity_on_hand": str(self.quantity_on_hand),
            "total_cost": str(self.total_cost),
            "unit_cost": str(self.unit_cost),
            "weighted_average_cost": str(self.weighted_average_cost),
            "nrv_per_unit": str(self.nrv_per_unit),
            "write_down_allowance": str(self.write_down_allowance),
            "valuation_basis": self.valuation_basis.value,
            "carrying_amount": str(self.carrying_amount),
            "effective_unit_value": str(self.effective_unit_value),
        }


@dataclass
class PSAK14FIFOLayer:
    """Layer FIFO untuk satu item."""

    purchase_date: datetime
    quantity: Decimal
    unit_cost: Decimal
    remaining_quantity: Decimal

    @property
    def remaining_value(self) -> Decimal:
        return self.remaining_quantity * self.unit_cost

    def to_dict(self) -> dict:
        return {
            "purchase_date": self.purchase_date.isoformat(),
            "quantity": str(self.quantity),
            "unit_cost": str(self.unit_cost),
            "remaining_quantity": str(self.remaining_quantity),
            "remaining_value": str(self.remaining_value),
        }


@dataclass
class PSAK14InventoryTransaction:
    """Transaksi persediaan."""

    transaction_id: UUID
    item_id: UUID
    movement_type: PSAK14MovementType
    quantity: Decimal
    unit_cost: Decimal
    total_value: Decimal
    transaction_date: datetime
    reference_document: str = ""
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "transaction_id": str(self.transaction_id),
            "item_id": str(self.item_id),
            "movement_type": self.movement_type.value,
            "quantity": str(self.quantity),
            "unit_cost": str(self.unit_cost),
            "total_value": str(self.total_value),
            "transaction_date": self.transaction_date.isoformat(),
            "reference": self.reference_document,
        }


@dataclass
class PSAK14Inventory:
    """Inventaris persediaan entitas."""

    inventory_id: UUID
    entity_id: UUID
    entity_name: str
    reporting_date: datetime
    items: list[PSAK14InventoryItem] = field(default_factory=list)
    transactions: list[PSAK14InventoryTransaction] = field(default_factory=list)
    fifo_layers: dict[UUID, list[PSAK14FIFOLayer]] = field(default_factory=dict)

    def total_inventory_value(self) -> Decimal:
        return sum(i.carrying_amount for i in self.items)

    def total_write_down(self) -> Decimal:
        return sum(i.write_down_allowance for i in self.items)

    def to_dict(self) -> dict:
        return {
            "inventory_id": str(self.inventory_id),
            "entity_id": str(self.entity_id),
            "entity_name": self.entity_name,
            "reporting_date": self.reporting_date.isoformat(),
            "items": [i.to_dict() for i in self.items],
            "transactions": [t.to_dict() for t in self.transactions],
            "total_inventory_value": str(self.total_inventory_value()),
            "total_write_down": str(self.total_write_down()),
        }


@dataclass
class PSAK14ValidationResult:
    is_compliant: bool
    compliance_level: PSAK14ComplianceLevel
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    hash_sha256: str = ""

    def __post_init__(self):
        self.hash_sha256 = self._compute_hash()

    def _compute_hash(self) -> str:
        data = {
            "is_compliant": self.is_compliant,
            "level": self.compliance_level.value,
            "errors": self.errors,
            "warnings": self.warnings,
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def add_error(self, error: str) -> None:
        self.errors.append(error)
        self.is_compliant = False
        if self.compliance_level != PSAK14ComplianceLevel.NON_COMPLIANT:
            self.compliance_level = PSAK14ComplianceLevel.NON_COMPLIANT

    def add_warning(self, warning: str) -> None:
        self.warnings.append(warning)
        if self.compliance_level == PSAK14ComplianceLevel.FULL:
            self.compliance_level = PSAK14ComplianceLevel.SUBSTANTIAL

    def to_dict(self) -> dict:
        return {
            "is_compliant": self.is_compliant,
            "compliance_level": self.compliance_level.value,
            "errors": self.errors,
            "warnings": self.warnings,
            "hash": self.hash_sha256,
        }


# ============================================================================
# Domain Services
# ============================================================================
class PSAK14InventoryService:
    """Service untuk perhitungan persediaan."""

    @staticmethod
    def calculate_weighted_average_cost(
        current_total_cost: Decimal,
        current_quantity: Decimal,
        new_purchase_cost: Decimal,
        new_purchase_quantity: Decimal,
    ) -> Decimal:
        total_quantity = current_quantity + new_purchase_quantity
        if total_quantity == 0:
            return Decimal(0)
        total_cost = current_total_cost + new_purchase_cost
        return (total_cost / total_quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    @staticmethod
    def calculate_fifo_cogs(
        fifo_layers: list[PSAK14FIFOLayer],
        quantity_sold: Decimal,
    ) -> tuple[Decimal, list[PSAK14FIFOLayer]]:
        remaining = quantity_sold
        cogs = Decimal(0)
        new_layers = []
        for layer in fifo_layers:
            if remaining <= 0:
                new_layers.append(layer)
                continue
            take = min(layer.remaining_quantity, remaining)
            cogs += take * layer.unit_cost
            remaining -= take
            if take < layer.remaining_quantity:
                # Layer masih tersisa
                new_layer = PSAK14FIFOLayer(
                    purchase_date=layer.purchase_date,
                    quantity=layer.quantity,
                    unit_cost=layer.unit_cost,
                    remaining_quantity=layer.remaining_quantity - take,
                )
                new_layers.append(new_layer)
            else:
                # Layer habis, tidak ditambahkan
                pass
        if remaining > 0:
            raise InsufficientInventoryError(
                f"Insufficient inventory: need {quantity_sold}, available less"
            )
        return cogs, new_layers

    @staticmethod
    def calculate_nrv(
        estimated_selling_price: Decimal,
        estimated_costs_to_complete: Decimal,
        estimated_costs_to_sell: Decimal,
    ) -> Decimal:
        return (
            estimated_selling_price - estimated_costs_to_complete - estimated_costs_to_sell
        ).quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)


# ============================================================================
# Rules
# ============================================================================
class PSAK14Rules:
    """Aturan PSAK 14."""

    @staticmethod
    def validate_cost_formula(formula: PSAK14CostFormula) -> PSAK14ValidationResult:
        result = PSAK14ValidationResult(
            is_compliant=True, compliance_level=PSAK14ComplianceLevel.FULL
        )
        if formula == PSAK14CostFormula.SPECIFIC_IDENTIFICATION:
            # Hanya untuk barang yang tidak dapat dipertukarkan
            result.add_warning(
                "Metode identifikasi khusus hanya untuk persediaan yang tidak dapat dipertukarkan"
            )
        return result

    @staticmethod
    def validate_nrv(item: PSAK14InventoryItem) -> PSAK14ValidationResult:
        result = PSAK14ValidationResult(
            is_compliant=True, compliance_level=PSAK14ComplianceLevel.FULL
        )
        if item.nrv_per_unit < 0:
            result.add_error(
                f"NRV per unit negatif untuk item {item.item_code}: {item.nrv_per_unit}"
            )
        if item.nrv_per_unit < item.unit_cost and item.write_down_allowance == 0:
            result.add_warning(
                "NRV lebih rendah dari biaya tetapi allowance write-down belum dicatat"
            )
        return result

    @staticmethod
    def validate_consistency(inventory: PSAK14Inventory) -> PSAK14ValidationResult:
        result = PSAK14ValidationResult(
            is_compliant=True, compliance_level=PSAK14ComplianceLevel.FULL
        )
        formulas = {i.cost_formula for i in inventory.items}
        if len(formulas) > 1:
            result.add_warning(
                f"Beberapa item menggunakan formula biaya yang berbeda: {[f.value for f in formulas]}"
            )
        return result


# ============================================================================
# Validator
# ============================================================================
class PSAK14Validator:
    def __init__(self):
        self._rules = PSAK14Rules()
        self._service = PSAK14InventoryService()

    def create_item(
        self,
        item_code: str,
        description: str,
        unit_of_measure: str,
        cost_formula: PSAK14CostFormula = PSAK14CostFormula.FIFO,
        opening_quantity: Decimal = Decimal(0),
        opening_cost: Decimal = Decimal(0),
    ) -> PSAK14InventoryItem:
        return PSAK14InventoryItem(
            item_id=uuid4(),
            item_code=item_code,
            description=description,
            unit_of_measure=unit_of_measure,
            cost_formula=cost_formula,
            quantity_on_hand=opening_quantity,
            total_cost=opening_cost,
            weighted_average_cost=opening_cost / opening_quantity
            if opening_quantity > 0
            else Decimal(0),
        )

    def create_inventory(
        self,
        entity_id: UUID,
        entity_name: str,
        reporting_date: datetime,
    ) -> PSAK14Inventory:
        return PSAK14Inventory(
            inventory_id=uuid4(),
            entity_id=entity_id,
            entity_name=entity_name,
            reporting_date=reporting_date,
        )

    def add_item(self, inventory: PSAK14Inventory, item: PSAK14InventoryItem) -> PSAK14Inventory:
        new_items = [*inventory.items, item]
        return PSAK14Inventory(
            inventory_id=inventory.inventory_id,
            entity_id=inventory.entity_id,
            entity_name=inventory.entity_name,
            reporting_date=inventory.reporting_date,
            items=new_items,
            transactions=inventory.transactions,
            fifo_layers=inventory.fifo_layers,
        )

    def record_purchase(
        self,
        inventory: PSAK14Inventory,
        item_id: UUID,
        quantity: Decimal,
        unit_cost: Decimal,
        transaction_date: datetime,
        reference: str = "",
    ) -> PSAK14Inventory:
        for i, item in enumerate(inventory.items):
            if item.item_id == item_id:
                if item.cost_formula == PSAK14CostFormula.WEIGHTED_AVERAGE:
                    new_avg = self._service.calculate_weighted_average_cost(
                        item.total_cost, item.quantity_on_hand, quantity * unit_cost, quantity
                    )
                    new_total_cost = item.total_cost + (quantity * unit_cost)
                    new_quantity = item.quantity_on_hand + quantity
                    updated_item = PSAK14InventoryItem(
                        item_id=item.item_id,
                        item_code=item.item_code,
                        description=item.description,
                        unit_of_measure=item.unit_of_measure,
                        cost_formula=item.cost_formula,
                        quantity_on_hand=new_quantity,
                        total_cost=new_total_cost,
                        weighted_average_cost=new_avg,
                        nrv_per_unit=item.nrv_per_unit,
                        write_down_allowance=item.write_down_allowance,
                        valuation_basis=item.valuation_basis,
                    )
                elif item.cost_formula == PSAK14CostFormula.FIFO:
                    # Update FIFO layers
                    layers = inventory.fifo_layers.get(item_id, [])
                    new_layer = PSAK14FIFOLayer(
                        purchase_date=transaction_date,
                        quantity=quantity,
                        unit_cost=unit_cost,
                        remaining_quantity=quantity,
                    )
                    layers.append(new_layer)
                    new_fifo_layers = inventory.fifo_layers.copy()
                    new_fifo_layers[item_id] = layers
                    new_total_cost = item.total_cost + (quantity * unit_cost)
                    new_quantity = item.quantity_on_hand + quantity
                    updated_item = PSAK14InventoryItem(
                        item_id=item.item_id,
                        item_code=item.item_code,
                        description=item.description,
                        unit_of_measure=item.unit_of_measure,
                        cost_formula=item.cost_formula,
                        quantity_on_hand=new_quantity,
                        total_cost=new_total_cost,
                        nrv_per_unit=item.nrv_per_unit,
                        write_down_allowance=item.write_down_allowance,
                        valuation_basis=item.valuation_basis,
                    )
                    new_items = inventory.items.copy()
                    new_items[i] = updated_item
                    new_transaction = self._create_transaction(
                        item_id,
                        PSAK14MovementType.PURCHASE,
                        quantity,
                        unit_cost,
                        transaction_date,
                        reference,
                    )
                    return PSAK14Inventory(
                        inventory_id=inventory.inventory_id,
                        entity_id=inventory.entity_id,
                        entity_name=inventory.entity_name,
                        reporting_date=inventory.reporting_date,
                        items=new_items,
                        transactions=[*inventory.transactions, new_transaction],
                        fifo_layers=new_fifo_layers,
                    )
                else:
                    # Specific identification: simple addition
                    new_total_cost = item.total_cost + (quantity * unit_cost)
                    new_quantity = item.quantity_on_hand + quantity
                    updated_item = PSAK14InventoryItem(
                        item_id=item.item_id,
                        item_code=item.item_code,
                        description=item.description,
                        unit_of_measure=item.unit_of_measure,
                        cost_formula=item.cost_formula,
                        quantity_on_hand=new_quantity,
                        total_cost=new_total_cost,
                        nrv_per_unit=item.nrv_per_unit,
                        write_down_allowance=item.write_down_allowance,
                        valuation_basis=item.valuation_basis,
                    )
                new_items = inventory.items.copy()
                new_items[i] = updated_item
                new_transaction = self._create_transaction(
                    item_id,
                    PSAK14MovementType.PURCHASE,
                    quantity,
                    unit_cost,
                    transaction_date,
                    reference,
                )
                return PSAK14Inventory(
                    inventory_id=inventory.inventory_id,
                    entity_id=inventory.entity_id,
                    entity_name=inventory.entity_name,
                    reporting_date=inventory.reporting_date,
                    items=new_items,
                    transactions=[*inventory.transactions, new_transaction],
                    fifo_layers=inventory.fifo_layers,
                )
        raise PSAK14Error(f"Item {item_id} not found")

    def record_sale(
        self,
        inventory: PSAK14Inventory,
        item_id: UUID,
        quantity: Decimal,
        transaction_date: datetime,
        reference: str = "",
    ) -> tuple[PSAK14Inventory, Decimal]:
        for i, item in enumerate(inventory.items):
            if item.item_id == item_id:
                if quantity > item.quantity_on_hand:
                    raise InsufficientInventoryError(
                        f"Insufficient stock for item {item.item_code}: need {quantity}, available {item.quantity_on_hand}"
                    )

                if item.cost_formula == PSAK14CostFormula.WEIGHTED_AVERAGE:
                    cogs = quantity * item.weighted_average_cost
                    new_quantity = item.quantity_on_hand - quantity
                    new_total_cost = item.total_cost - cogs
                    updated_item = PSAK14InventoryItem(
                        item_id=item.item_id,
                        item_code=item.item_code,
                        description=item.description,
                        unit_of_measure=item.unit_of_measure,
                        cost_formula=item.cost_formula,
                        quantity_on_hand=new_quantity,
                        total_cost=new_total_cost,
                        weighted_average_cost=item.weighted_average_cost,
                        nrv_per_unit=item.nrv_per_unit,
                        write_down_allowance=item.write_down_allowance,
                        valuation_basis=item.valuation_basis,
                    )
                elif item.cost_formula == PSAK14CostFormula.FIFO:
                    layers = inventory.fifo_layers.get(item_id, [])
                    cogs, new_layers = self._service.calculate_fifo_cogs(layers, quantity)
                    new_fifo_layers = inventory.fifo_layers.copy()
                    new_fifo_layers[item_id] = new_layers
                    new_quantity = item.quantity_on_hand - quantity
                    new_total_cost = sum(layer.remaining_value for layer in new_layers)
                    updated_item = PSAK14InventoryItem(
                        item_id=item.item_id,
                        item_code=item.item_code,
                        description=item.description,
                        unit_of_measure=item.unit_of_measure,
                        cost_formula=item.cost_formula,
                        quantity_on_hand=new_quantity,
                        total_cost=new_total_cost,
                        nrv_per_unit=item.nrv_per_unit,
                        write_down_allowance=item.write_down_allowance,
                        valuation_basis=item.valuation_basis,
                    )
                    new_items = inventory.items.copy()
                    new_items[i] = updated_item
                    new_transaction = self._create_transaction(
                        item_id,
                        PSAK14MovementType.SALE,
                        quantity,
                        cogs / quantity,
                        transaction_date,
                        reference,
                    )
                    return (
                        PSAK14Inventory(
                            inventory_id=inventory.inventory_id,
                            entity_id=inventory.entity_id,
                            entity_name=inventory.entity_name,
                            reporting_date=inventory.reporting_date,
                            items=new_items,
                            transactions=[*inventory.transactions, new_transaction],
                            fifo_layers=new_fifo_layers,
                        ),
                        cogs,
                    )
                else:
                    # Specific identification: simple reduction
                    unit = item.unit_cost
                    cogs = quantity * unit
                    new_quantity = item.quantity_on_hand - quantity
                    new_total_cost = item.total_cost - cogs
                    updated_item = PSAK14InventoryItem(
                        item_id=item.item_id,
                        item_code=item.item_code,
                        description=item.description,
                        unit_of_measure=item.unit_of_measure,
                        cost_formula=item.cost_formula,
                        quantity_on_hand=new_quantity,
                        total_cost=new_total_cost,
                        nrv_per_unit=item.nrv_per_unit,
                        write_down_allowance=item.write_down_allowance,
                        valuation_basis=item.valuation_basis,
                    )
                new_items = inventory.items.copy()
                new_items[i] = updated_item
                new_transaction = self._create_transaction(
                    item_id,
                    PSAK14MovementType.SALE,
                    quantity,
                    cogs / quantity,
                    transaction_date,
                    reference,
                )
                return (
                    PSAK14Inventory(
                        inventory_id=inventory.inventory_id,
                        entity_id=inventory.entity_id,
                        entity_name=inventory.entity_name,
                        reporting_date=inventory.reporting_date,
                        items=new_items,
                        transactions=[*inventory.transactions, new_transaction],
                        fifo_layers=inventory.fifo_layers,
                    ),
                    cogs,
                )
        raise PSAK14Error(f"Item {item_id} not found")

    def update_nrv(
        self,
        inventory: PSAK14Inventory,
        item_id: UUID,
        estimated_selling_price: Decimal,
        estimated_costs_to_complete: Decimal,
        estimated_costs_to_sell: Decimal,
        valuation_date: datetime,
    ) -> PSAK14Inventory:
        nrv = self._service.calculate_nrv(
            estimated_selling_price, estimated_costs_to_complete, estimated_costs_to_sell
        )
        new_items = []
        for item in inventory.items:
            if item.item_id == item_id:
                write_down = max(Decimal(0), item.total_cost - (item.quantity_on_hand * nrv))
                updated = PSAK14InventoryItem(
                    item_id=item.item_id,
                    item_code=item.item_code,
                    description=item.description,
                    unit_of_measure=item.unit_of_measure,
                    cost_formula=item.cost_formula,
                    quantity_on_hand=item.quantity_on_hand,
                    total_cost=item.total_cost,
                    weighted_average_cost=item.weighted_average_cost,
                    nrv_per_unit=nrv,
                    write_down_allowance=write_down,
                    valuation_basis=item.valuation_basis,
                    last_valuation_date=valuation_date,
                )
                new_items.append(updated)
            else:
                new_items.append(item)
        return PSAK14Inventory(
            inventory_id=inventory.inventory_id,
            entity_id=inventory.entity_id,
            entity_name=inventory.entity_name,
            reporting_date=inventory.reporting_date,
            items=new_items,
            transactions=inventory.transactions,
            fifo_layers=inventory.fifo_layers,
        )

    def _create_transaction(
        self,
        item_id: UUID,
        movement_type: PSAK14MovementType,
        quantity: Decimal,
        unit_cost: Decimal,
        date: datetime,
        ref: str,
    ) -> PSAK14InventoryTransaction:
        return PSAK14InventoryTransaction(
            transaction_id=uuid4(),
            item_id=item_id,
            movement_type=movement_type,
            quantity=quantity,
            unit_cost=unit_cost,
            total_value=quantity * unit_cost,
            transaction_date=date,
            reference_document=ref,
        )

    def validate_inventory(self, inventory: PSAK14Inventory) -> PSAK14ValidationResult:
        result = PSAK14ValidationResult(
            is_compliant=True, compliance_level=PSAK14ComplianceLevel.FULL
        )
        for item in inventory.items:
            result = self._merge_results(
                result, self._rules.validate_cost_formula(item.cost_formula)
            )
            result = self._merge_results(result, self._rules.validate_nrv(item))
        result = self._merge_results(result, self._rules.validate_consistency(inventory))
        return result

    def _merge_results(
        self, main: PSAK14ValidationResult, other: PSAK14ValidationResult
    ) -> PSAK14ValidationResult:
        main.errors.extend(other.errors)
        main.warnings.extend(other.warnings)
        main.is_compliant = main.is_compliant and other.is_compliant
        level_order = [
            PSAK14ComplianceLevel.FULL,
            PSAK14ComplianceLevel.SUBSTANTIAL,
            PSAK14ComplianceLevel.PARTIAL,
            PSAK14ComplianceLevel.NON_COMPLIANT,
        ]
        main_idx = level_order.index(main.compliance_level)
        other_idx = level_order.index(other.compliance_level)
        if other_idx > main_idx:
            main.compliance_level = level_order[other_idx]
        return main

    def get_requirements_summary(self) -> dict:
        return {
            "cost_formulas": [
                "FIFO",
                "Rata-rata tertimbang",
                "Identifikasi khusus (untuk barang tidak dapat dipertukarkan)",
            ],
            "disallowed_method": "LIFO (dilarang)",
            "measurement": "Lower of cost and net realizable value (LCNRV)",
            "nrv_definition": "Estimated selling price - estimated costs to complete - estimated costs to sell",
            "reversal": "Write-down dapat dibalik jika NRV meningkat",
            "disclosures": [
                "Kebijakan akuntansi persediaan",
                "Total nilai tercatat persediaan",
                "Jumlah persediaan yang diakui sebagai beban",
                "Write-down dan reversal",
                "Persediaan yang dijaminkan",
            ],
        }


class PSAK14:
    @staticmethod
    def calculate_inventory_cost(purchase_price, freight, import_duties, handling):
        return purchase_price + freight + import_duties + handling

    @staticmethod
    def net_realizable_value(selling_price, cost_to_complete, cost_to_sell):
        return selling_price - cost_to_complete - cost_to_sell

    @staticmethod
    def is_write_down_required(cost, nrv):
        return cost > nrv


# ============================================================================
# Singleton Accessor
# ============================================================================
_psak14_validator_instance: PSAK14Validator | None = None


def get_psak14_validator() -> PSAK14Validator:
    global _psak14_validator_instance
    if _psak14_validator_instance is None:
        _psak14_validator_instance = PSAK14Validator()
    return _psak14_validator_instance


InventoryMeasurementBasis = PSAK14ValuationMethod
InventoryValuationMethod = PSAK14CostFormula
InventoryValuation = PSAK14Inventory

# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    validator = get_psak14_validator()
    entity_id = uuid4()

    inventory = validator.create_inventory(
        entity_id=entity_id,
        entity_name="PT Gudang Persediaan",
        reporting_date=datetime(2026, 12, 31, tzinfo=UTC),
    )

    # Create two items
    item1 = validator.create_item("INV-001", "Produk Elektronik", "unit", PSAK14CostFormula.FIFO)
    item2 = validator.create_item("INV-002", "Bahan Baku", "kg", PSAK14CostFormula.WEIGHTED_AVERAGE)
    inventory = validator.add_item(inventory, item1)
    inventory = validator.add_item(inventory, item2)

    # Purchases for item1 (FIFO)
    inventory = validator.record_purchase(
        inventory,
        item1.item_id,
        100,
        Decimal("50000"),
        datetime(2026, 1, 15, tzinfo=UTC),
        "PO-001",
    )
    inventory = validator.record_purchase(
        inventory,
        item1.item_id,
        50,
        Decimal("52000"),
        datetime(2026, 6, 20, tzinfo=UTC),
        "PO-002",
    )

    # Sales for item1 (FIFO)
    inventory, cogs1 = validator.record_sale(
        inventory, item1.item_id, 80, datetime(2026, 12, 10, tzinfo=UTC), "SO-001"
    )
    print(f"COGS for item1 (FIFO): {cogs1}")

    # Purchases for item2 (Weighted Average)
    inventory = validator.record_purchase(
        inventory,
        item2.item_id,
        1000,
        Decimal("10000"),
        datetime(2026, 2, 1, tzinfo=UTC),
        "PO-003",
    )
    inventory = validator.record_purchase(
        inventory,
        item2.item_id,
        500,
        Decimal("10500"),
        datetime(2026, 5, 1, tzinfo=UTC),
        "PO-004",
    )
    # Check weighted average cost
    for i in inventory.items:
        if i.item_id == item2.item_id:
            print(f"Weighted average cost after purchases: {i.weighted_average_cost}")

    # Update NRV for item1
    inventory = validator.update_nrv(
        inventory,
        item1.item_id,
        Decimal("55000"),
        Decimal("2000"),
        Decimal("1000"),
        datetime(2026, 12, 31, tzinfo=UTC),
    )

    # Validate
    result = validator.validate_inventory(inventory)
    print("Validation Result:")
    print(json.dumps(result.to_dict(), indent=2))
    print("\nInventory Status:")
    print(json.dumps(inventory.to_dict(), indent=2, default=str))
