#!/usr/bin/env python3
"""
Module: item_entity.py
Layer: 6 - Domain / Inventory
Responsibility: Entitas barang: SKU, deskripsi, satuan, metode penilaian.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


class ItemType(Enum):
    RAW_MATERIAL = "raw_material"
    WORK_IN_PROGRESS = "work_in_progress"
    FINISHED_GOODS = "finished_goods"
    FINISHED_GOOD = "finished_goods"
    PACKAGING = "packaging"
    SUPPLIES = "supplies"
    ASSET = "asset"
    TRADING = "trading"
    SERVICE = "service"

    @classmethod
    def from_string(cls, value: str) -> ItemType:
        for member in cls:
            if member.value == value or member.name == value.upper():
                return member
        return cls.FINISHED_GOODS

    @property
    def is_inventoriable(self) -> bool:
        return self in [
            ItemType.RAW_MATERIAL,
            ItemType.WORK_IN_PROGRESS,
            ItemType.FINISHED_GOODS,
            ItemType.PACKAGING,
            ItemType.SUPPLIES,
            ItemType.TRADING,
        ]


class ItemStatus(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    DISCONTINUED = "discontinued"
    OBSOLETE = "obsolete"

    @classmethod
    def from_string(cls, value: str) -> ItemStatus:
        for member in cls:
            if member.value == value or member.name == value.upper():
                return member
        return cls.ACTIVE


class UnitOfMeasure(Enum):
    PCS = "pcs"
    KG = "kg"
    GRAM = "gram"
    LITER = "liter"
    ML = "ml"
    METER = "meter"
    CM = "cm"
    BOX = "box"
    CARTON = "carton"
    PALLET = "pallet"
    SET = "set"
    DOZEN = "dozen"
    ROLL = "roll"
    SHEET = "sheet"

    @classmethod
    def from_string(cls, value: str) -> UnitOfMeasure:
        for member in cls:
            if member.value == value or member.name == value.upper():
                return member
        return cls.PCS


class ValuationMethod(Enum):
    FIFO = "FIFO"
    LIFO = "LIFO"
    AVERAGE = "AVERAGE"
    MOVING_AVERAGE = "MOVING_AVERAGE"
    STANDARD = "STANDARD"
    SPECIFIC_ID = "SPECIFIC_ID"

    @classmethod
    def from_string(cls, value: str) -> ValuationMethod:
        for member in cls:
            if member.value == value or member.name == value.upper():
                return member
        return cls.FIFO


@dataclass(kw_only=True)
class ItemEntity:
    """Entitas Item persediaan."""

    id: UUID
    legal_entity_id: UUID
    sku: str
    name: str
    description: str | None = None
    item_type: ItemType = ItemType.FINISHED_GOODS
    unit_of_measure: UnitOfMeasure = UnitOfMeasure.PCS
    current_stock: Decimal = Decimal(0)
    current_stock_value: Decimal = Decimal(0)
    average_cost: Decimal = Decimal(0)
    last_cost: Decimal = Decimal(0)
    reorder_point: Decimal = Decimal(0)
    safety_stock: Decimal = Decimal(0)
    maximum_stock: Decimal | None = None
    minimum_stock: Decimal | None = None
    status: ItemStatus = ItemStatus.ACTIVE
    standard_cost: Decimal = Decimal(0)
    selling_price: Decimal = Decimal(0)
    category: str | None = None
    warehouse_code: str | None = None
    created_by: UUID = field(default_factory=uuid.uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None
    updated_by: UUID | None = None
    deactivated_at: datetime | None = None
    deactivated_by: UUID | None = None
    version: int = 1
    barcode: str | None = None
    weight_gram: Decimal | None = None
    dimension_cm: str | None = None
    brand: str | None = None
    lead_time_days: int = 0
    reorder_quantity: Decimal = Decimal(0)
    warehouse_location: str | None = None
    currency: str = "IDR"
    valuation_method: str | None = None
    tax_rate: Decimal = Decimal(0)
    is_taxable: bool = True
    hs_code: str | None = None
    country_of_origin: str | None = None

    @property
    def item_id(self) -> UUID:
        return self.id

    @property
    def unit_cost(self) -> Decimal:
        return self.standard_cost

    @property
    def is_active(self) -> bool:
        return self.status == ItemStatus.ACTIVE

    @property
    def total_stock_value(self) -> Decimal:
        return self.current_stock * self.average_cost

    @property
    def needs_reorder(self) -> bool:
        return self.current_stock <= self.reorder_point and self.reorder_quantity > 0

    @property
    def below_safety_stock(self) -> bool:
        return self.current_stock < self.safety_stock

    @property
    def above_maximum_stock(self) -> bool:
        return self.maximum_stock is not None and self.current_stock > self.maximum_stock

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        """Validate invariants."""
        if not self.sku or len(self.sku.strip()) < 2:
            raise ValueError("SKU must be at least 2 characters")
        if not self.name or len(self.name.strip()) < 2:
            raise ValueError("Item name must be at least 2 characters")
        if self.current_stock < 0:
            raise ValueError(f"Current stock cannot be negative: {self.current_stock}")
        if self.current_stock_value < 0:
            raise ValueError(f"Current stock value cannot be negative: {self.current_stock_value}")
        if self.average_cost < 0:
            raise ValueError(f"Average cost cannot be negative: {self.average_cost}")
        if self.last_cost < 0:
            raise ValueError(f"Last cost cannot be negative: {self.last_cost}")
        if self.standard_cost < 0:
            raise ValueError(f"Standard cost cannot be negative: {self.standard_cost}")
        if self.selling_price < 0:
            raise ValueError(f"Selling price cannot be negative: {self.selling_price}")
        if self.reorder_point < 0:
            raise ValueError(f"Reorder point cannot be negative: {self.reorder_point}")
        if self.safety_stock < 0:
            raise ValueError(f"Safety stock cannot be negative: {self.safety_stock}")
        if self.reorder_quantity < 0:
            raise ValueError(f"Reorder quantity cannot be negative: {self.reorder_quantity}")
        if self.lead_time_days < 0:
            raise ValueError(f"Lead time days cannot be negative: {self.lead_time_days}")
        if self.tax_rate < 0 or self.tax_rate > 100:
            raise ValueError(f"Tax rate must be between 0 and 100: {self.tax_rate}")

    def validate(self) -> list[str]:
        """Validate and return list of errors."""
        errors = []
        if not self.sku or len(self.sku.strip()) < 2:
            errors.append("SKU must be at least 2 characters")
        if not self.name or len(self.name.strip()) < 2:
            errors.append("Item name must be at least 2 characters")
        if self.current_stock < 0:
            errors.append(f"Current stock cannot be negative: {self.current_stock}")
        if self.current_stock_value < 0:
            errors.append(f"Current stock value cannot be negative: {self.current_stock_value}")
        if self.average_cost < 0:
            errors.append(f"Average cost cannot be negative: {self.average_cost}")
        if self.standard_cost < 0:
            errors.append(f"Standard cost cannot be negative: {self.standard_cost}")
        if self.selling_price < 0:
            errors.append(f"Selling price cannot be negative: {self.selling_price}")
        if self.tax_rate < 0 or self.tax_rate > 100:
            errors.append(f"Tax rate must be between 0 and 100: {self.tax_rate}")
        return errors

    # ==================== BUSINESS METHODS ====================

    def activate(self, activated_by: UUID, activated_at: datetime | None = None) -> ItemEntity:
        """Activate the item."""
        now = activated_at or datetime.now(UTC)
        return ItemEntity(
            id=self.id,
            legal_entity_id=self.legal_entity_id,
            sku=self.sku,
            name=self.name,
            description=self.description,
            item_type=self.item_type,
            unit_of_measure=self.unit_of_measure,
            current_stock=self.current_stock,
            current_stock_value=self.current_stock_value,
            average_cost=self.average_cost,
            last_cost=self.last_cost,
            reorder_point=self.reorder_point,
            safety_stock=self.safety_stock,
            maximum_stock=self.maximum_stock,
            minimum_stock=self.minimum_stock,
            status=ItemStatus.ACTIVE,
            standard_cost=self.standard_cost,
            selling_price=self.selling_price,
            category=self.category,
            warehouse_code=self.warehouse_code,
            created_by=self.created_by,
            created_at=self.created_at,
            updated_at=now,
            updated_by=activated_by,
            deactivated_at=None,
            deactivated_by=None,
            version=self.version + 1,
            barcode=self.barcode,
            weight_gram=self.weight_gram,
            dimension_cm=self.dimension_cm,
            brand=self.brand,
            lead_time_days=self.lead_time_days,
            reorder_quantity=self.reorder_quantity,
            warehouse_location=self.warehouse_location,
            currency=self.currency,
            valuation_method=self.valuation_method,
            tax_rate=self.tax_rate,
            is_taxable=self.is_taxable,
            hs_code=self.hs_code,
            country_of_origin=self.country_of_origin,
        )

    def deactivate(
        self,
        deactivated_by: UUID,
        reason: str | None = None,
        deactivated_at: datetime | None = None,
    ) -> ItemEntity:
        """Deactivate the item."""
        if self.current_stock > 0:
            raise ValueError("Cannot deactivate item with current stock")
        now = deactivated_at or datetime.now(UTC)
        return ItemEntity(
            id=self.id,
            legal_entity_id=self.legal_entity_id,
            sku=self.sku,
            name=self.name,
            description=self.description,
            item_type=self.item_type,
            unit_of_measure=self.unit_of_measure,
            current_stock=self.current_stock,
            current_stock_value=self.current_stock_value,
            average_cost=self.average_cost,
            last_cost=self.last_cost,
            reorder_point=self.reorder_point,
            safety_stock=self.safety_stock,
            maximum_stock=self.maximum_stock,
            minimum_stock=self.minimum_stock,
            status=ItemStatus.INACTIVE,
            standard_cost=self.standard_cost,
            selling_price=self.selling_price,
            category=self.category,
            warehouse_code=self.warehouse_code,
            created_by=self.created_by,
            created_at=self.created_at,
            updated_at=now,
            updated_by=deactivated_by,
            deactivated_at=now,
            deactivated_by=deactivated_by,
            version=self.version + 1,
            barcode=self.barcode,
            weight_gram=self.weight_gram,
            dimension_cm=self.dimension_cm,
            brand=self.brand,
            lead_time_days=self.lead_time_days,
            reorder_quantity=self.reorder_quantity,
            warehouse_location=self.warehouse_location,
            currency=self.currency,
            valuation_method=self.valuation_method,
            tax_rate=self.tax_rate,
            is_taxable=self.is_taxable,
            hs_code=self.hs_code,
            country_of_origin=self.country_of_origin,
        )

    def mark_obsolete(self, updated_by: UUID) -> ItemEntity:
        """Mark item as obsolete."""
        return ItemEntity(
            id=self.id,
            legal_entity_id=self.legal_entity_id,
            sku=self.sku,
            name=self.name,
            description=self.description,
            item_type=self.item_type,
            unit_of_measure=self.unit_of_measure,
            current_stock=self.current_stock,
            current_stock_value=self.current_stock_value,
            average_cost=self.average_cost,
            last_cost=self.last_cost,
            reorder_point=self.reorder_point,
            safety_stock=self.safety_stock,
            maximum_stock=self.maximum_stock,
            minimum_stock=self.minimum_stock,
            status=ItemStatus.OBSOLETE,
            standard_cost=self.standard_cost,
            selling_price=self.selling_price,
            category=self.category,
            warehouse_code=self.warehouse_code,
            created_by=self.created_by,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            updated_by=updated_by,
            deactivated_at=self.deactivated_at,
            deactivated_by=self.deactivated_by,
            version=self.version + 1,
            barcode=self.barcode,
            weight_gram=self.weight_gram,
            dimension_cm=self.dimension_cm,
            brand=self.brand,
            lead_time_days=self.lead_time_days,
            reorder_quantity=self.reorder_quantity,
            warehouse_location=self.warehouse_location,
            currency=self.currency,
            valuation_method=self.valuation_method,
            tax_rate=self.tax_rate,
            is_taxable=self.is_taxable,
            hs_code=self.hs_code,
            country_of_origin=self.country_of_origin,
        )

    def update_cost(
        self, new_unit_cost: Decimal, updated_by: UUID, effective_date: datetime | None = None
    ) -> ItemEntity:
        """Update the cost of the item."""
        if new_unit_cost < 0:
            raise ValueError("Unit cost cannot be negative")
        now = effective_date or datetime.now(UTC)
        return ItemEntity(
            id=self.id,
            legal_entity_id=self.legal_entity_id,
            sku=self.sku,
            name=self.name,
            description=self.description,
            item_type=self.item_type,
            unit_of_measure=self.unit_of_measure,
            current_stock=self.current_stock,
            current_stock_value=self.current_stock_value,
            average_cost=self.average_cost,
            last_cost=new_unit_cost,
            reorder_point=self.reorder_point,
            safety_stock=self.safety_stock,
            maximum_stock=self.maximum_stock,
            minimum_stock=self.minimum_stock,
            status=self.status,
            standard_cost=new_unit_cost,
            selling_price=self.selling_price,
            category=self.category,
            warehouse_code=self.warehouse_code,
            created_by=self.created_by,
            created_at=self.created_at,
            updated_at=now,
            updated_by=updated_by,
            deactivated_at=self.deactivated_at,
            deactivated_by=self.deactivated_by,
            version=self.version + 1,
            barcode=self.barcode,
            weight_gram=self.weight_gram,
            dimension_cm=self.dimension_cm,
            brand=self.brand,
            lead_time_days=self.lead_time_days,
            reorder_quantity=self.reorder_quantity,
            warehouse_location=self.warehouse_location,
            currency=self.currency,
            valuation_method=self.valuation_method,
            tax_rate=self.tax_rate,
            is_taxable=self.is_taxable,
            hs_code=self.hs_code,
            country_of_origin=self.country_of_origin,
        )

    def update_price(
        self, new_selling_price: Decimal, updated_by: UUID, effective_date: datetime | None = None
    ) -> ItemEntity:
        """Update the selling price of the item."""
        if new_selling_price < 0:
            raise ValueError("Selling price cannot be negative")
        now = effective_date or datetime.now(UTC)
        return ItemEntity(
            id=self.id,
            legal_entity_id=self.legal_entity_id,
            sku=self.sku,
            name=self.name,
            description=self.description,
            item_type=self.item_type,
            unit_of_measure=self.unit_of_measure,
            current_stock=self.current_stock,
            current_stock_value=self.current_stock_value,
            average_cost=self.average_cost,
            last_cost=self.last_cost,
            reorder_point=self.reorder_point,
            safety_stock=self.safety_stock,
            maximum_stock=self.maximum_stock,
            minimum_stock=self.minimum_stock,
            status=self.status,
            standard_cost=self.standard_cost,
            selling_price=new_selling_price,
            category=self.category,
            warehouse_code=self.warehouse_code,
            created_by=self.created_by,
            created_at=self.created_at,
            updated_at=now,
            updated_by=updated_by,
            deactivated_at=self.deactivated_at,
            deactivated_by=self.deactivated_by,
            version=self.version + 1,
            barcode=self.barcode,
            weight_gram=self.weight_gram,
            dimension_cm=self.dimension_cm,
            brand=self.brand,
            lead_time_days=self.lead_time_days,
            reorder_quantity=self.reorder_quantity,
            warehouse_location=self.warehouse_location,
            currency=self.currency,
            valuation_method=self.valuation_method,
            tax_rate=self.tax_rate,
            is_taxable=self.is_taxable,
            hs_code=self.hs_code,
            country_of_origin=self.country_of_origin,
        )

    def update_reorder_point(self, new_reorder_point: Decimal, updated_by: UUID) -> ItemEntity:
        """Update reorder point."""
        if new_reorder_point < 0:
            raise ValueError("Reorder point cannot be negative")
        return ItemEntity(
            id=self.id,
            legal_entity_id=self.legal_entity_id,
            sku=self.sku,
            name=self.name,
            description=self.description,
            item_type=self.item_type,
            unit_of_measure=self.unit_of_measure,
            current_stock=self.current_stock,
            current_stock_value=self.current_stock_value,
            average_cost=self.average_cost,
            last_cost=self.last_cost,
            reorder_point=new_reorder_point,
            safety_stock=self.safety_stock,
            maximum_stock=self.maximum_stock,
            minimum_stock=self.minimum_stock,
            status=self.status,
            standard_cost=self.standard_cost,
            selling_price=self.selling_price,
            category=self.category,
            warehouse_code=self.warehouse_code,
            created_by=self.created_by,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            updated_by=updated_by,
            deactivated_at=self.deactivated_at,
            deactivated_by=self.deactivated_by,
            version=self.version + 1,
            barcode=self.barcode,
            weight_gram=self.weight_gram,
            dimension_cm=self.dimension_cm,
            brand=self.brand,
            lead_time_days=self.lead_time_days,
            reorder_quantity=self.reorder_quantity,
            warehouse_location=self.warehouse_location,
            currency=self.currency,
            valuation_method=self.valuation_method,
            tax_rate=self.tax_rate,
            is_taxable=self.is_taxable,
            hs_code=self.hs_code,
            country_of_origin=self.country_of_origin,
        )

    def update_safety_stock(self, new_safety_stock: Decimal, updated_by: UUID) -> ItemEntity:
        """Update safety stock level."""
        if new_safety_stock < 0:
            raise ValueError("Safety stock cannot be negative")
        return ItemEntity(
            id=self.id,
            legal_entity_id=self.legal_entity_id,
            sku=self.sku,
            name=self.name,
            description=self.description,
            item_type=self.item_type,
            unit_of_measure=self.unit_of_measure,
            current_stock=self.current_stock,
            current_stock_value=self.current_stock_value,
            average_cost=self.average_cost,
            last_cost=self.last_cost,
            reorder_point=self.reorder_point,
            safety_stock=new_safety_stock,
            maximum_stock=self.maximum_stock,
            minimum_stock=self.minimum_stock,
            status=self.status,
            standard_cost=self.standard_cost,
            selling_price=self.selling_price,
            category=self.category,
            warehouse_code=self.warehouse_code,
            created_by=self.created_by,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            updated_by=updated_by,
            deactivated_at=self.deactivated_at,
            deactivated_by=self.deactivated_by,
            version=self.version + 1,
            barcode=self.barcode,
            weight_gram=self.weight_gram,
            dimension_cm=self.dimension_cm,
            brand=self.brand,
            lead_time_days=self.lead_time_days,
            reorder_quantity=self.reorder_quantity,
            warehouse_location=self.warehouse_location,
            currency=self.currency,
            valuation_method=self.valuation_method,
            tax_rate=self.tax_rate,
            is_taxable=self.is_taxable,
            hs_code=self.hs_code,
            country_of_origin=self.country_of_origin,
        )

    def update_category(self, new_category: str | None, updated_by: UUID) -> ItemEntity:
        """Update item category."""
        return ItemEntity(
            id=self.id,
            legal_entity_id=self.legal_entity_id,
            sku=self.sku,
            name=self.name,
            description=self.description,
            item_type=self.item_type,
            unit_of_measure=self.unit_of_measure,
            current_stock=self.current_stock,
            current_stock_value=self.current_stock_value,
            average_cost=self.average_cost,
            last_cost=self.last_cost,
            reorder_point=self.reorder_point,
            safety_stock=self.safety_stock,
            maximum_stock=self.maximum_stock,
            minimum_stock=self.minimum_stock,
            status=self.status,
            standard_cost=self.standard_cost,
            selling_price=self.selling_price,
            category=new_category,
            warehouse_code=self.warehouse_code,
            created_by=self.created_by,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            updated_by=updated_by,
            deactivated_at=self.deactivated_at,
            deactivated_by=self.deactivated_by,
            version=self.version + 1,
            barcode=self.barcode,
            weight_gram=self.weight_gram,
            dimension_cm=self.dimension_cm,
            brand=self.brand,
            lead_time_days=self.lead_time_days,
            reorder_quantity=self.reorder_quantity,
            warehouse_location=self.warehouse_location,
            currency=self.currency,
            valuation_method=self.valuation_method,
            tax_rate=self.tax_rate,
            is_taxable=self.is_taxable,
            hs_code=self.hs_code,
            country_of_origin=self.country_of_origin,
        )

    def rename(self, new_name: str, updated_by: UUID) -> ItemEntity:
        """Rename the item."""
        if not new_name or len(new_name.strip()) < 3:
            raise ValueError("Name must be at least 3 characters")
        return ItemEntity(
            id=self.id,
            legal_entity_id=self.legal_entity_id,
            sku=self.sku,
            name=new_name,
            description=self.description,
            item_type=self.item_type,
            unit_of_measure=self.unit_of_measure,
            current_stock=self.current_stock,
            current_stock_value=self.current_stock_value,
            average_cost=self.average_cost,
            last_cost=self.last_cost,
            reorder_point=self.reorder_point,
            safety_stock=self.safety_stock,
            maximum_stock=self.maximum_stock,
            minimum_stock=self.minimum_stock,
            status=self.status,
            standard_cost=self.standard_cost,
            selling_price=self.selling_price,
            category=self.category,
            warehouse_code=self.warehouse_code,
            created_by=self.created_by,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            updated_by=updated_by,
            deactivated_at=self.deactivated_at,
            deactivated_by=self.deactivated_by,
            version=self.version + 1,
            barcode=self.barcode,
            weight_gram=self.weight_gram,
            dimension_cm=self.dimension_cm,
            brand=self.brand,
            lead_time_days=self.lead_time_days,
            reorder_quantity=self.reorder_quantity,
            warehouse_location=self.warehouse_location,
            currency=self.currency,
            valuation_method=self.valuation_method,
            tax_rate=self.tax_rate,
            is_taxable=self.is_taxable,
            hs_code=self.hs_code,
            country_of_origin=self.country_of_origin,
        )

    def update_description(self, new_description: str | None, updated_by: UUID) -> ItemEntity:
        """Update item description."""
        return ItemEntity(
            id=self.id,
            legal_entity_id=self.legal_entity_id,
            sku=self.sku,
            name=self.name,
            description=new_description,
            item_type=self.item_type,
            unit_of_measure=self.unit_of_measure,
            current_stock=self.current_stock,
            current_stock_value=self.current_stock_value,
            average_cost=self.average_cost,
            last_cost=self.last_cost,
            reorder_point=self.reorder_point,
            safety_stock=self.safety_stock,
            maximum_stock=self.maximum_stock,
            minimum_stock=self.minimum_stock,
            status=self.status,
            standard_cost=self.standard_cost,
            selling_price=self.selling_price,
            category=self.category,
            warehouse_code=self.warehouse_code,
            created_by=self.created_by,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            updated_by=updated_by,
            deactivated_at=self.deactivated_at,
            deactivated_by=self.deactivated_by,
            version=self.version + 1,
            barcode=self.barcode,
            weight_gram=self.weight_gram,
            dimension_cm=self.dimension_cm,
            brand=self.brand,
            lead_time_days=self.lead_time_days,
            reorder_quantity=self.reorder_quantity,
            warehouse_location=self.warehouse_location,
            currency=self.currency,
            valuation_method=self.valuation_method,
            tax_rate=self.tax_rate,
            is_taxable=self.is_taxable,
            hs_code=self.hs_code,
            country_of_origin=self.country_of_origin,
        )

    def update_standard_cost(self, new_standard_cost: Decimal, updated_by: UUID) -> ItemEntity:
        """Update standard cost."""
        return self.update_cost(new_standard_cost, updated_by)

    def update_selling_price(self, new_selling_price: Decimal, updated_by: UUID) -> ItemEntity:
        """Update selling price."""
        return self.update_price(new_selling_price, updated_by)

    def update_tax_rate(self, new_tax_rate: Decimal, updated_by: UUID) -> ItemEntity:
        """Update tax rate."""
        if new_tax_rate < 0 or new_tax_rate > 100:
            raise ValueError(f"Tax rate must be between 0 and 100: {new_tax_rate}")
        return ItemEntity(
            id=self.id,
            legal_entity_id=self.legal_entity_id,
            sku=self.sku,
            name=self.name,
            description=self.description,
            item_type=self.item_type,
            unit_of_measure=self.unit_of_measure,
            current_stock=self.current_stock,
            current_stock_value=self.current_stock_value,
            average_cost=self.average_cost,
            last_cost=self.last_cost,
            reorder_point=self.reorder_point,
            safety_stock=self.safety_stock,
            maximum_stock=self.maximum_stock,
            minimum_stock=self.minimum_stock,
            status=self.status,
            standard_cost=self.standard_cost,
            selling_price=self.selling_price,
            category=self.category,
            warehouse_code=self.warehouse_code,
            created_by=self.created_by,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            updated_by=updated_by,
            deactivated_at=self.deactivated_at,
            deactivated_by=self.deactivated_by,
            version=self.version + 1,
            barcode=self.barcode,
            weight_gram=self.weight_gram,
            dimension_cm=self.dimension_cm,
            brand=self.brand,
            lead_time_days=self.lead_time_days,
            reorder_quantity=self.reorder_quantity,
            warehouse_location=self.warehouse_location,
            currency=self.currency,
            valuation_method=self.valuation_method,
            tax_rate=new_tax_rate,
            is_taxable=self.is_taxable,
            hs_code=self.hs_code,
            country_of_origin=self.country_of_origin,
        )

    def update_valuation_method(self, new_method: str, updated_by: UUID) -> ItemEntity:
        """Update valuation method."""
        return ItemEntity(
            id=self.id,
            legal_entity_id=self.legal_entity_id,
            sku=self.sku,
            name=self.name,
            description=self.description,
            item_type=self.item_type,
            unit_of_measure=self.unit_of_measure,
            current_stock=self.current_stock,
            current_stock_value=self.current_stock_value,
            average_cost=self.average_cost,
            last_cost=self.last_cost,
            reorder_point=self.reorder_point,
            safety_stock=self.safety_stock,
            maximum_stock=self.maximum_stock,
            minimum_stock=self.minimum_stock,
            status=self.status,
            standard_cost=self.standard_cost,
            selling_price=self.selling_price,
            category=self.category,
            warehouse_code=self.warehouse_code,
            created_by=self.created_by,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            updated_by=updated_by,
            deactivated_at=self.deactivated_at,
            deactivated_by=self.deactivated_by,
            version=self.version + 1,
            barcode=self.barcode,
            weight_gram=self.weight_gram,
            dimension_cm=self.dimension_cm,
            brand=self.brand,
            lead_time_days=self.lead_time_days,
            reorder_quantity=self.reorder_quantity,
            warehouse_location=self.warehouse_location,
            currency=self.currency,
            valuation_method=new_method,
            tax_rate=self.tax_rate,
            is_taxable=self.is_taxable,
            hs_code=self.hs_code,
            country_of_origin=self.country_of_origin,
        )

    # ==================== VALUE OBJECT METHODS ====================

    def normalize(self) -> ItemEntity:
        """Normalize the item (trim strings, round decimals)."""
        return ItemEntity(
            id=self.id,
            legal_entity_id=self.legal_entity_id,
            sku=self.sku.strip().upper(),
            name=self.name.strip().title(),
            description=self.description.strip() if self.description else None,
            item_type=self.item_type,
            unit_of_measure=self.unit_of_measure,
            current_stock=self.current_stock.quantize(Decimal("0.001")),
            current_stock_value=self.current_stock_value.quantize(Decimal("0.01")),
            average_cost=self.average_cost.quantize(Decimal("0.01")),
            last_cost=self.last_cost.quantize(Decimal("0.01")),
            reorder_point=self.reorder_point.quantize(Decimal("0.001")),
            safety_stock=self.safety_stock.quantize(Decimal("0.001")),
            maximum_stock=self.maximum_stock.quantize(Decimal("0.001"))
            if self.maximum_stock
            else None,
            minimum_stock=self.minimum_stock.quantize(Decimal("0.001"))
            if self.minimum_stock
            else None,
            status=self.status,
            standard_cost=self.standard_cost.quantize(Decimal("0.01")),
            selling_price=self.selling_price.quantize(Decimal("0.01")),
            category=self.category.strip() if self.category else None,
            warehouse_code=self.warehouse_code.strip().upper() if self.warehouse_code else None,
            created_by=self.created_by,
            created_at=self.created_at,
            updated_at=self.updated_at,
            updated_by=self.updated_by,
            deactivated_at=self.deactivated_at,
            deactivated_by=self.deactivated_by,
            version=self.version,
            barcode=self.barcode.strip() if self.barcode else None,
            weight_gram=self.weight_gram.quantize(Decimal("0.001")) if self.weight_gram else None,
            dimension_cm=self.dimension_cm.strip() if self.dimension_cm else None,
            brand=self.brand.strip() if self.brand else None,
            lead_time_days=self.lead_time_days,
            reorder_quantity=self.reorder_quantity.quantize(Decimal("0.001")),
            warehouse_location=self.warehouse_location.strip() if self.warehouse_location else None,
            currency=self.currency.strip().upper(),
            valuation_method=self.valuation_method.strip().upper()
            if self.valuation_method
            else None,
            tax_rate=self.tax_rate.quantize(Decimal("0.01")),
            is_taxable=self.is_taxable,
            hs_code=self.hs_code.strip() if self.hs_code else None,
            country_of_origin=self.country_of_origin.strip().upper()
            if self.country_of_origin
            else None,
        )

    def clone(self) -> ItemEntity:
        """Create a deep copy of the item."""
        return ItemEntity(
            id=uuid.uuid4(),
            legal_entity_id=self.legal_entity_id,
            sku=self.sku,
            name=self.name,
            description=self.description,
            item_type=self.item_type,
            unit_of_measure=self.unit_of_measure,
            current_stock=Decimal(0),
            current_stock_value=Decimal(0),
            average_cost=self.average_cost,
            last_cost=self.last_cost,
            reorder_point=self.reorder_point,
            safety_stock=self.safety_stock,
            maximum_stock=self.maximum_stock,
            minimum_stock=self.minimum_stock,
            status=ItemStatus.ACTIVE,
            standard_cost=self.standard_cost,
            selling_price=self.selling_price,
            category=self.category,
            warehouse_code=self.warehouse_code,
            created_by=self.created_by,
            created_at=datetime.now(UTC),
            updated_at=None,
            updated_by=None,
            deactivated_at=None,
            deactivated_by=None,
            version=1,
            barcode=self.barcode,
            weight_gram=self.weight_gram,
            dimension_cm=self.dimension_cm,
            brand=self.brand,
            lead_time_days=self.lead_time_days,
            reorder_quantity=self.reorder_quantity,
            warehouse_location=self.warehouse_location,
            currency=self.currency,
            valuation_method=self.valuation_method,
            tax_rate=self.tax_rate,
            is_taxable=self.is_taxable,
            hs_code=self.hs_code,
            country_of_origin=self.country_of_origin,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": str(self.id),
            "legal_entity_id": str(self.legal_entity_id),
            "sku": self.sku,
            "name": self.name,
            "description": self.description,
            "item_type": self.item_type.value,
            "unit_of_measure": self.unit_of_measure.value,
            "current_stock": str(self.current_stock),
            "current_stock_value": str(self.current_stock_value),
            "average_cost": str(self.average_cost),
            "last_cost": str(self.last_cost),
            "reorder_point": str(self.reorder_point),
            "safety_stock": str(self.safety_stock),
            "maximum_stock": str(self.maximum_stock) if self.maximum_stock else None,
            "minimum_stock": str(self.minimum_stock) if self.minimum_stock else None,
            "status": self.status.value,
            "standard_cost": str(self.standard_cost),
            "selling_price": str(self.selling_price),
            "category": self.category,
            "warehouse_code": self.warehouse_code,
            "created_at": self.created_at.isoformat(),
            "created_by": str(self.created_by),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "updated_by": str(self.updated_by) if self.updated_by else None,
            "deactivated_at": self.deactivated_at.isoformat() if self.deactivated_at else None,
            "deactivated_by": str(self.deactivated_by) if self.deactivated_by else None,
            "version": self.version,
            "barcode": self.barcode,
            "weight_gram": str(self.weight_gram) if self.weight_gram else None,
            "dimension_cm": self.dimension_cm,
            "brand": self.brand,
            "lead_time_days": self.lead_time_days,
            "reorder_quantity": str(self.reorder_quantity),
            "warehouse_location": self.warehouse_location,
            "currency": self.currency,
            "valuation_method": self.valuation_method,
            "tax_rate": str(self.tax_rate),
            "is_taxable": self.is_taxable,
            "hs_code": self.hs_code,
            "country_of_origin": self.country_of_origin,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ItemEntity:
        """Create from dictionary."""
        return cls(
            id=UUID(data["id"]),
            legal_entity_id=UUID(data["legal_entity_id"]),
            sku=data["sku"],
            name=data["name"],
            description=data.get("description"),
            item_type=ItemType.from_string(data.get("item_type", "finished_goods")),
            unit_of_measure=UnitOfMeasure.from_string(data.get("unit_of_measure", "pcs")),
            current_stock=Decimal(data.get("current_stock", "0")),
            current_stock_value=Decimal(data.get("current_stock_value", "0")),
            average_cost=Decimal(data.get("average_cost", "0")),
            last_cost=Decimal(data.get("last_cost", "0")),
            reorder_point=Decimal(data.get("reorder_point", "0")),
            safety_stock=Decimal(data.get("safety_stock", "0")),
            maximum_stock=Decimal(data["maximum_stock"]) if data.get("maximum_stock") else None,
            minimum_stock=Decimal(data["minimum_stock"]) if data.get("minimum_stock") else None,
            status=ItemStatus.from_string(data.get("status", "active")),
            standard_cost=Decimal(data.get("standard_cost", "0")),
            selling_price=Decimal(data.get("selling_price", "0")),
            category=data.get("category"),
            warehouse_code=data.get("warehouse_code"),
            created_by=UUID(data["created_by"]) if data.get("created_by") else uuid.uuid4(),
            created_at=datetime.fromisoformat(data["created_at"])
            if data.get("created_at")
            else datetime.now(UTC),
            updated_at=datetime.fromisoformat(data["updated_at"])
            if data.get("updated_at")
            else None,
            updated_by=UUID(data["updated_by"]) if data.get("updated_by") else None,
            deactivated_at=datetime.fromisoformat(data["deactivated_at"])
            if data.get("deactivated_at")
            else None,
            deactivated_by=UUID(data["deactivated_by"]) if data.get("deactivated_by") else None,
            version=data.get("version", 1),
            barcode=data.get("barcode"),
            weight_gram=Decimal(data["weight_gram"]) if data.get("weight_gram") else None,
            dimension_cm=data.get("dimension_cm"),
            brand=data.get("brand"),
            lead_time_days=data.get("lead_time_days", 0),
            reorder_quantity=Decimal(data.get("reorder_quantity", "0")),
            warehouse_location=data.get("warehouse_location"),
            currency=data.get("currency", "IDR"),
            valuation_method=data.get("valuation_method"),
            tax_rate=Decimal(data.get("tax_rate", "0")),
            is_taxable=data.get("is_taxable", True),
            hs_code=data.get("hs_code"),
            country_of_origin=data.get("country_of_origin"),
        )


# ==================== ALIASES ====================

Item = ItemEntity
InventoryItemEntity = ItemEntity
InventoryItem = ItemEntity  # Added alias for tests


# ==================== REPOSITORY PROTOCOL ====================


class ItemRepository:
    """Repository protocol for ItemEntity."""

    async def get_by_id(self, item_id: UUID, legal_entity_id: UUID) -> ItemEntity | None:
        raise NotImplementedError

    async def get_by_sku(self, sku: str, legal_entity_id: UUID) -> ItemEntity | None:
        raise NotImplementedError

    async def get_by_barcode(self, barcode: str, legal_entity_id: UUID) -> ItemEntity | None:
        raise NotImplementedError

    async def list_by_type(
        self, item_type: ItemType, legal_entity_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[ItemEntity]:
        raise NotImplementedError

    async def list_active(self, legal_entity_id: UUID, limit: int = 1000) -> list[ItemEntity]:
        raise NotImplementedError

    async def list_by_category(
        self, category: str, legal_entity_id: UUID, limit: int = 100
    ) -> list[ItemEntity]:
        raise NotImplementedError

    async def list_by_valuation_method(
        self, method: str, legal_entity_id: UUID, limit: int = 100
    ) -> list[ItemEntity]:
        raise NotImplementedError

    async def search(
        self,
        legal_entity_id: UUID,
        query: str | None = None,
        item_type: ItemType | None = None,
        status: ItemStatus | None = None,
        category: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ItemEntity]:
        raise NotImplementedError

    async def count(
        self,
        legal_entity_id: UUID,
        item_type: ItemType | None = None,
        status: ItemStatus | None = None,
        category: str | None = None,
    ) -> int:
        raise NotImplementedError

    async def save(self, item: ItemEntity) -> None:
        raise NotImplementedError

    async def delete(self, item_id: UUID, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    async def exists(self, sku: str, legal_entity_id: UUID) -> bool:
        raise NotImplementedError


__all__ = [
    "InventoryItem",
    "InventoryItemEntity",
    "Item",
    "ItemEntity",
    "ItemRepository",
    "ItemStatus",
    "ItemType",
    "UnitOfMeasure",
    "ValuationMethod",
]
