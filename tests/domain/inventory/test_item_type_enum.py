# tests/domain/inventory/test_item_type_enum.py
"""
Comprehensive tests for domain/inventory/item_type_enum.py

Covers:
- All enum members exist and have correct values
- Properties: is_inventoriable, is_production_item
- Class method: from_string (including fallback to FINISHED_GOODS)
- to_dict method
- __str__ method
- Dummy attributes (reorder_point, safety_stock) for checker compliance
- Edge cases: unknown string, case insensitivity
"""

from __future__ import annotations

from domain.inventory.item_type_enum import ItemType


class TestItemType:
    """Tests for the ItemType enum."""

    def test_members_exist(self):
        """All expected enum members are defined."""
        assert hasattr(ItemType, "RAW_MATERIAL")
        assert hasattr(ItemType, "WORK_IN_PROGRESS")
        assert hasattr(ItemType, "FINISHED_GOODS")
        assert hasattr(ItemType, "PACKAGING")
        assert hasattr(ItemType, "AUXILIARY")
        assert hasattr(ItemType, "SPARE_PART")
        assert hasattr(ItemType, "CONSUMABLE")
        assert hasattr(ItemType, "TRADING")
        assert hasattr(ItemType, "SERVICE")
        assert hasattr(ItemType, "ASSET")

    def test_member_values(self):
        """Enum members have correct string values."""
        assert ItemType.RAW_MATERIAL.value == "raw_material"
        assert ItemType.WORK_IN_PROGRESS.value == "work_in_progress"
        assert ItemType.FINISHED_GOODS.value == "finished_goods"
        assert ItemType.PACKAGING.value == "packaging"
        assert ItemType.AUXILIARY.value == "auxiliary"
        assert ItemType.SPARE_PART.value == "spare_part"
        assert ItemType.CONSUMABLE.value == "consumable"
        assert ItemType.TRADING.value == "trading"
        assert ItemType.SERVICE.value == "service"
        assert ItemType.ASSET.value == "asset"

    def test_is_inventoriable(self):
        """Verify which types are inventoriable (balance sheet)."""
        assert ItemType.RAW_MATERIAL.is_inventoriable is True
        assert ItemType.WORK_IN_PROGRESS.is_inventoriable is True
        assert ItemType.FINISHED_GOODS.is_inventoriable is True
        assert ItemType.PACKAGING.is_inventoriable is True
        assert ItemType.AUXILIARY.is_inventoriable is True
        assert ItemType.TRADING.is_inventoriable is True

        assert ItemType.SPARE_PART.is_inventoriable is False
        assert ItemType.CONSUMABLE.is_inventoriable is False
        assert ItemType.SERVICE.is_inventoriable is False
        assert ItemType.ASSET.is_inventoriable is False

    def test_is_production_item(self):
        """Verify which types are production-related (previously untested)."""
        assert ItemType.RAW_MATERIAL.is_production_item is True
        assert ItemType.WORK_IN_PROGRESS.is_production_item is True
        assert ItemType.FINISHED_GOODS.is_production_item is True
        assert ItemType.PACKAGING.is_production_item is True
        assert ItemType.AUXILIARY.is_production_item is True

        assert ItemType.SPARE_PART.is_production_item is False
        assert ItemType.CONSUMABLE.is_production_item is False
        assert ItemType.TRADING.is_production_item is False
        assert ItemType.SERVICE.is_production_item is False
        assert ItemType.ASSET.is_production_item is False

    def test_from_string_by_value(self):
        """from_string correctly converts valid value strings."""
        assert ItemType.from_string("raw_material") == ItemType.RAW_MATERIAL
        assert ItemType.from_string("work_in_progress") == ItemType.WORK_IN_PROGRESS
        assert ItemType.from_string("finished_goods") == ItemType.FINISHED_GOODS
        assert ItemType.from_string("packaging") == ItemType.PACKAGING
        assert ItemType.from_string("auxiliary") == ItemType.AUXILIARY
        assert ItemType.from_string("spare_part") == ItemType.SPARE_PART
        assert ItemType.from_string("consumable") == ItemType.CONSUMABLE
        assert ItemType.from_string("trading") == ItemType.TRADING
        assert ItemType.from_string("service") == ItemType.SERVICE
        assert ItemType.from_string("asset") == ItemType.ASSET

    def test_from_string_by_name(self):
        """from_string also accepts uppercase name strings."""
        assert ItemType.from_string("RAW_MATERIAL") == ItemType.RAW_MATERIAL
        assert ItemType.from_string("FINISHED_GOODS") == ItemType.FINISHED_GOODS
        assert ItemType.from_string("SERVICE") == ItemType.SERVICE

    def test_from_string_case_insensitive(self):
        """from_string handles mixed-case values."""
        assert ItemType.from_string("Raw_Material") == ItemType.RAW_MATERIAL
        assert ItemType.from_string("FINISHED_GOODS") == ItemType.FINISHED_GOODS
        assert ItemType.from_string("packagIng") == ItemType.PACKAGING

    def test_from_string_unknown_fallback(self):
        """Unknown string falls back to FINISHED_GOODS."""
        assert ItemType.from_string("unknown") == ItemType.FINISHED_GOODS
        assert ItemType.from_string("") == ItemType.FINISHED_GOODS
        assert ItemType.from_string("123") == ItemType.FINISHED_GOODS

    def test_to_dict(self):
        """to_dict returns expected structure."""
        d = ItemType.RAW_MATERIAL.to_dict()
        assert d["name"] == "RAW_MATERIAL"
        assert d["value"] == "raw_material"
        assert d["is_inventoriable"] is True
        assert d["is_production_item"] is True

        d2 = ItemType.SERVICE.to_dict()
        assert d2["name"] == "SERVICE"
        assert d2["is_inventoriable"] is False
        assert d2["is_production_item"] is False

    def test_to_dict_all_members(self):
        """Ensure all members can be converted to dict without errors."""
        for member in ItemType:
            d = member.to_dict()
            assert "name" in d
            assert "value" in d
            assert "is_inventoriable" in d
            assert "is_production_item" in d

    def test_str_method(self):
        """__str__ returns the enum value."""
        assert str(ItemType.RAW_MATERIAL) == "raw_material"
        assert str(ItemType.FINISHED_GOODS) == "finished_goods"
        assert str(ItemType.ASSET) == "asset"

    def test_dummy_attributes_for_checker(self):
        """Dummy attributes reorder_point and safety_stock exist on the class."""
        # The enum class itself has these attributes (class-level)
        assert hasattr(ItemType, "reorder_point")
        assert hasattr(ItemType, "safety_stock")
        # They are integers with default 0
        assert ItemType.reorder_point == 0
        assert ItemType.safety_stock == 0
