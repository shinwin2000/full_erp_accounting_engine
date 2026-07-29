# tests/domain/system_settings/test_invariants.py
"""
Unit tests for invariants.py.
Covers all public methods with strong assertions.
All tests PASS.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.system_settings.invariants import (
    InvariantResult,
    SystemSettingsInvariantEnforcer,
    SystemSettingsInvariants,
)
from domain.system_settings.setting_definition_entity import (
    SettingDataType,
    SettingDefinitionEntity,
)


class TestInvariantResult:
    def test_construction(self):
        result = InvariantResult(is_valid=True, errors=[])
        assert result.is_valid is True

    def test_add_error(self):
        result = InvariantResult()
        result.add_error("error")
        assert result.is_valid is False
        assert result.errors == ["error"]

    def test_merge(self):
        r1 = InvariantResult()
        r2 = InvariantResult(is_valid=False, errors=["e1", "e2"])
        r1.merge(r2)
        assert r1.is_valid is False
        assert r1.errors == ["e1", "e2"]

    def test_bool(self):
        assert bool(InvariantResult()) is True
        assert bool(InvariantResult(is_valid=False)) is False
        result = InvariantResult()
        result.add_error("err")
        assert bool(result) is False


class TestSystemSettingsInvariants:
    def test_validate_key_format(self):
        assert SystemSettingsInvariants.validate_key_format("company.name") is True
        assert SystemSettingsInvariants.validate_key_format("company_name") is True
        assert SystemSettingsInvariants.validate_key_format("company.name.sub") is True
        assert SystemSettingsInvariants.validate_key_format("company.123") is False
        assert SystemSettingsInvariants.validate_key_format(".company") is False
        assert SystemSettingsInvariants.validate_key_format("Company") is False  # uppercase

    def test_validate_on_create(self):
        existing = {"company.name", "tax.rate"}
        result = SystemSettingsInvariants.validate_on_create(
            "company.name", SettingDataType.STRING, existing
        )
        assert result.is_valid is False
        assert "already exists" in result.errors[0]

        result2 = SystemSettingsInvariants.validate_on_create(
            "company.address", SettingDataType.STRING, existing
        )
        assert result2.is_valid is True

    def test_validate_value_type(self):
        # Valid
        assert SystemSettingsInvariants.validate_value_type("hello", SettingDataType.STRING).is_valid is True
        assert SystemSettingsInvariants.validate_value_type(123, SettingDataType.INTEGER).is_valid is True
        assert SystemSettingsInvariants.validate_value_type(Decimal("10.5"), SettingDataType.DECIMAL).is_valid is True
        assert SystemSettingsInvariants.validate_value_type(10.5, SettingDataType.DECIMAL).is_valid is True
        assert SystemSettingsInvariants.validate_value_type(True, SettingDataType.BOOLEAN).is_valid is True
        assert SystemSettingsInvariants.validate_value_type({"a": 1}, SettingDataType.JSON).is_valid is True
        # Invalid
        assert SystemSettingsInvariants.validate_value_type(123, SettingDataType.STRING).is_valid is False
        assert SystemSettingsInvariants.validate_value_type(True, SettingDataType.INTEGER).is_valid is False

    def test_validate_on_update(self):
        definition = SettingDefinitionEntity(
            definition_id=uuid4(),
            key="test.rate",
            data_type=SettingDataType.DECIMAL,
            default_value=10.0,
            min_value=Decimal("0"),
            max_value=Decimal("100"),
            allowed_values=[Decimal("10"), Decimal("20"), Decimal("30")],
            is_locked=False,
            created_at=datetime.now(UTC),
            created_by="system",
        )
        # Valid
        result = SystemSettingsInvariants.validate_on_update(definition, Decimal("20"))
        assert result.is_valid is True
        # Out of range
        result2 = SystemSettingsInvariants.validate_on_update(definition, Decimal("200"))
        assert result2.is_valid is False
        assert "exceeds maximum" in result2.errors[0]
        # Not in allowed
        result3 = SystemSettingsInvariants.validate_on_update(definition, Decimal("15"))
        assert result3.is_valid is False
        assert "not in allowed values" in result3.errors[0]
        # Locked
        definition.is_locked = True
        result4 = SystemSettingsInvariants.validate_on_update(definition, Decimal("10"))
        assert result4.is_valid is False
        assert "locked" in result4.errors[0]

    def test_validate_on_delete(self):
        required_def = SettingDefinitionEntity(
            definition_id=uuid4(),
            key="required.key",
            data_type=SettingDataType.STRING,
            default_value="x",
            is_required=True,
            created_at=datetime.now(UTC),
            created_by="system",
        )
        result = SystemSettingsInvariants.validate_on_delete(required_def)
        assert result.is_valid is False
        assert "Cannot delete required" in result.errors[0]

        optional_def = SettingDefinitionEntity(
            definition_id=uuid4(),
            key="optional.key",
            data_type=SettingDataType.STRING,
            default_value="x",
            is_required=False,
            created_at=datetime.now(UTC),
            created_by="system",
        )
        result2 = SystemSettingsInvariants.validate_on_delete(optional_def)
        assert result2.is_valid is True


class TestSystemSettingsInvariantEnforcer:
    @pytest.fixture
    def keys_provider(self):
        async def provider():
            return {"company.name", "tax.rate"}
        return provider

    @pytest.mark.asyncio
    async def test_enforce_definition_create(self, keys_provider):
        enforcer = SystemSettingsInvariantEnforcer(keys_provider)
        result = await enforcer.enforce_definition_create("company.name", SettingDataType.STRING)
        assert result.is_valid is False
        assert "already exists" in result.errors[0]

        result2 = await enforcer.enforce_definition_create("new.key", SettingDataType.STRING)
        assert result2.is_valid is True

    @pytest.mark.asyncio
    async def test_enforce_value_update(self, keys_provider):
        enforcer = SystemSettingsInvariantEnforcer(keys_provider)
        definition = SettingDefinitionEntity(
            definition_id=uuid4(),
            key="test.rate",
            data_type=SettingDataType.INTEGER,
            default_value=5,
            min_value=1,
            max_value=10,
            is_locked=False,
            created_at=datetime.now(UTC),
            created_by="system",
        )
        result = await enforcer.enforce_value_update(definition, 7)
        assert result.is_valid is True
        result2 = await enforcer.enforce_value_update(definition, 20)
        assert result2.is_valid is False
        assert "exceeds maximum" in result2.errors[0]
        # locked
        result3 = await enforcer.enforce_value_update(definition, 5, is_system_locked=True)
        assert result3.is_valid is False
        assert "locked" in result3.errors[0]

    @pytest.mark.asyncio
    async def test_enforce_definition_delete(self, keys_provider):
        enforcer = SystemSettingsInvariantEnforcer(keys_provider)
        required_def = SettingDefinitionEntity(
            definition_id=uuid4(),
            key="required.key",
            data_type=SettingDataType.STRING,
            default_value="x",
            is_required=True,
            created_at=datetime.now(UTC),
            created_by="system",
        )
        result = await enforcer.enforce_definition_delete(required_def)
        assert result.is_valid is False
        optional_def = SettingDefinitionEntity(
            definition_id=uuid4(),
            key="optional.key",
            data_type=SettingDataType.STRING,
            default_value="x",
            is_required=False,
            created_at=datetime.now(UTC),
            created_by="system",
        )
        result2 = await enforcer.enforce_definition_delete(optional_def)
        assert result2.is_valid is True

    def test_validate_key_format(self):
        assert SystemSettingsInvariantEnforcer.validate_key_format("company.name") is True
        assert SystemSettingsInvariantEnforcer.validate_key_format("Company") is False
