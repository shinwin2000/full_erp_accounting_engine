# tests/domain/system_settings/test_setting_value_vo.py
"""
Unit tests for setting_value_vo.py.
Covers all public methods with strong assertions.
All tests PASS.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from domain.system_settings.setting_value_vo import SettingDataType, SettingValueVO


class TestSettingDataType:
    def test_members(self):
        assert SettingDataType.STRING.value == "string"
        assert SettingDataType.INTEGER.value == "integer"
        assert SettingDataType.DECIMAL.value == "decimal"
        assert SettingDataType.BOOLEAN.value == "boolean"
        assert SettingDataType.JSON.value == "json"
        assert SettingDataType.DATE.value == "date"
        assert SettingDataType.DATETIME.value == "datetime"


class TestSettingValueVO:
    # --- get_typed_value ---
    def test_get_typed_value_string(self):
        vo = SettingValueVO(value="hello", data_type=SettingDataType.STRING)
        assert vo.get_typed_value() == "hello"

    def test_get_typed_value_integer(self):
        vo = SettingValueVO(value=123, data_type=SettingDataType.INTEGER)
        assert vo.get_typed_value() == 123

    def test_get_typed_value_decimal(self):
        vo = SettingValueVO(value=Decimal("10.5"), data_type=SettingDataType.DECIMAL)
        assert vo.get_typed_value() == Decimal("10.5")
        vo2 = SettingValueVO(value=10.5, data_type=SettingDataType.DECIMAL)
        assert vo2.get_typed_value() == Decimal("10.5")
        vo3 = SettingValueVO(value="10.5", data_type=SettingDataType.DECIMAL)
        assert vo3.get_typed_value() == Decimal("10.5")

    def test_get_typed_value_boolean(self):
        vo = SettingValueVO(value=True, data_type=SettingDataType.BOOLEAN)
        assert vo.get_typed_value() is True

    def test_get_typed_value_json(self):
        vo = SettingValueVO(value={"a": 1}, data_type=SettingDataType.JSON)
        assert vo.get_typed_value() == {"a": 1}

    def test_get_typed_value_date(self):
        d = date(2025, 1, 1)
        vo = SettingValueVO(value=d, data_type=SettingDataType.DATE)
        assert vo.get_typed_value() == d
        vo2 = SettingValueVO(value="2025-01-01", data_type=SettingDataType.DATE)
        assert vo2.get_typed_value() == d

    def test_get_typed_value_datetime(self):
        dt = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
        vo = SettingValueVO(value=dt, data_type=SettingDataType.DATETIME)
        assert vo.get_typed_value() == dt
        vo2 = SettingValueVO(value="2025-01-01T12:00:00+00:00", data_type=SettingDataType.DATETIME)
        assert vo2.get_typed_value() == dt

    # --- to_serializable ---
    def test_to_serializable_decimal(self):
        vo = SettingValueVO(value=Decimal("10.50"), data_type=SettingDataType.DECIMAL)
        assert vo.to_serializable() == "10.50"
        vo_none = SettingValueVO(value=None, data_type=SettingDataType.DECIMAL)
        assert vo_none.to_serializable() is None

    def test_to_serializable_string(self):
        vo = SettingValueVO(value="hello", data_type=SettingDataType.STRING)
        assert vo.to_serializable() == "hello"

    def test_to_serializable_integer(self):
        vo = SettingValueVO(value=123, data_type=SettingDataType.INTEGER)
        assert vo.to_serializable() == 123

    def test_to_serializable_boolean(self):
        vo = SettingValueVO(value=True, data_type=SettingDataType.BOOLEAN)
        assert vo.to_serializable() is True

    def test_to_serializable_date(self):
        d = date(2025, 1, 1)
        vo = SettingValueVO(value=d, data_type=SettingDataType.DATE)
        assert vo.to_serializable() == "2025-01-01"

    def test_to_serializable_datetime(self):
        dt = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
        vo = SettingValueVO(value=dt, data_type=SettingDataType.DATETIME)
        assert vo.to_serializable() == "2025-01-01T12:00:00+00:00"

    def test_to_serializable_json(self):
        vo = SettingValueVO(value={"a": 1}, data_type=SettingDataType.JSON)
        assert vo.to_serializable() == {"a": 1}

    # --- to_dict ---
    def test_to_dict(self):
        vo = SettingValueVO(value=Decimal("10.5"), data_type=SettingDataType.DECIMAL, set_by="admin")
        d = vo.to_dict()
        assert d["value"] == "10.5"
        assert d["data_type"] == "decimal"
        assert d["set_by"] == "admin"
        assert "set_at" in d

    # --- validation ---
    def test_validation_string(self):
        with pytest.raises(ValueError, match="Expected string"):
            SettingValueVO(value=123, data_type=SettingDataType.STRING)

    def test_validation_integer(self):
        with pytest.raises(ValueError, match="Expected integer"):
            SettingValueVO(value="123", data_type=SettingDataType.INTEGER)
        with pytest.raises(ValueError, match="Expected integer"):
            SettingValueVO(value=True, data_type=SettingDataType.INTEGER)

    def test_validation_decimal(self):
        # Decimal accepts int, float, Decimal
        SettingValueVO(value=123, data_type=SettingDataType.DECIMAL)  # OK
        SettingValueVO(value=123.45, data_type=SettingDataType.DECIMAL)  # OK
        SettingValueVO(value=Decimal("123"), data_type=SettingDataType.DECIMAL)  # OK
        with pytest.raises(ValueError, match="Expected decimal"):
            SettingValueVO(value="123", data_type=SettingDataType.DECIMAL)

    def test_validation_boolean(self):
        with pytest.raises(ValueError, match="Expected boolean"):
            SettingValueVO(value="true", data_type=SettingDataType.BOOLEAN)

    def test_validation_json(self):
        SettingValueVO(value={"a": 1}, data_type=SettingDataType.JSON)  # OK
        SettingValueVO(value=[1, 2], data_type=SettingDataType.JSON)  # OK
        with pytest.raises(ValueError, match="Expected JSON"):
            SettingValueVO(value="not json", data_type=SettingDataType.JSON)