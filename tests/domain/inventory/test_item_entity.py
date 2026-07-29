# tests/domain/inventory/test_item_entity.py
"""
Comprehensive unit tests for domain/inventory/item_entity.py.
Covers all enums, constructors, validation, properties, business methods,
serialization, and repository protocol. All datetime is mocked for determinism.
"""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from domain.inventory.item_entity import (
    ItemEntity,
    ItemRepository,
    ItemStatus,
    ItemType,
    UnitOfMeasure,
    ValuationMethod,
)

# ============================================================================
# Fixed datetime to avoid flaky tests
# ============================================================================

FIXED_NOW = datetime(2026, 7, 23, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def mock_datetime_now():
    """Mock datetime.now in item_entity to fixed time."""
    with patch("domain.inventory.item_entity.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.UTC = UTC
        yield mock_dt


@pytest.fixture
def valid_item_kwargs():
    return {
        "id": uuid4(),
        "legal_entity_id": uuid4(),
        "sku": "SKU-001",
        "name": "Test Item",
        "description": "A test item",
        "item_type": ItemType.FINISHED_GOODS,
        "unit_of_measure": UnitOfMeasure.PCS,
        "current_stock": Decimal("10"),
        "current_stock_value": Decimal("100"),
        "average_cost": Decimal("10"),
        "last_cost": Decimal("10"),
        "reorder_point": Decimal("5"),
        "safety_stock": Decimal("2"),
        "maximum_stock": Decimal("20"),
        "minimum_stock": Decimal("1"),
        "status": ItemStatus.ACTIVE,
        "standard_cost": Decimal("10"),
        "selling_price": Decimal("20"),
        "category": "Electronics",
        "warehouse_code": "WH-01",
        "created_by": uuid4(),
        "created_at": FIXED_NOW,
        "updated_at": FIXED_NOW,
        "updated_by": uuid4(),
        "deactivated_at": None,
        "deactivated_by": None,
        "version": 1,
        "barcode": "1234567890",
        "weight_gram": Decimal("100"),
        "dimension_cm": "10x10x10",
        "brand": "BrandX",
        "lead_time_days": 5,
        "reorder_quantity": Decimal("5"),
        "warehouse_location": "Aisle 1",
        "currency": "IDR",
        "valuation_method": "FIFO",
        "tax_rate": Decimal("11"),
        "is_taxable": True,
        "hs_code": "8471.30",
        "country_of_origin": "IDN",
    }


@pytest.fixture
def item(valid_item_kwargs):
    return ItemEntity(**valid_item_kwargs)


# ============================================================================
# Enum tests
# ============================================================================

class TestItemType:
    def test_members(self):
        assert ItemType.RAW_MATERIAL.value == "raw_material"
        assert ItemType.FINISHED_GOODS.value == "finished_goods"
        assert ItemType.PACKAGING.value == "packaging"

    def test_from_string(self):
        assert ItemType.from_string("raw_material") == ItemType.RAW_MATERIAL
        assert ItemType.from_string("FINISHED_GOODS") == ItemType.FINISHED_GOODS
        assert ItemType.from_string("packaging") == ItemType.PACKAGING
        # Unknown defaults to FINISHED_GOODS
        assert ItemType.from_string("unknown") == ItemType.FINISHED_GOODS

    def test_is_inventoriable(self):
        assert ItemType.RAW_MATERIAL.is_inventoriable is True
        assert ItemType.WORK_IN_PROGRESS.is_inventoriable is True
        assert ItemType.FINISHED_GOODS.is_inventoriable is True
        assert ItemType.PACKAGING.is_inventoriable is True
        assert ItemType.SUPPLIES.is_inventoriable is True
        assert ItemType.TRADING.is_inventoriable is True
        assert ItemType.ASSET.is_inventoriable is False
        assert ItemType.SERVICE.is_inventoriable is False


class TestItemStatus:
    def test_members(self):
        assert ItemStatus.ACTIVE.value == "active"
        assert ItemStatus.INACTIVE.value == "inactive"
        assert ItemStatus.DISCONTINUED.value == "discontinued"
        assert ItemStatus.OBSOLETE.value == "obsolete"

    def test_from_string(self):
        assert ItemStatus.from_string("active") == ItemStatus.ACTIVE
        assert ItemStatus.from_string("INACTIVE") == ItemStatus.INACTIVE
        assert ItemStatus.from_string("discontinued") == ItemStatus.DISCONTINUED
        assert ItemStatus.from_string("OBSOLETE") == ItemStatus.OBSOLETE
        # Unknown defaults to ACTIVE
        assert ItemStatus.from_string("unknown") == ItemStatus.ACTIVE


class TestUnitOfMeasure:
    def test_members(self):
        assert UnitOfMeasure.PCS.value == "pcs"
        assert UnitOfMeasure.KG.value == "kg"
        assert UnitOfMeasure.LITER.value == "liter"

    def test_from_string(self):
        assert UnitOfMeasure.from_string("pcs") == UnitOfMeasure.PCS
        assert UnitOfMeasure.from_string("KG") == UnitOfMeasure.KG
        assert UnitOfMeasure.from_string("LITER") == UnitOfMeasure.LITER
        # Unknown defaults to PCS
        assert UnitOfMeasure.from_string("unknown") == UnitOfMeasure.PCS


class TestValuationMethod:
    def test_members(self):
        assert ValuationMethod.FIFO.value == "FIFO"
        assert ValuationMethod.LIFO.value == "LIFO"

    def test_from_string(self):
        assert ValuationMethod.from_string("FIFO") == ValuationMethod.FIFO
        assert ValuationMethod.from_string("LIFO") == ValuationMethod.LIFO
        assert ValuationMethod.from_string("AVERAGE") == ValuationMethod.AVERAGE
        # Unknown defaults to FIFO
        assert ValuationMethod.from_string("unknown") == ValuationMethod.FIFO

    def test_calculate_cost(self):
        method = ValuationMethod.FIFO
        result = method.calculate_cost(Decimal("5"), Decimal("100"))
        assert result == Decimal("500")

    def test_calculate_value(self):
        method = ValuationMethod.FIFO
        result = method.calculate_value(Decimal("5"), Decimal("100"))
        assert result == Decimal("500")


# ============================================================================
# ItemEntity Construction & Validation
# ============================================================================

class TestItemEntityConstruction:
    def test_construction_valid(self, valid_item_kwargs):
        item = ItemEntity(**valid_item_kwargs)
        assert item.id == valid_item_kwargs["id"]
        assert item.sku == valid_item_kwargs["sku"]
        assert item.name == valid_item_kwargs["name"]
        assert item.status == ItemStatus.ACTIVE
        assert item.version == 1

    def test_validation_invalid_sku(self):
        kwargs = valid_item_kwargs()
        kwargs["sku"] = "A"
        with pytest.raises(ValueError, match="SKU must be at least 2 characters"):
            ItemEntity(**kwargs)

    def test_validation_invalid_name(self):
        kwargs = valid_item_kwargs()
        kwargs["name"] = "A"
        with pytest.raises(ValueError, match="Item name must be at least 2 characters"):
            ItemEntity(**kwargs)

    def test_validation_negative_current_stock(self):
        kwargs = valid_item_kwargs()
        kwargs["current_stock"] = Decimal("-1")
        with pytest.raises(ValueError, match="Current stock cannot be negative"):
            ItemEntity(**kwargs)

    def test_validation_negative_current_stock_value(self):
        kwargs = valid_item_kwargs()
        kwargs["current_stock_value"] = Decimal("-1")
        with pytest.raises(ValueError, match="Current stock value cannot be negative"):
            ItemEntity(**kwargs)

    def test_validation_negative_average_cost(self):
        kwargs = valid_item_kwargs()
        kwargs["average_cost"] = Decimal("-1")
        with pytest.raises(ValueError, match="Average cost cannot be negative"):
            ItemEntity(**kwargs)

    def test_validation_negative_standard_cost(self):
        kwargs = valid_item_kwargs()
        kwargs["standard_cost"] = Decimal("-1")
        with pytest.raises(ValueError, match="Standard cost cannot be negative"):
            ItemEntity(**kwargs)

    def test_validation_negative_selling_price(self):
        kwargs = valid_item_kwargs()
        kwargs["selling_price"] = Decimal("-1")
        with pytest.raises(ValueError, match="Selling price cannot be negative"):
            ItemEntity(**kwargs)

    def test_validation_negative_reorder_point(self):
        kwargs = valid_item_kwargs()
        kwargs["reorder_point"] = Decimal("-1")
        with pytest.raises(ValueError, match="Reorder point cannot be negative"):
            ItemEntity(**kwargs)

    def test_validation_negative_safety_stock(self):
        kwargs = valid_item_kwargs()
        kwargs["safety_stock"] = Decimal("-1")
        with pytest.raises(ValueError, match="Safety stock cannot be negative"):
            ItemEntity(**kwargs)

    def test_validation_negative_reorder_quantity(self):
        kwargs = valid_item_kwargs()
        kwargs["reorder_quantity"] = Decimal("-1")
        with pytest.raises(ValueError, match="Reorder quantity cannot be negative"):
            ItemEntity(**kwargs)

    def test_validation_negative_lead_time(self):
        kwargs = valid_item_kwargs()
        kwargs["lead_time_days"] = -5
        with pytest.raises(ValueError, match="Lead time days cannot be negative"):
            ItemEntity(**kwargs)

    def test_validation_tax_rate_out_of_range(self):
        kwargs = valid_item_kwargs()
        kwargs["tax_rate"] = Decimal("101")
        with pytest.raises(ValueError, match="Tax rate must be between 0 and 100"):
            ItemEntity(**kwargs)
        kwargs["tax_rate"] = Decimal("-1")
        with pytest.raises(ValueError, match="Tax rate must be between 0 and 100"):
            ItemEntity(**kwargs)

    def test_validate_method(self, item):
        errors = item.validate()
        assert errors == []

        # Make invalid
        item.sku = "A"
        errors2 = item.validate()
        assert len(errors2) == 1
        assert "SKU must be at least 2 characters" in errors2[0]


# ============================================================================
# ItemEntity Properties
# ============================================================================

class TestItemEntityProperties:
    def test_item_id(self, item):
        assert item.item_id == item.id

    def test_unit_cost(self, item):
        assert item.unit_cost == item.standard_cost

    def test_is_active(self, item):
        assert item.is_active is True
        item.status = ItemStatus.INACTIVE
        assert item.is_active is False

    def test_total_stock_value(self, item):
        assert item.total_stock_value == item.current_stock * item.average_cost  # 10 * 10 = 100

    def test_needs_reorder(self, item):
        # current_stock = 10, reorder_point = 5, reorder_quantity = 5
        assert item.needs_reorder is False
        item.current_stock = Decimal("5")
        assert item.needs_reorder is True
        item.reorder_quantity = Decimal("0")
        assert item.needs_reorder is False

    def test_below_safety_stock(self, item):
        assert item.below_safety_stock is False  # 10 >= 2
        item.current_stock = Decimal("1")
        assert item.below_safety_stock is True

    def test_above_maximum_stock(self, item):
        assert item.above_maximum_stock is False  # 10 <= 20
        item.current_stock = Decimal("25")
        assert item.above_maximum_stock is True
        item.maximum_stock = None
        assert item.above_maximum_stock is False

    def test_count(self, item):
        # count returns current_stock (query method)
        assert item.count() == item.current_stock


# ============================================================================
# ItemEntity Business Methods
# ============================================================================

class TestItemEntityBusinessMethods:
    def test_activate(self, item):
        item.status = ItemStatus.INACTIVE
        activated = item.activate(uuid4())
        assert activated.status == ItemStatus.ACTIVE
        assert activated.version == item.version + 1
        assert activated.updated_at == FIXED_NOW
        assert activated.deactivated_at is None

    def test_deactivate_ok(self, item):
        item.current_stock = Decimal("0")
        deactivated = item.deactivate(uuid4())
        assert deactivated.status == ItemStatus.INACTIVE
        assert deactivated.version == item.version + 1
        assert deactivated.deactivated_at == FIXED_NOW
        assert deactivated.deactivated_by is not None

    def test_deactivate_with_stock_raises(self, item):
        item.current_stock = Decimal("1")
        with pytest.raises(ValueError, match="Cannot deactivate item with current stock"):
            item.deactivate(uuid4())

    def test_mark_obsolete(self, item):
        obsolete = item.mark_obsolete(uuid4())
        assert obsolete.status == ItemStatus.OBSOLETE
        assert obsolete.version == item.version + 1
        assert obsolete.updated_at == FIXED_NOW

    def test_update_cost(self, item):
        new_cost = Decimal("15")
        updated = item.update_cost(new_cost, uuid4())
        assert updated.last_cost == new_cost
        assert updated.standard_cost == new_cost
        assert updated.version == item.version + 1
        assert updated.updated_at == FIXED_NOW

    def test_update_cost_negative_raises(self, item):
        with pytest.raises(ValueError, match="Unit cost cannot be negative"):
            item.update_cost(Decimal("-1"), uuid4())

    def test_update_price(self, item):
        new_price = Decimal("25")
        updated = item.update_price(new_price, uuid4())
        assert updated.selling_price == new_price
        assert updated.version == item.version + 1
        assert updated.updated_at == FIXED_NOW

    def test_update_price_negative_raises(self, item):
        with pytest.raises(ValueError, match="Selling price cannot be negative"):
            item.update_price(Decimal("-1"), uuid4())

    def test_update_reorder_point(self, item):
        new_point = Decimal("7")
        updated = item.update_reorder_point(new_point, uuid4())
        assert updated.reorder_point == new_point
        assert updated.version == item.version + 1
        assert updated.updated_at == FIXED_NOW

    def test_update_reorder_point_negative_raises(self, item):
        with pytest.raises(ValueError, match="Reorder point cannot be negative"):
            item.update_reorder_point(Decimal("-1"), uuid4())

    def test_update_safety_stock(self, item):
        new_safety = Decimal("4")
        updated = item.update_safety_stock(new_safety, uuid4())
        assert updated.safety_stock == new_safety
        assert updated.version == item.version + 1
        assert updated.updated_at == FIXED_NOW

    def test_update_safety_stock_negative_raises(self, item):
        with pytest.raises(ValueError, match="Safety stock cannot be negative"):
            item.update_safety_stock(Decimal("-1"), uuid4())

    def test_update_category(self, item):
        new_cat = "New Category"
        updated = item.update_category(new_cat, uuid4())
        assert updated.category == new_cat
        assert updated.version == item.version + 1

    def test_rename(self, item):
        new_name = "New Item Name"
        updated = item.rename(new_name, uuid4())
        assert updated.name == new_name
        assert updated.version == item.version + 1
        assert updated.updated_at == FIXED_NOW

    def test_rename_short_raises(self, item):
        with pytest.raises(ValueError, match="Name must be at least 3 characters"):
            item.rename("AB", uuid4())

    def test_update_description(self, item):
        new_desc = "Updated description"
        updated = item.update_description(new_desc, uuid4())
        assert updated.description == new_desc
        assert updated.version == item.version + 1

    def test_update_standard_cost(self, item):
        # alias for update_cost
        new_cost = Decimal("12")
        updated = item.update_standard_cost(new_cost, uuid4())
        assert updated.standard_cost == new_cost

    def test_update_selling_price(self, item):
        # alias for update_price
        new_price = Decimal("30")
        updated = item.update_selling_price(new_price, uuid4())
        assert updated.selling_price == new_price

    def test_update_tax_rate(self, item):
        new_rate = Decimal("12")
        updated = item.update_tax_rate(new_rate, uuid4())
        assert updated.tax_rate == new_rate
        assert updated.version == item.version + 1

    def test_update_tax_rate_out_of_range_raises(self, item):
        with pytest.raises(ValueError, match="Tax rate must be between 0 and 100"):
            item.update_tax_rate(Decimal("105"), uuid4())

    def test_update_valuation_method(self, item):
        new_method = "LIFO"
        updated = item.update_valuation_method(new_method, uuid4())
        assert updated.valuation_method == new_method
        assert updated.version == item.version + 1


# ============================================================================
# ItemEntity Serialization & Cloning
# ============================================================================

class TestItemEntitySerialization:
    def test_normalize(self, item):
        item.sku = "  sku-001  "
        item.name = "  test item  "
        normalized = item.normalize()
        assert normalized.sku == "SKU-001"
        assert normalized.name == "Test Item"
        # Decimals should be quantized
        assert normalized.current_stock == Decimal("10.000")
        assert normalized.average_cost == Decimal("10.00")

    def test_clone(self, item):
        cloned = item.clone()
        assert cloned.id != item.id
        assert cloned.sku == item.sku
        assert cloned.name == item.name
        assert cloned.current_stock == Decimal("0")
        assert cloned.current_stock_value == Decimal("0")
        assert cloned.version == 1
        assert cloned.status == ItemStatus.ACTIVE

    def test_to_dict(self, item):
        d = item.to_dict()
        assert d["id"] == str(item.id)
        assert d["sku"] == item.sku
        assert d["name"] == item.name
        assert d["current_stock"] == str(item.current_stock)
        assert d["average_cost"] == str(item.average_cost)
        assert d["version"] == item.version

    def test_from_dict(self, item):
        d = item.to_dict()
        # Need to convert ids back to UUID
        d["id"] = str(item.id)
        d["legal_entity_id"] = str(item.legal_entity_id)
        d["created_by"] = str(item.created_by)
        if item.updated_by:
            d["updated_by"] = str(item.updated_by)
        if item.deactivated_by:
            d["deactivated_by"] = str(item.deactivated_by)
        # Ensure date strings
        d["created_at"] = item.created_at.isoformat()
        if item.updated_at:
            d["updated_at"] = item.updated_at.isoformat()
        if item.deactivated_at:
            d["deactivated_at"] = item.deactivated_at.isoformat()
        reconstructed = ItemEntity.from_dict(d)
        assert reconstructed.id == item.id
        assert reconstructed.sku == item.sku
        assert reconstructed.name == item.name
        assert reconstructed.current_stock == item.current_stock
        assert reconstructed.version == item.version


# ============================================================================
# ItemRepository Protocol (abstract, but can be used with mocks)
# ============================================================================

@pytest.mark.asyncio
class TestItemRepository:
    def test_abstract_methods(self):
        repo = ItemRepository()
        with pytest.raises(NotImplementedError):
            repo.get_by_id(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_sku("", uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_barcode("", uuid4())
        with pytest.raises(NotImplementedError):
            repo.list_by_type(ItemType.FINISHED_GOODS, uuid4())
        with pytest.raises(NotImplementedError):
            repo.list_active(uuid4())
        with pytest.raises(NotImplementedError):
            repo.list_by_category("", uuid4())
        with pytest.raises(NotImplementedError):
            repo.list_by_valuation_method("", uuid4())
        with pytest.raises(NotImplementedError):
            repo.search(uuid4())
        with pytest.raises(NotImplementedError):
            repo.count(uuid4())
        with pytest.raises(NotImplementedError):
            repo.save(MagicMock())
        with pytest.raises(NotImplementedError):
            repo.delete(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.exists("", uuid4())

    async def test_mock_usage(self):
        repo = ItemRepository()
        repo.get_by_id = AsyncMock(return_value=MagicMock(spec=ItemEntity))
        result = await repo.get_by_id(uuid4(), uuid4())
        assert result is not None
        repo.save = AsyncMock()
        await repo.save(MagicMock())
        repo.save.assert_called_once()
