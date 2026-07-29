# test_warehouse_vo.py
# ======================
# Comprehensive tests for domain/shared_value_objects/warehouse_vo.py.
# Covers all public methods, properties, factories, transformations,
# serialization, helper functions, and edge cases.

import pytest

from domain.shared_value_objects.warehouse_vo import (
    InvalidWarehouseCodeError,
    InvalidWarehouseNameError,
    WarehouseCode,
    WarehouseCodeVO,
    WarehouseError,
    WarehouseVO,
    filter_active_warehouses,
    find_warehouse_by_code,
    validate_warehouse_code_unique,
    warehouse_code_list,
)


# ----------------------------------------------------------------------
# Exceptions
# ----------------------------------------------------------------------
class TestExceptions:
    def test_warehouse_error(self):
        err = WarehouseError("test")
        assert isinstance(err, ValueError)

    def test_invalid_warehouse_code_error(self):
        err = InvalidWarehouseCodeError("test")
        assert isinstance(err, WarehouseError)

    def test_invalid_warehouse_name_error(self):
        err = InvalidWarehouseNameError("test")
        assert isinstance(err, WarehouseError)


# ----------------------------------------------------------------------
# WarehouseVO - Construction & Validation
# ----------------------------------------------------------------------
class TestWarehouseVOConstruction:
    def test_construction_minimal(self):
        wh = WarehouseVO("WH01", "Main Warehouse")
        assert wh.code == "WH01"
        assert wh.name == "Main Warehouse"
        assert wh.location is None
        assert wh.address is None
        assert wh.phone is None
        assert wh.manager_name is None
        assert wh.is_active is True
        assert wh.metadata is None

    def test_construction_full(self):
        wh = WarehouseVO(
            code="WH-002",
            name="Jakarta Main Warehouse",
            location="Jakarta",
            address="Jl. Sudirman No. 1",
            phone="021-123456",
            manager_name="Budi",
            is_active=False,
            metadata={"zone": "A"},
        )
        assert wh.code == "WH-002"
        assert wh.name == "Jakarta Main Warehouse"
        assert wh.location == "Jakarta"
        assert wh.address == "Jl. Sudirman No. 1"
        assert wh.phone == "021-123456"
        assert wh.manager_name == "Budi"
        assert wh.is_active is False
        assert wh.metadata == {"zone": "A"}

    def test_code_validation_strips_whitespace(self):
        wh = WarehouseVO("  WH01  ", "Main")
        assert wh.code == "WH01"

    def test_code_too_short_raises(self):
        with pytest.raises(InvalidWarehouseCodeError, match="at least 2 characters"):
            WarehouseVO("A", "Main")

    def test_code_too_long_raises(self):
        long_code = "A" * 21
        with pytest.raises(InvalidWarehouseCodeError, match="not exceed 20 characters"):
            WarehouseVO(long_code, "Main")

    def test_code_invalid_characters_raises(self):
        with pytest.raises(InvalidWarehouseCodeError, match="only contain letters, numbers, hyphens, and underscores"):
            WarehouseVO("WH@01", "Main")

    def test_name_strips_whitespace(self):
        wh = WarehouseVO("WH01", "  Main Warehouse  ")
        assert wh.name == "Main Warehouse"

    def test_name_too_short_raises(self):
        with pytest.raises(InvalidWarehouseNameError, match="at least 2 characters"):
            WarehouseVO("WH01", "A")

    def test_name_too_long_raises(self):
        long_name = "A" * 101
        with pytest.raises(InvalidWarehouseNameError, match="not exceed 100 characters"):
            WarehouseVO("WH01", long_name)

    def test_location_too_long_raises(self):
        long_loc = "A" * 101
        with pytest.raises(WarehouseError, match="Location must not exceed 100 characters"):
            WarehouseVO("WH01", "Main", location=long_loc)

    def test_address_too_long_raises(self):
        long_addr = "A" * 501
        with pytest.raises(WarehouseError, match="Address must not exceed 500 characters"):
            WarehouseVO("WH01", "Main", address=long_addr)

    def test_phone_too_long_raises(self):
        long_phone = "1" * 31
        with pytest.raises(WarehouseError, match="Phone number must not exceed 30 characters"):
            WarehouseVO("WH01", "Main", phone=long_phone)

    def test_manager_name_too_long_raises(self):
        long_name = "A" * 101
        with pytest.raises(WarehouseError, match="Manager name must not exceed 100 characters"):
            WarehouseVO("WH01", "Main", manager_name=long_name)

    def test_metadata_not_dict_raises(self):
        with pytest.raises(WarehouseError, match="Metadata must be a dictionary or None"):
            WarehouseVO("WH01", "Main", metadata="not_dict")  # type: ignore


# ----------------------------------------------------------------------
# WarehouseVO - Factory Methods (create, from_dict, from_db_record)
# ----------------------------------------------------------------------
class TestWarehouseVOFactory:
    def test_create(self):
        wh = WarehouseVO.create(
            code="WH01",
            name="Main",
            location="Jakarta",
            address="Jl. Sudirman",
            phone="021-123",
            manager_name="Budi",
            metadata={"zone": "A"},
        )
        assert wh.code == "WH01"
        assert wh.name == "Main"
        assert wh.location == "Jakarta"
        assert wh.address == "Jl. Sudirman"
        assert wh.phone == "021-123"
        assert wh.manager_name == "Budi"
        assert wh.is_active is True
        assert wh.metadata == {"zone": "A"}

    def test_create_with_idempotency_key(self):
        # No side effects, just test that it accepts the param and returns a valid object
        wh = WarehouseVO.create("WH01", "Main", idempotency_key="key-123")
        assert wh.code == "WH01"
        assert wh.name == "Main"

    def test_from_dict(self):
        data = {
            "code": "WH01",
            "name": "Main Warehouse",
            "location": "Jakarta",
            "address": "Jl. Sudirman",
            "phone": "021-123",
            "manager_name": "Budi",
            "is_active": False,
            "metadata": {"zone": "A"},
        }
        wh = WarehouseVO.from_dict(data)
        assert wh.code == "WH01"
        assert wh.name == "Main Warehouse"
        assert wh.location == "Jakarta"
        assert wh.address == "Jl. Sudirman"
        assert wh.phone == "021-123"
        assert wh.manager_name == "Budi"
        assert wh.is_active is False
        assert wh.metadata == {"zone": "A"}

    def test_from_dict_missing_is_active_default_true(self):
        data = {"code": "WH01", "name": "Main"}
        wh = WarehouseVO.from_dict(data)
        assert wh.is_active is True

    def test_from_db_record(self):
        """Test from_db_record - this method was untested."""
        record = {
            "code": "WH01",
            "name": "Main Warehouse",
            "location": "Jakarta",
            "address": "Jl. Sudirman",
            "phone": "021-123",
            "manager_name": "Budi",
            "is_active": True,
            "metadata": {"zone": "A"},
        }
        wh = WarehouseVO.from_db_record(record)
        assert wh.code == "WH01"
        assert wh.name == "Main Warehouse"
        assert wh.location == "Jakarta"
        assert wh.address == "Jl. Sudirman"
        assert wh.phone == "021-123"
        assert wh.manager_name == "Budi"
        assert wh.is_active is True
        assert wh.metadata == {"zone": "A"}

    def test_from_db_record_missing_is_active_default_true(self):
        record = {"code": "WH01", "name": "Main"}
        wh = WarehouseVO.from_db_record(record)
        assert wh.is_active is True


# ----------------------------------------------------------------------
# WarehouseVO - Properties
# ----------------------------------------------------------------------
class TestWarehouseVOProperties:
    def test_display_name(self):
        wh = WarehouseVO("WH01", "Main Warehouse")
        assert wh.display_name == "WH01 - Main Warehouse"

    def test_has_contact_when_phone_exists(self):
        """Test has_contact property - this was untested."""
        wh = WarehouseVO("WH01", "Main", phone="021-123")
        assert wh.has_contact is True

    def test_has_contact_when_manager_name_exists(self):
        wh = WarehouseVO("WH01", "Main", manager_name="Budi")
        assert wh.has_contact is True

    def test_has_contact_when_both_exist(self):
        wh = WarehouseVO("WH01", "Main", phone="021-123", manager_name="Budi")
        assert wh.has_contact is True

    def test_has_contact_when_none(self):
        wh = WarehouseVO("WH01", "Main")
        assert wh.has_contact is False


# ----------------------------------------------------------------------
# WarehouseVO - Transformations (immutable)
# ----------------------------------------------------------------------
class TestWarehouseVOTransformations:
    def test_deactivate(self):
        wh = WarehouseVO("WH01", "Main")
        inactive = wh.deactivate()
        assert inactive.is_active is False
        assert inactive.code == wh.code
        assert inactive is not wh

    def test_deactivate_already_inactive_returns_self(self):
        wh = WarehouseVO("WH01", "Main", is_active=False)
        result = wh.deactivate()
        assert result is wh

    def test_activate(self):
        wh = WarehouseVO("WH01", "Main", is_active=False)
        active = wh.activate()
        assert active.is_active is True
        assert active is not wh

    def test_activate_already_active_returns_self(self):
        wh = WarehouseVO("WH01", "Main")
        result = wh.activate()
        assert result is wh

    def test_rename(self):
        wh = WarehouseVO("WH01", "Old Name")
        renamed = wh.rename("New Name")
        assert renamed.name == "New Name"
        assert renamed.code == wh.code
        assert renamed is not wh

    def test_relocate(self):
        """Test relocate method - this was untested."""
        wh = WarehouseVO("WH01", "Main", location="Old City")
        relocated = wh.relocate("New City")
        assert relocated.location == "New City"
        assert relocated.code == wh.code
        assert relocated.name == wh.name
        assert relocated is not wh

    def test_relocate_with_none(self):
        wh = WarehouseVO("WH01", "Main", location="Jakarta")
        relocated = wh.relocate(None)
        assert relocated.location is None

    def test_update_address(self):
        wh = WarehouseVO("WH01", "Main", address="Old Address")
        updated = wh.update_address("New Address")
        assert updated.address == "New Address"
        assert updated is not wh

    def test_update_contact(self):
        wh = WarehouseVO("WH01", "Main")
        updated = wh.update_contact("081-123", "New Manager")
        assert updated.phone == "081-123"
        assert updated.manager_name == "New Manager"
        assert updated is not wh

    def test_with_metadata(self):
        wh = WarehouseVO("WH01", "Main")
        new_meta = {"key": "value"}
        updated = wh.with_metadata(new_meta)
        assert updated.metadata == new_meta
        assert updated is not wh

    def test_with_metadata_none(self):
        wh = WarehouseVO("WH01", "Main", metadata={"old": "data"})
        updated = wh.with_metadata(None)
        assert updated.metadata is None


# ----------------------------------------------------------------------
# WarehouseVO - Serialization
# ----------------------------------------------------------------------
class TestWarehouseVOSerialization:
    def test_to_dict_with_metadata(self):
        wh = WarehouseVO(
            code="WH01",
            name="Main",
            location="Jakarta",
            address="Jl. Sudirman",
            phone="021-123",
            manager_name="Budi",
            is_active=True,
            metadata={"zone": "A"},
        )
        d = wh.to_dict(include_metadata=True)
        assert d["code"] == "WH01"
        assert d["name"] == "Main"
        assert d["display_name"] == "WH01 - Main"
        assert d["location"] == "Jakarta"
        assert d["address"] == "Jl. Sudirman"
        assert d["phone"] == "021-123"
        assert d["manager_name"] == "Budi"
        assert d["is_active"] is True
        assert d["has_contact"] is True
        assert d["metadata"] == {"zone": "A"}

    def test_to_dict_without_metadata(self):
        wh = WarehouseVO("WH01", "Main", metadata={"zone": "A"})
        d = wh.to_dict(include_metadata=False)
        assert "metadata" not in d

    def test_to_db_record(self):
        wh = WarehouseVO(
            code="WH01",
            name="Main",
            location="Jakarta",
            address="Jl. Sudirman",
            phone="021-123",
            manager_name="Budi",
            is_active=True,
            metadata={"zone": "A"},
        )
        rec = wh.to_db_record()
        assert rec["code"] == "WH01"
        assert rec["name"] == "Main"
        assert rec["location"] == "Jakarta"
        assert rec["address"] == "Jl. Sudirman"
        assert rec["phone"] == "021-123"
        assert rec["manager_name"] == "Budi"
        assert rec["is_active"] is True
        assert rec["metadata"] == {"zone": "A"}


# ----------------------------------------------------------------------
# WarehouseVO - Dunder Methods
# ----------------------------------------------------------------------
class TestWarehouseVODunder:
    def test_str(self):
        wh = WarehouseVO("WH01", "Main")
        assert str(wh) == "WH01 - Main"

    def test_repr(self):
        wh = WarehouseVO("WH01", "Main", is_active=False)
        assert repr(wh) == "WarehouseVO('WH01', 'Main', active=False)"

    def test_equality_based_on_code(self):
        wh1 = WarehouseVO("WH01", "Main")
        wh2 = WarehouseVO("WH01", "Different Name")
        assert wh1 == wh2
        wh3 = WarehouseVO("WH02", "Other")
        assert wh1 != wh3
        assert wh1 != "WH01"

    def test_hash_based_on_code(self):
        wh1 = WarehouseVO("WH01", "Main")
        wh2 = WarehouseVO("WH01", "Other")
        assert hash(wh1) == hash(wh2)

    def test_lt_based_on_code(self):
        wh1 = WarehouseVO("WH01", "Main")
        wh2 = WarehouseVO("WH02", "Other")
        assert wh1 < wh2
        assert not (wh2 < wh1)


# ----------------------------------------------------------------------
# WarehouseCode
# ----------------------------------------------------------------------
class TestWarehouseCode:
    def test_construction_valid(self):
        code = WarehouseCode("WH-01")
        assert code.value == "WH-01"

    def test_construction_strips_whitespace(self):
        code = WarehouseCode("  WH-01  ")
        assert code.value == "WH-01"

    def test_construction_too_short_raises(self):
        with pytest.raises(InvalidWarehouseCodeError, match="at least 2 characters"):
            WarehouseCode("A")

    def test_construction_too_long_raises(self):
        with pytest.raises(InvalidWarehouseCodeError, match="not exceed 20 characters"):
            WarehouseCode("A" * 21)

    def test_construction_invalid_characters_raises(self):
        with pytest.raises(InvalidWarehouseCodeError, match="only contain letters"):
            WarehouseCode("WH@01")

    def test_construction_empty_raises(self):
        with pytest.raises(InvalidWarehouseCodeError, match="non-empty string"):
            WarehouseCode("")

    def test_from_string(self):
        """Test from_string factory method - this was untested."""
        code = WarehouseCode.from_string("WH-01")
        assert code.value == "WH-01"
        assert isinstance(code, WarehouseCode)

    def test_from_string_with_whitespace(self):
        code = WarehouseCode.from_string("  WH-01  ")
        assert code.value == "WH-01"

    def test_str(self):
        code = WarehouseCode("WH01")
        assert str(code) == "WH01"

    def test_repr(self):
        code = WarehouseCode("WH01")
        assert repr(code) == "WarehouseCode('WH01')"

    def test_equality(self):
        code1 = WarehouseCode("WH01")
        code2 = WarehouseCode("WH01")
        code3 = WarehouseCode("WH02")
        assert code1 == code2
        assert code1 != code3
        assert code1 != "WH01"

    def test_hash(self):
        code1 = WarehouseCode("WH01")
        code2 = WarehouseCode("WH01")
        assert hash(code1) == hash(code2)

    def test_to_dict(self):
        code = WarehouseCode("WH01")
        d = code.to_dict()
        assert d == {"warehouse_code": "WH01"}

    def test_alias_warehouse_code_vo(self):
        assert WarehouseCodeVO is WarehouseCode


# ----------------------------------------------------------------------
# Helper Functions
# ----------------------------------------------------------------------
class TestHelperFunctions:
    def test_filter_active_warehouses(self):
        wh1 = WarehouseVO("WH01", "Main", is_active=True)
        wh2 = WarehouseVO("WH02", "Backup", is_active=False)
        wh3 = WarehouseVO("WH03", "Temp", is_active=True)
        active = filter_active_warehouses([wh1, wh2, wh3])
        assert len(active) == 2
        assert wh1 in active
        assert wh3 in active
        assert wh2 not in active

    def test_filter_active_warehouses_empty_list(self):
        assert filter_active_warehouses([]) == []

    def test_find_warehouse_by_code_found(self):
        wh1 = WarehouseVO("WH01", "Main")
        wh2 = WarehouseVO("WH02", "Backup")
        result = find_warehouse_by_code([wh1, wh2], "WH02")
        assert result is wh2

    def test_find_warehouse_by_code_not_found(self):
        wh1 = WarehouseVO("WH01", "Main")
        result = find_warehouse_by_code([wh1], "WH99")
        assert result is None

    def test_warehouse_code_list(self):
        wh1 = WarehouseVO("WH01", "Main")
        wh2 = WarehouseVO("WH02", "Backup")
        codes = warehouse_code_list([wh1, wh2])
        assert codes == ["WH01", "WH02"]

    def test_warehouse_code_list_empty(self):
        assert warehouse_code_list([]) == []

    def test_validate_warehouse_code_unique_true(self):
        assert validate_warehouse_code_unique("WH03", ["WH01", "WH02"]) is True

    def test_validate_warehouse_code_unique_false(self):
        assert validate_warehouse_code_unique("WH01", ["WH01", "WH02"]) is False


# ----------------------------------------------------------------------
# Edge Cases
# ----------------------------------------------------------------------
class TestEdgeCases:
    def test_code_with_underscore_and_hyphen_valid(self):
        wh = WarehouseVO("WH-01_A", "Main")
        assert wh.code == "WH-01_A"

    def test_code_uppercase_conversion_not_forced(self):
        # The validation doesn't convert case, but accepts uppercase
        wh = WarehouseVO("wh01", "Main")
        assert wh.code == "wh01"

    def test_metadata_empty_dict_accepted(self):
        wh = WarehouseVO("WH01", "Main", metadata={})
        assert wh.metadata == {}

    def test_phone_stripped(self):
        wh = WarehouseVO("WH01", "Main", phone="  021-123  ")
        assert wh.phone == "021-123"

    def test_manager_name_stripped(self):
        wh = WarehouseVO("WH01", "Main", manager_name="  Budi  ")
        assert wh.manager_name == "Budi"
