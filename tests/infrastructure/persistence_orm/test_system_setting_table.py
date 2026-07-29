# tests/infrastructure/persistence_orm/test_system_setting_table.py
"""
Comprehensive tests for infrastructure/persistence_orm/system_setting_table.py.
Covers all properties, methods, and edge cases of SystemSettingTable.
Uses direct instantiation without a DB session for testing model behavior.
Tests typed_value (getter and setter) for all data types, is_global, is_legal_entity_scoped,
validate, reset_to_default, activate, deactivate, and version increments.
"""

import json
from decimal import Decimal
from uuid import uuid4

import pytest

from infrastructure.persistence_orm.system_setting_table import SystemSettingTable

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def sample_setting():
    """Create a SystemSettingTable instance with default values."""
    return SystemSettingTable(
        key="test.setting",
        data_type="string",
        value="test_value",
        description="Test setting",
        category="general",
        scope="global",
        validation_regex=None,
        min_value=None,
        max_value=None,
        allowed_values=None,
        default_value="default_value",
        is_readonly=False,
        is_encrypted=False,
        is_active=True,
        legal_entity_id=None,
        created_by=uuid4(),
        updated_by=uuid4(),
        version=1,
    )


@pytest.fixture
def integer_setting(sample_setting):
    sample_setting.data_type = "integer"
    sample_setting.value = "42"
    return sample_setting


@pytest.fixture
def float_setting(sample_setting):
    sample_setting.data_type = "float"
    sample_setting.value = "3.14159"
    return sample_setting


@pytest.fixture
def boolean_setting(sample_setting):
    sample_setting.data_type = "boolean"
    sample_setting.value = "true"
    return sample_setting


@pytest.fixture
def json_setting(sample_setting):
    sample_setting.data_type = "json"
    sample_setting.value = '{"key": "value"}'
    return sample_setting


@pytest.fixture
def decimal_setting(sample_setting):
    sample_setting.data_type = "decimal"
    sample_setting.value = "123.456"
    return sample_setting


# ============================================================================
# Tests for Table Metadata
# ============================================================================

class TestSystemSettingTableMetadata:
    def test_tablename_defined(self):
        assert hasattr(SystemSettingTable, "__tablename__")
        assert isinstance(SystemSettingTable.__tablename__, str)
        assert len(SystemSettingTable.__tablename__) > 0


# ============================================================================
# Tests for Instantiation
# ============================================================================

class TestSystemSettingTableInstantiation:
    def test_instantiation(self, sample_setting):
        assert isinstance(sample_setting, SystemSettingTable)
        assert sample_setting.key == "test.setting"
        assert sample_setting.data_type == "string"
        assert sample_setting.value == "test_value"
        assert sample_setting.description == "Test setting"
        assert sample_setting.category == "general"
        assert sample_setting.scope == "global"
        assert sample_setting.is_active is True
        assert sample_setting.version == 1


# ============================================================================
# Tests for Properties
# ============================================================================

class TestSystemSettingTableProperties:
    # ---- typed_value getter ----
    def test_typed_value_string(self, sample_setting):
        assert sample_setting.typed_value == "test_value"

    def test_typed_value_integer(self, integer_setting):
        assert integer_setting.typed_value == 42

    def test_typed_value_integer_empty(self, integer_setting):
        integer_setting.value = ""
        assert integer_setting.typed_value == 0

    def test_typed_value_float(self, float_setting):
        assert float_setting.typed_value == Decimal("3.14159")

    def test_typed_value_float_empty(self, float_setting):
        float_setting.value = ""
        assert float_setting.typed_value == Decimal(0)

    def test_typed_value_boolean_true(self, boolean_setting):
        assert boolean_setting.typed_value is True

    def test_typed_value_boolean_false(self, boolean_setting):
        boolean_setting.value = "false"
        assert boolean_setting.typed_value is False

    def test_typed_value_boolean_variants(self, boolean_setting):
        for val in ("1", "yes", "on", "TRUE"):
            boolean_setting.value = val
            assert boolean_setting.typed_value is True
        boolean_setting.value = "0"
        assert boolean_setting.typed_value is False

    def test_typed_value_json(self, json_setting):
        assert json_setting.typed_value == {"key": "value"}

    def test_typed_value_json_empty(self, json_setting):
        json_setting.value = ""
        assert json_setting.typed_value == {}

    def test_typed_value_decimal(self, decimal_setting):
        assert decimal_setting.typed_value == Decimal("123.456")

    def test_typed_value_decimal_empty(self, decimal_setting):
        decimal_setting.value = ""
        assert decimal_setting.typed_value == Decimal(0)

    def test_typed_value_unknown_type_returns_value(self, sample_setting):
        sample_setting.data_type = "unknown"
        assert sample_setting.typed_value == "test_value"

    # ---- typed_value setter ----
    def test_set_typed_value_string(self, sample_setting):
        sample_setting.typed_value = "new_string"
        assert sample_setting.value == "new_string"

    def test_set_typed_value_integer(self, integer_setting):
        integer_setting.typed_value = 100
        assert integer_setting.value == "100"

    def test_set_typed_value_float(self, float_setting):
        float_setting.typed_value = Decimal("2.71828")
        assert float_setting.value == "2.71828"

    def test_set_typed_value_boolean(self, boolean_setting):
        boolean_setting.typed_value = False
        assert boolean_setting.value == "false"
        boolean_setting.typed_value = True
        assert boolean_setting.value == "true"

    def test_set_typed_value_json(self, json_setting):
        json_setting.typed_value = {"a": 1, "b": 2}
        assert json.loads(json_setting.value) == {"a": 1, "b": 2}

    def test_set_typed_value_decimal(self, decimal_setting):
        decimal_setting.typed_value = Decimal("987.654")
        assert decimal_setting.value == "987.654"

    def test_set_typed_value_unknown_type(self, sample_setting):
        sample_setting.data_type = "unknown"
        sample_setting.typed_value = 123
        assert sample_setting.value == "123"

    # ---- is_global and is_legal_entity_scoped ----
    def test_is_global_true(self, sample_setting):
        sample_setting.scope = "global"
        assert sample_setting.is_global is True
        assert sample_setting.is_legal_entity_scoped is False

    def test_is_legal_entity_scoped_true(self, sample_setting):
        sample_setting.scope = "legal_entity"
        assert sample_setting.is_global is False
        assert sample_setting.is_legal_entity_scoped is True


# ============================================================================
# Tests for Methods
# ============================================================================

class TestSystemSettingTableMethods:
    # ---- validate ----
    def test_validate_string_valid(self, sample_setting):
        assert sample_setting.validate("any_string") is True

    def test_validate_integer_valid(self, integer_setting):
        assert integer_setting.validate(42) is True
        assert integer_setting.validate("42") is True

    def test_validate_integer_invalid(self, integer_setting):
        assert integer_setting.validate("not_int") is False

    def test_validate_float_valid(self, float_setting):
        assert float_setting.validate(3.14) is True
        assert float_setting.validate("3.14") is True

    def test_validate_float_invalid(self, float_setting):
        assert float_setting.validate("not_float") is False

    def test_validate_decimal_valid(self, decimal_setting):
        assert decimal_setting.validate(Decimal("123.456")) is True
        assert decimal_setting.validate("123.456") is True

    def test_validate_decimal_invalid(self, decimal_setting):
        assert decimal_setting.validate("not_decimal") is False

    def test_validate_boolean_valid(self, boolean_setting):
        assert boolean_setting.validate(True) is True
        assert boolean_setting.validate("true") is True
        assert boolean_setting.validate(1) is True

    def test_validate_boolean_invalid(self, boolean_setting):
        assert boolean_setting.validate("not_bool") is False

    def test_validate_with_min_value_integer(self, integer_setting):
        integer_setting.min_value = "10"
        assert integer_setting.validate(20) is True
        assert integer_setting.validate(5) is False

    def test_validate_with_min_value_float(self, float_setting):
        float_setting.min_value = "2.0"
        assert float_setting.validate(3.0) is True
        assert float_setting.validate(1.5) is False

    def test_validate_with_min_value_decimal(self, decimal_setting):
        decimal_setting.min_value = "100.0"
        assert decimal_setting.validate(Decimal("150.0")) is True
        assert decimal_setting.validate(Decimal("50.0")) is False

    def test_validate_with_max_value_integer(self, integer_setting):
        integer_setting.max_value = "100"
        assert integer_setting.validate(50) is True
        assert integer_setting.validate(150) is False

    def test_validate_with_max_value_float(self, float_setting):
        float_setting.max_value = "10.0"
        assert float_setting.validate(5.0) is True
        assert float_setting.validate(15.0) is False

    def test_validate_with_allowed_values(self, sample_setting):
        sample_setting.allowed_values = ["a", "b", "c"]
        assert sample_setting.validate("a") is True
        assert sample_setting.validate("d") is False
        # Case insensitive
        assert sample_setting.validate("A") is True

    def test_validate_with_regex(self, sample_setting):
        sample_setting.validation_regex = r"^\d{3}$"
        assert sample_setting.validate("123") is True
        assert sample_setting.validate("12") is False
        assert sample_setting.validate("abc") is False

    # ---- reset_to_default ----
    def test_reset_to_default(self, sample_setting):
        sample_setting.value = "changed"
        initial_version = sample_setting.version
        sample_setting.reset_to_default()
        assert sample_setting.value == "default_value"
        assert sample_setting.version == initial_version + 1

    def test_reset_to_default_no_default(self, sample_setting):
        sample_setting.default_value = None
        sample_setting.value = "changed"
        initial_version = sample_setting.version
        sample_setting.reset_to_default()
        # Should not change value
        assert sample_setting.value == "changed"
        # Should still increment version? The code increments unconditionally if default_value is not None, but if None, it does nothing.
        # It only sets value if default_value is not None, and then increments. So if None, version does not increment.
        assert sample_setting.version == initial_version

    # ---- activate ----
    def test_activate(self, sample_setting):
        sample_setting.is_active = False
        initial_version = sample_setting.version
        sample_setting.activate()
        assert sample_setting.is_active is True
        assert sample_setting.version == initial_version + 1

    # ---- deactivate ----
    def test_deactivate(self, sample_setting):
        sample_setting.is_active = True
        initial_version = sample_setting.version
        sample_setting.deactivate()
        assert sample_setting.is_active is False
        assert sample_setting.version == initial_version + 1


# ============================================================================
# Tests for Edge Cases and Additional Coverage
# ============================================================================

class TestSystemSettingTableEdgeCases:
    def test_typed_value_getter_for_boolean_with_invalid_string(self, boolean_setting):
        boolean_setting.value = "garbage"
        # The getter uses lower() and checks in ("true", "1", "yes", "on"), so garbage returns False
        assert boolean_setting.typed_value is False

    def test_typed_value_setter_for_float_with_decimal_preserves_precision(self, float_setting):
        val = Decimal("1.23456789")
        float_setting.typed_value = val
        assert float_setting.value == "1.23456789"

    def test_validate_with_min_value_using_decimal_for_float(self, float_setting):
        float_setting.min_value = "1.1"
        assert float_setting.validate(Decimal("1.2")) is True
        assert float_setting.validate(Decimal("1.0")) is False

    def test_validate_with_max_value_using_decimal_for_float(self, float_setting):
        float_setting.max_value = "9.9"
        assert float_setting.validate(Decimal("9.8")) is True
        assert float_setting.validate(Decimal("10.0")) is False

    def test_typed_value_for_json_with_malformed_json(self, json_setting):
        json_setting.value = "invalid"
        with pytest.raises(json.JSONDecodeError):
            _ = json_setting.typed_value

    def test_typed_value_setter_for_json_with_complex_object(self, json_setting):
        obj = {"a": [1, 2, 3], "b": {"c": "d"}}
        json_setting.typed_value = obj
        assert json.loads(json_setting.value) == obj

    def test_typed_value_for_integer_with_non_numeric_string(self, integer_setting):
        integer_setting.value = "abc"
        with pytest.raises(ValueError):
            _ = integer_setting.typed_value

    def test_typed_value_for_float_with_non_numeric_string(self, float_setting):
        float_setting.value = "abc"
        with pytest.raises(ValueError):
            _ = float_setting.typed_value

    def test_validate_allowed_values_case_insensitive(self, sample_setting):
        sample_setting.allowed_values = ["Yes", "No"]
        assert sample_setting.validate("yes") is True
        assert sample_setting.validate("YES") is True
        assert sample_setting.validate("no") is True
        assert sample_setting.validate("maybe") is False

    def test_validate_with_regex_and_empty_string(self, sample_setting):
        sample_setting.validation_regex = r"^\d+$"
        assert sample_setting.validate("") is False

    def test_activate_does_not_change_other_fields(self, sample_setting):
        sample_setting.is_active = False
        sample_setting.activate()
        assert sample_setting.key == "test.setting"
        assert sample_setting.data_type == "string"

    def test_deactivate_does_not_change_other_fields(self, sample_setting):
        sample_setting.deactivate()
        assert sample_setting.key == "test.setting"
        assert sample_setting.data_type == "string"
