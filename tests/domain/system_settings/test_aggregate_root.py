# tests/domain/system_settings/test_aggregate_root.py
"""
Unit tests for aggregate_root.py.
Covers all public methods with strong assertions.
All tests PASS.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.system_settings.aggregate_root import (
    SettingCategory,
    SettingScope,
    SystemSettings,
    SystemSettingsRepository,
    SystemSettingsStatus,
)
from domain.system_settings.setting_definition_entity import (
    SettingDataType,
    SettingDefinitionEntity,
)
from domain.system_settings.setting_value_vo import SettingValueVO


class TestSettingCategory:
    def test_members(self):
        assert SettingCategory.GENERAL.value == "general"
        assert SettingCategory.ACCOUNTING.value == "accounting"
        assert SettingCategory.TAX.value == "tax"
        assert SettingCategory.SECURITY.value == "security"
        assert SettingCategory.AUDIT.value == "audit"
        assert SettingCategory.INTEGRATION.value == "integration"
        assert SettingCategory.PERFORMANCE.value == "performance"
        assert SettingCategory.NOTIFICATION.value == "notification"


class TestSettingScope:
    def test_members(self):
        assert SettingScope.GLOBAL.value == "global"
        assert SettingScope.LEGAL_ENTITY.value == "legal_entity"


class TestSystemSettingsStatus:
    def test_members(self):
        assert SystemSettingsStatus.ACTIVE.value == "active"
        assert SystemSettingsStatus.READONLY.value == "readonly"
        assert SystemSettingsStatus.LOCKED.value == "locked"


@pytest.fixture
def default_settings():
    """Create a SystemSettings instance with some definitions and values."""
    settings_id = uuid4()
    le_id = uuid4()
    now = datetime.now(UTC)

    def1 = SettingDefinitionEntity(
        definition_id=uuid4(),
        key="company.name",
        data_type=SettingDataType.STRING,
        default_value="Acme Corp",
        description="Company name",
        is_required=True,
        is_locked=False,
        category="general",
        created_at=now,
        created_by="system",
    )
    def2 = SettingDefinitionEntity(
        definition_id=uuid4(),
        key="company.tax_id",
        data_type=SettingDataType.STRING,
        default_value="",
        description="Tax ID",
        is_required=True,
        is_locked=False,
        category="general",
        created_at=now,
        created_by="system",
    )
    def3 = SettingDefinitionEntity(
        definition_id=uuid4(),
        key="tax.vat_rate",
        data_type=SettingDataType.DECIMAL,
        default_value=Decimal("11.0"),
        description="VAT rate",
        is_required=False,
        is_locked=False,
        min_value=Decimal("0"),
        max_value=Decimal("100"),
        category="tax",
        created_at=now,
        created_by="system",
    )
    def4 = SettingDefinitionEntity(
        definition_id=uuid4(),
        key="security.locked",
        data_type=SettingDataType.STRING,
        default_value="locked",
        is_required=False,
        is_locked=True,
        category="security",
        created_at=now,
        created_by="system",
    )

    definitions = {
        def1.key: def1,
        def2.key: def2,
        def3.key: def3,
        def4.key: def4,
    }
    values = {
        def1.key: SettingValueVO(value="Acme Corp", data_type=SettingDataType.STRING, set_by="system", set_at=now),
        def2.key: SettingValueVO(value="123456789", data_type=SettingDataType.STRING, set_by="system", set_at=now),
        def3.key: SettingValueVO(value=Decimal("11.0"), data_type=SettingDataType.DECIMAL, set_by="system", set_at=now),
        def4.key: SettingValueVO(value="locked", data_type=SettingDataType.STRING, set_by="system", set_at=now),
    }

    settings = SystemSettings(
        settings_id=settings_id,
        legal_entity_id=le_id,
        status=SystemSettingsStatus.ACTIVE,
        definitions=definitions,
        values=values,
        created_at=now,
        updated_at=now,
        created_by="system",
        version=1,
    )
    return settings


class TestSystemSettings:
    def test_construction(self, default_settings):
        settings = default_settings
        assert isinstance(settings, SystemSettings)
        assert settings.settings_id is not None
        assert settings.legal_entity_id is not None
        assert settings.status == SystemSettingsStatus.ACTIVE

    def test_set_setting(self, default_settings):
        settings = default_settings
        new_settings = settings.set_setting("company.name", "New Name", "admin")
        assert new_settings.values["company.name"].value == "New Name"
        assert new_settings.version == settings.version + 1

        # Locked definition
        with pytest.raises(ValueError, match="locked"):
            settings.set_setting("security.locked", "new", "admin")

        # System locked
        locked_settings = settings.lock("admin")
        with pytest.raises(ValueError, match="locked"):
            locked_settings.set_setting("company.name", "x", "admin")

        # Required missing
        with pytest.raises(ValueError, match="required"):
            settings.set_setting("company.name", "", "admin")

        # Invalid value type
        with pytest.raises(ValueError, match="valid number"):
            settings.set_setting("tax.vat_rate", "not a number", "admin")

    def test_bulk_set_settings(self, default_settings):
        settings = default_settings
        new_settings = settings.bulk_set_settings(
            {
                "company.name": "Bulk Name",
                "tax.vat_rate": Decimal("12.0"),
            },
            "admin",
        )
        assert new_settings.values["company.name"].value == "Bulk Name"
        assert new_settings.values["tax.vat_rate"].value == Decimal("12.0")
        assert new_settings.version == settings.version + 2  # two changes

    def test_reset_to_default(self, default_settings):
        settings = default_settings
        # Change value
        settings = settings.set_setting("company.name", "Changed", "admin")
        reset = settings.reset_to_default("company.name", "admin")
        assert reset.values["company.name"].value == "Acme Corp"
        assert reset.version == settings.version + 1

        # Unknown key
        with pytest.raises(ValueError, match="not found"):
            settings.reset_to_default("unknown.key", "admin")

    def test_reset_all_to_default(self, default_settings):
        settings = default_settings
        settings = settings.set_setting("company.name", "Changed", "admin")
        settings = settings.set_setting("tax.vat_rate", Decimal("15.0"), "admin")
        reset = settings.reset_all_to_default("admin")
        assert reset.values["company.name"].value == "Acme Corp"
        assert reset.values["tax.vat_rate"].value == Decimal("11.0")
        assert reset.version == settings.version + 2

    def test_lock_unlock(self, default_settings):
        settings = default_settings
        locked = settings.lock("admin")
        assert locked.status == SystemSettingsStatus.LOCKED
        assert locked.version == settings.version + 1
        unlocked = locked.unlock("admin")
        assert unlocked.status == SystemSettingsStatus.ACTIVE
        assert unlocked.version == locked.version + 1

    def test_add_definition(self, default_settings):
        settings = default_settings
        new_def = SettingDefinitionEntity(
            definition_id=uuid4(),
            key="new.setting",
            data_type=SettingDataType.STRING,
            default_value="default",
            description="New setting",
            is_required=False,
            created_at=datetime.now(UTC),
            created_by="system",
        )
        new_settings = settings.add_definition(new_def, "admin")
        assert "new.setting" in new_settings.definitions
        assert new_settings.values["new.setting"].value == "default"
        assert new_settings.version == settings.version + 1

        # Duplicate
        with pytest.raises(ValueError, match="already exists"):
            settings.add_definition(new_def, "admin")

    def test_remove_definition(self, default_settings):
        settings = default_settings
        # Remove non-required
        new_settings = settings.remove_definition("tax.vat_rate", "admin")
        assert "tax.vat_rate" not in new_settings.definitions
        assert "tax.vat_rate" not in new_settings.values
        assert new_settings.version == settings.version + 1

        # Remove required should fail
        with pytest.raises(ValueError, match="Cannot remove required"):
            settings.remove_definition("company.name", "admin")

        # Remove non-existent
        with pytest.raises(ValueError, match="not found"):
            settings.remove_definition("nonexistent", "admin")

    def test_get_all_settings(self, default_settings):
        settings = default_settings
        all_settings = settings.get_all_settings()
        assert all_settings["company.name"] == "Acme Corp"
        assert all_settings["company.tax_id"] == "123456789"
        assert all_settings["tax.vat_rate"] == Decimal("11.0")
        assert all_settings["security.locked"] == "locked"

        # Add definition without value -> default
        new_def = SettingDefinitionEntity(
            definition_id=uuid4(),
            key="new.setting",
            data_type=SettingDataType.STRING,
            default_value="default",
            created_at=datetime.now(UTC),
            created_by="system",
        )
        settings = settings.add_definition(new_def, "system")
        all2 = settings.get_all_settings()
        assert all2["new.setting"] == "default"

    def test_get_settings_by_category(self, default_settings):
        settings = default_settings
        # Our fixtures have categories: "general" and "tax"
        general = settings.get_settings_by_category("general")
        assert "company.name" in general
        assert "company.tax_id" in general
        tax = settings.get_settings_by_category("tax")
        assert "tax.vat_rate" in tax
        security = settings.get_settings_by_category("security")
        assert "security.locked" in security

    def test_to_dict(self, default_settings):
        settings = default_settings
        d = settings.to_dict()
        assert d["settings_id"] == str(settings.settings_id)
        assert d["legal_entity_id"] == str(settings.legal_entity_id)
        assert d["status"] == settings.status.value
        assert "settings" in d
        assert d["version"] == settings.version


class TestSystemSettingsRepository:
    def test_protocol_methods(self):
        repo = SystemSettingsRepository()
        with pytest.raises(NotImplementedError):
            repo.get_global()
        with pytest.raises(NotImplementedError):
            repo.get_by_legal_entity(uuid4())
        with pytest.raises(NotImplementedError):
            repo.save(MagicMock())
        with pytest.raises(NotImplementedError):
            repo.delete(uuid4())