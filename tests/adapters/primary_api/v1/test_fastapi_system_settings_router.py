# adapters/primary_api/v1/test_fastapi_system_settings_router.py
"""
Comprehensive unit tests for FastAPI System Settings Router.

Covers:
- IdempotencyManager
- All enum classes
- All request/response schemas (valid & invalid cases)
- All endpoint functions (with mocked service layer)
- Key validation (regex, length, format)
- Range validation for numeric settings
"""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from adapters.primary_api.v1.fastapi_system_settings_router import (
    IdempotencyManager,
    SettingBulkUpdateSchema,
    SettingCategory,
    SettingCreateSchema,
    SettingDataType,
    SettingHistorySchema,
    SettingImportSchema,
    SettingResponseSchema,
    SettingSchemaSchema,
    SettingScope,
    SettingStatus,
    SettingUpdateSchema,
    SettingValidationResultSchema,
    activate_setting,
    bulk_reset_settings,
    bulk_update_settings,
    create_setting,
    deactivate_setting,
    export_settings,
    get_setting,
    get_setting_categories,
    get_setting_history,
    get_setting_schema,
    get_settings_audit_trail,
    get_settings_by_category,
    get_settings_svc,
    import_settings,
    lock_setting,
    reset_setting,
    unlock_setting,
    update_setting,
    validate_setting,
)

# =============================================================================
# Helper fixtures
# =============================================================================

@pytest.fixture
def mock_token_payload():
    return MagicMock(user_id=uuid4())


@pytest.fixture
def mock_legal_entity_id():
    return uuid4()


@pytest.fixture
def mock_settings_service():
    svc = AsyncMock()

    # Base setting response
    def create_mock_setting(**kwargs):
        defaults = {
            "id": uuid4(),
            "key": "test.setting",
            "value": "test_value",
            "data_type": "string",
            "description": "Test setting",
            "category": "general",
            "scope": "global",
            "legal_entity_id": None,
            "user_id": None,
            "role_id": None,
            "branch_id": None,
            "validation_regex": None,
            "min_value": None,
            "max_value": None,
            "allowed_values": None,
            "default_value": None,
            "is_readonly": False,
            "is_encrypted": False,
            "is_active": True,
            "is_locked": False,
            "tags": [],
            "version": 1,
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
            "created_by": uuid4(),
            "created_by_name": "Admin",
            "updated_by": uuid4(),
            "updated_by_name": "Admin",
        }
        defaults.update(kwargs)
        return MagicMock(**defaults)

    svc.create_setting.return_value = create_mock_setting()
    svc.get_setting.return_value = create_mock_setting()
    svc.list_settings.return_value = [create_mock_setting()]
    svc.update_setting.return_value = create_mock_setting()
    svc.deactivate_setting.return_value = True
    svc.activate_setting.return_value = create_mock_setting()
    svc.reset_to_default.return_value = create_mock_setting()
    svc.validate_bulk_update.return_value = MagicMock(
        success_count=2,
        failed_count=0,
        failed_keys=[],
        errors=[],
    )
    svc.bulk_update_settings.return_value = MagicMock(
        success_count=2,
        failed_count=0,
        failed_keys=[],
        errors=[],
    )
    svc.bulk_reset_settings.return_value = MagicMock(
        success_count=2,
        failed_count=0,
        failed_keys=[],
        errors=[],
    )
    svc.export_settings.return_value = {"settings": {"test": "value"}}
    svc.import_settings.return_value = MagicMock(
        success=True,
        imported_count=3,
        updated_count=2,
        skipped_count=0,
        errors=[],
    )
    svc.validate_setting_value.return_value = MagicMock(
        is_valid=True,
        errors=[],
        warnings=[],
        normalized_value="normalized",
    )
    svc.get_setting_schemas.return_value = [
        MagicMock(
            key="test.setting",
            data_type="string",
            description="Test",
            category="general",
            scope="global",
            validation_regex=None,
            min_value=None,
            max_value=None,
            allowed_values=None,
            default_value=None,
            is_readonly=False,
            is_encrypted=False,
            tags=[],
        )
    ]
    svc.get_setting_categories.return_value = [
        MagicMock(
            name="general",
            label="General",
            description="General settings",
            setting_count=10,
            active_count=8,
        )
    ]
    svc.get_setting_history.return_value = [
        MagicMock(
            id=uuid4(),
            setting_id=uuid4(),
            setting_key="test.setting",
            old_value="old",
            new_value="new",
            changed_by=uuid4(),
            changed_by_name="Admin",
            changed_at=datetime.now(UTC),
            reason="Update",
            ip_address="192.168.1.1",
        )
    ]
    svc.get_settings_audit_trail.return_value = svc.get_setting_history.return_value
    svc.lock_setting.return_value = create_mock_setting(is_locked=True)
    svc.unlock_setting.return_value = create_mock_setting(is_locked=False)

    return svc


# =============================================================================
# Tests for IdempotencyManager
# =============================================================================

class TestIdempotencyManager:
    def test_initialization(self):
        manager = IdempotencyManager()
        assert manager._storage == {}
        assert manager._ttl_seconds == 86400

    def test_get_cached_result_miss(self):
        manager = IdempotencyManager()
        result = manager.get_cached_result("key1", "method1")
        assert result is None

    def test_cache_and_retrieve(self):
        manager = IdempotencyManager()
        data = {"id": "123", "status": "ok"}
        manager.cache_result("key1", "method1", data)
        cached = manager.get_cached_result("key1", "method1")
        assert cached == data

    def test_cache_serializes_complex_types(self):
        manager = IdempotencyManager()
        data = {"date": datetime.now(UTC), "decimal": Decimal("10.50")}
        manager.cache_result("key2", "method2", data)
        cached = manager.get_cached_result("key2", "method2")
        assert cached is not None
        assert "date" in cached

    def test_cache_expiration(self):
        manager = IdempotencyManager()
        manager._ttl_seconds = 0
        manager.cache_result("key3", "method3", {"foo": "bar"})
        cached = manager.get_cached_result("key3", "method3")
        assert cached is None

    def test_key_generation_deterministic(self):
        manager = IdempotencyManager()
        key1 = manager._get_key("abc", "create_setting")
        key2 = manager._get_key("abc", "create_setting")
        key3 = manager._get_key("abc", "update_setting")
        assert key1 == key2
        assert key1 != key3


# =============================================================================
# Tests for Enums
# =============================================================================

class TestEnums:
    def test_setting_data_type_values(self):
        assert SettingDataType.STRING.value == "string"
        assert SettingDataType.INTEGER.value == "integer"
        assert SettingDataType.FLOAT.value == "float"
        assert SettingDataType.BOOLEAN.value == "boolean"
        assert SettingDataType.JSON.value == "json"
        assert SettingDataType.DECIMAL.value == "decimal"
        assert SettingDataType.DATE.value == "date"
        assert SettingDataType.DATETIME.value == "datetime"
        assert SettingDataType.EMAIL.value == "email"
        assert SettingDataType.URL.value == "url"
        assert SettingDataType.SENSITIVE.value == "sensitive"
        assert SettingDataType.ENCRYPTED.value == "encrypted"

    def test_setting_category_values(self):
        assert SettingCategory.GENERAL.value == "general"
        assert SettingCategory.ACCOUNTING.value == "accounting"
        assert SettingCategory.TAX.value == "tax"
        assert SettingCategory.SECURITY.value == "security"
        assert SettingCategory.AUDIT.value == "audit"
        assert SettingCategory.INTEGRATION.value == "integration"
        assert SettingCategory.PERFORMANCE.value == "performance"
        assert SettingCategory.NOTIFICATION.value == "notification"
        assert SettingCategory.REPORTING.value == "reporting"
        assert SettingCategory.INVENTORY.value == "inventory"
        assert SettingCategory.PURCHASE.value == "purchase"
        assert SettingCategory.SALES.value == "sales"
        assert SettingCategory.MANUFACTURING.value == "manufacturing"
        assert SettingCategory.FIXED_ASSET.value == "fixed_asset"
        assert SettingCategory.CURRENCY.value == "currency"
        assert SettingCategory.WORKFLOW.value == "workflow"
        assert SettingCategory.LOCALIZATION.value == "localization"

    def test_setting_scope_values(self):
        assert SettingScope.GLOBAL.value == "global"
        assert SettingScope.LEGAL_ENTITY.value == "legal_entity"
        assert SettingScope.USER.value == "user"
        assert SettingScope.ROLE.value == "role"
        assert SettingScope.BRANCH.value == "branch"

    def test_setting_status_values(self):
        assert SettingStatus.ACTIVE.value == "active"
        assert SettingStatus.INACTIVE.value == "inactive"
        assert SettingStatus.DRAFT.value == "draft"
        assert SettingStatus.PENDING.value == "pending"
        assert SettingStatus.LOCKED.value == "locked"
        assert SettingStatus.ARCHIVED.value == "archived"
        assert SettingStatus.DEPRECATED.value == "deprecated"


# =============================================================================
# Tests for Schemas (validation)
# =============================================================================

class TestSettingCreateSchema:
    def test_valid_schema(self):
        data = {
            "key": "company.name",
            "value": "My Company",
            "data_type": SettingDataType.STRING,
            "description": "Company name",
            "category": SettingCategory.GENERAL,
            "scope": SettingScope.GLOBAL,
            "validation_regex": "^[A-Za-z ]+$",
            "min_value": None,
            "max_value": None,
            "allowed_values": None,
            "default_value": None,
            "is_readonly": False,
            "is_encrypted": False,
            "tags": ["company", "identity"],
        }
        schema = SettingCreateSchema(**data)
        assert schema.key == "company.name"
        assert schema.value == "My Company"

    def test_key_lowercase(self):
        schema = SettingCreateSchema(
            key="COMPANY.NAME",
            value="Test",
            data_type=SettingDataType.STRING,
        )
        assert schema.key == "company.name"  # validator lowercases

    def test_key_invalid_characters(self):
        with pytest.raises(ValueError, match="must contain only letters, numbers, dots, underscores, and hyphens"):
            SettingCreateSchema(
                key="company name",
                value="Test",
                data_type=SettingDataType.STRING,
            )

    def test_range_validation_numeric(self):
        # valid: min < max
        schema = SettingCreateSchema(
            key="test.range",
            value="5",
            data_type=SettingDataType.INTEGER,
            min_value="1",
            max_value="10",
        )
        assert schema.min_value == "1"
        # invalid: min >= max
        with pytest.raises(ValueError, match="min_value must be less than max_value"):
            SettingCreateSchema(
                key="test.range",
                value="5",
                data_type=SettingDataType.INTEGER,
                min_value="10",
                max_value="5",
            )
        # invalid: non-numeric
        with pytest.raises(ValueError, match="must be numeric"):
            SettingCreateSchema(
                key="test.range",
                value="abc",
                data_type=SettingDataType.INTEGER,
                min_value="abc",
                max_value="10",
            )


class TestSettingUpdateSchema:
    def test_valid_schema(self):
        data = {
            "value": "new_value",
            "description": "Updated description",
            "category": SettingCategory.ACCOUNTING,
            "is_active": False,
            "tags": ["updated"],
        }
        schema = SettingUpdateSchema(**data)
        assert schema.value == "new_value"
        assert schema.category == SettingCategory.ACCOUNTING


class TestSettingBulkUpdateSchema:
    def test_valid_schema(self):
        data = {
            "settings": {"key1": "value1", "key2": "value2"},
            "dry_run": True,
        }
        schema = SettingBulkUpdateSchema(**data)
        assert schema.settings["key1"] == "value1"
        assert schema.dry_run is True


class TestSettingImportSchema:
    def test_valid_schema(self):
        data = {
            "data": '{"key": "value"}',
            "format": "json",
            "mode": "merge",
        }
        schema = SettingImportSchema(**data)
        assert schema.data == '{"key": "value"}'
        assert schema.format == "json"


# =============================================================================
# Tests for Endpoint Functions (with mocks)
# =============================================================================

@pytest.mark.asyncio
class TestSettingCRUD:
    async def test_create_success(self, mock_settings_service, mock_token_payload, mock_legal_entity_id):
        request = SettingCreateSchema(
            key="company.name",
            value="My Company",
            data_type=SettingDataType.STRING,
            category=SettingCategory.GENERAL,
            scope=SettingScope.GLOBAL,
        )
        result = await create_setting(
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            settings_svc=mock_settings_service,
        )
        assert isinstance(result, SettingResponseSchema)
        assert result.key == "test.setting"  # from mock
        mock_settings_service.create_setting.assert_called_once()

    async def test_create_idempotency(self, mock_settings_service, mock_token_payload, mock_legal_entity_id):
        request = SettingCreateSchema(
            key="company.name",
            value="Test",
            data_type=SettingDataType.STRING,
        )
        with patch("adapters.primary_api.v1.fastapi_system_settings_router._idempotency_manager") as mock_im:
            mock_im.get_cached_result.return_value = {
                "id": str(uuid4()),
                "key": "company.name",
                "value": "Test",
                "data_type": "string",
                "description": None,
                "category": "general",
                "scope": "global",
                "legal_entity_id": None,
                "user_id": None,
                "role_id": None,
                "branch_id": None,
                "validation_regex": None,
                "min_value": None,
                "max_value": None,
                "allowed_values": None,
                "default_value": None,
                "is_readonly": False,
                "is_encrypted": False,
                "is_active": True,
                "is_locked": False,
                "tags": None,
                "version": 1,
                "created_at": datetime.now(UTC).isoformat(),
                "updated_at": datetime.now(UTC).isoformat(),
                "created_by": str(uuid4()),
                "created_by_name": None,
                "updated_by": None,
                "updated_by_name": None,
            }
            result = await create_setting(
                request=request,
                idempotency_key="abc123",
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                settings_svc=mock_settings_service,
            )
            assert isinstance(result, SettingResponseSchema)
            mock_settings_service.create_setting.assert_not_called()

    async def test_create_value_error(self, mock_settings_service, mock_token_payload, mock_legal_entity_id):
        mock_settings_service.create_setting.side_effect = ValueError("Invalid key format")
        request = SettingCreateSchema(
            key="invalid key",
            value="test",
            data_type=SettingDataType.STRING,
        )
        with pytest.raises(HTTPException) as exc:
            await create_setting(
                request=request,
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                settings_svc=mock_settings_service,
            )
        assert exc.value.status_code == 422

    async def test_create_permission_error(self, mock_settings_service, mock_token_payload, mock_legal_entity_id):
        mock_settings_service.create_setting.side_effect = PermissionError("Not allowed")
        request = SettingCreateSchema(
            key="test.key",
            value="test",
            data_type=SettingDataType.STRING,
        )
        with pytest.raises(HTTPException) as exc:
            await create_setting(
                request=request,
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                settings_svc=mock_settings_service,
            )
        assert exc.value.status_code == 403

    async def test_get_setting_success(self, mock_settings_service, mock_legal_entity_id):
        result = await get_setting(
            key="test.setting",
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            settings_svc=mock_settings_service,
        )
        assert isinstance(result, SettingResponseSchema)
        mock_settings_service.get_setting.assert_called_once_with("test.setting", mock_legal_entity_id)

    async def test_get_setting_not_found(self, mock_settings_service, mock_legal_entity_id):
        mock_settings_service.get_setting.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_setting(
                key="missing",
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                settings_svc=mock_settings_service,
            )
        assert exc.value.status_code == 404

    async def test_get_settings_by_category(self, mock_settings_service, mock_legal_entity_id):
        result = await get_settings_by_category(
            category=SettingCategory.GENERAL,
            scope=SettingScope.GLOBAL,
            is_active=True,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            settings_svc=mock_settings_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], SettingResponseSchema)
        mock_settings_service.list_settings.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            category="general",
            scope="global",
            is_active=True,
        )

    async def test_update_setting_success(self, mock_settings_service, mock_token_payload, mock_legal_entity_id):
        request = SettingUpdateSchema(value="new_value")
        result = await update_setting(
            key="test.setting",
            request=request,
            reason="Update reason",
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            settings_svc=mock_settings_service,
        )
        assert isinstance(result, SettingResponseSchema)
        mock_settings_service.update_setting.assert_called_once_with(
            key="test.setting",
            legal_entity_id=mock_legal_entity_id,
            value="new_value",
            description=None,
            category=None,
            validation_regex=None,
            min_value=None,
            max_value=None,
            allowed_values=None,
            default_value=None,
            is_readonly=None,
            is_encrypted=None,
            is_active=None,
            tags=None,
            reason="Update reason",
            updated_by=mock_token_payload.user_id,
        )

    async def test_update_setting_not_found(self, mock_settings_service, mock_token_payload, mock_legal_entity_id):
        mock_settings_service.update_setting.return_value = None
        request = SettingUpdateSchema(value="new")
        with pytest.raises(HTTPException) as exc:
            await update_setting(
                key="missing",
                request=request,
                reason="",
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                settings_svc=mock_settings_service,
            )
        assert exc.value.status_code == 404

    async def test_deactivate_setting_success(self, mock_settings_service, mock_token_payload, mock_legal_entity_id):
        result = await deactivate_setting(
            key="test.setting",
            reason="Deprecated",
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            settings_svc=mock_settings_service,
        )
        assert result["deactivated"] is True
        mock_settings_service.deactivate_setting.assert_called_once_with(
            "test.setting", mock_legal_entity_id, mock_token_payload.user_id, "Deprecated"
        )

    async def test_deactivate_setting_not_found(self, mock_settings_service, mock_token_payload, mock_legal_entity_id):
        mock_settings_service.deactivate_setting.return_value = False
        with pytest.raises(HTTPException) as exc:
            await deactivate_setting(
                key="missing",
                reason="",
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                settings_svc=mock_settings_service,
            )
        assert exc.value.status_code == 404

    async def test_activate_setting_success(self, mock_settings_service, mock_token_payload, mock_legal_entity_id):
        result = await activate_setting(
            key="test.setting",
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            settings_svc=mock_settings_service,
        )
        assert isinstance(result, SettingResponseSchema)
        mock_settings_service.activate_setting.assert_called_once_with(
            "test.setting", mock_legal_entity_id, mock_token_payload.user_id
        )

    async def test_activate_setting_not_found(self, mock_settings_service, mock_token_payload, mock_legal_entity_id):
        mock_settings_service.activate_setting.return_value = None
        with pytest.raises(HTTPException) as exc:
            await activate_setting(
                key="missing",
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                settings_svc=mock_settings_service,
            )
        assert exc.value.status_code == 404

    async def test_reset_setting_success(self, mock_settings_service, mock_token_payload, mock_legal_entity_id):
        result = await reset_setting(
            key="test.setting",
            reason="Reset to default",
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            settings_svc=mock_settings_service,
        )
        assert isinstance(result, SettingResponseSchema)
        mock_settings_service.reset_to_default.assert_called_once_with(
            "test.setting", mock_legal_entity_id, mock_token_payload.user_id, "Reset to default"
        )

    async def test_reset_setting_not_found(self, mock_settings_service, mock_token_payload, mock_legal_entity_id):
        mock_settings_service.reset_to_default.return_value = None
        with pytest.raises(HTTPException) as exc:
            await reset_setting(
                key="missing",
                reason="",
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                settings_svc=mock_settings_service,
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
class TestBulkOperations:
    async def test_bulk_update_success(self, mock_settings_service, mock_token_payload, mock_legal_entity_id):
        request = SettingBulkUpdateSchema(
            settings={"key1": "value1", "key2": "value2"},
            dry_run=False,
        )
        result = await bulk_update_settings(
            request=request,
            reason="Bulk update",
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            settings_svc=mock_settings_service,
        )
        assert result["success_count"] == 2
        assert result["dry_run"] is False
        mock_settings_service.bulk_update_settings.assert_called_once_with(
            request.settings, mock_legal_entity_id, "Bulk update", mock_token_payload.user_id
        )

    async def test_bulk_update_dry_run(self, mock_settings_service, mock_token_payload, mock_legal_entity_id):
        request = SettingBulkUpdateSchema(
            settings={"key1": "value1"},
            dry_run=True,
        )
        result = await bulk_update_settings(
            request=request,
            reason="",
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            settings_svc=mock_settings_service,
        )
        assert result["dry_run"] is True
        mock_settings_service.validate_bulk_update.assert_called_once_with(
            request.settings, mock_legal_entity_id
        )
        mock_settings_service.bulk_update_settings.assert_not_called()

    async def test_bulk_reset_success(self, mock_settings_service, mock_token_payload, mock_legal_entity_id):
        keys = ["key1", "key2"]
        result = await bulk_reset_settings(
            keys=keys,
            reason="Reset all",
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            settings_svc=mock_settings_service,
        )
        assert result["success_count"] == 2
        mock_settings_service.bulk_reset_settings.assert_called_once_with(
            keys, mock_legal_entity_id, "Reset all", mock_token_payload.user_id
        )


@pytest.mark.asyncio
class TestImportExport:
    async def test_export_settings(self, mock_settings_service, mock_legal_entity_id):
        result = await export_settings(
            format="json",
            category=SettingCategory.GENERAL,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            settings_svc=mock_settings_service,
        )
        assert result == {"settings": {"test": "value"}}
        mock_settings_service.export_settings.assert_called_once_with(
            mock_legal_entity_id, "json", "general"
        )

    async def test_import_settings_success(self, mock_settings_service, mock_token_payload, mock_legal_entity_id):
        request = SettingImportSchema(
            data='{"key": "value"}',
            format="json",
            mode="merge",
        )
        result = await import_settings(
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            settings_svc=mock_settings_service,
        )
        assert result["success"] is True
        assert result["imported_count"] == 3
        mock_settings_service.import_settings.assert_called_once_with(
            mock_legal_entity_id, request.data, request.format, request.mode, mock_token_payload.user_id
        )

    async def test_import_settings_value_error(self, mock_settings_service, mock_token_payload, mock_legal_entity_id):
        mock_settings_service.import_settings.side_effect = ValueError("Invalid format")
        request = SettingImportSchema(
            data="invalid",
            format="json",
            mode="merge",
        )
        with pytest.raises(HTTPException) as exc:
            await import_settings(
                request=request,
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                settings_svc=mock_settings_service,
            )
        assert exc.value.status_code == 422


@pytest.mark.asyncio
class TestValidationAndSchema:
    async def test_validate_setting_success(self, mock_settings_service, mock_legal_entity_id):
        result = await validate_setting(
            key="test.setting",
            value="test",
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            settings_svc=mock_settings_service,
        )
        assert isinstance(result, SettingValidationResultSchema)
        assert result.is_valid is True
        mock_settings_service.validate_setting_value.assert_called_once_with(
            "test.setting", "test", mock_legal_entity_id
        )

    async def test_get_setting_schema(self, mock_settings_service):
        result = await get_setting_schema(
            category=SettingCategory.GENERAL,
            _permission=None,
            settings_svc=mock_settings_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], SettingSchemaSchema)
        mock_settings_service.get_setting_schemas.assert_called_once_with("general")

    async def test_get_setting_categories(self, mock_settings_service):
        result = await get_setting_categories(
            _permission=None,
            settings_svc=mock_settings_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["name"] == "general"
        mock_settings_service.get_setting_categories.assert_called_once()


@pytest.mark.asyncio
class TestHistoryAndAudit:
    async def test_get_setting_history(self, mock_settings_service, mock_legal_entity_id):
        result = await get_setting_history(
            key="test.setting",
            limit=10,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            settings_svc=mock_settings_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], SettingHistorySchema)
        mock_settings_service.get_setting_history.assert_called_once_with(
            "test.setting", mock_legal_entity_id, 10
        )

    async def test_get_settings_audit_trail(self, mock_settings_service, mock_legal_entity_id):
        start = datetime.now(UTC)
        end = datetime.now(UTC)
        user_id = uuid4()
        result = await get_settings_audit_trail(
            start_time=start,
            end_time=end,
            user_id=user_id,
            limit=50,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            settings_svc=mock_settings_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        mock_settings_service.get_settings_audit_trail.assert_called_once_with(
            mock_legal_entity_id, start, end, user_id, 50
        )


@pytest.mark.asyncio
class TestLockUnlock:
    async def test_lock_setting_success(self, mock_settings_service, mock_token_payload, mock_legal_entity_id):
        result = await lock_setting(
            key="test.setting",
            reason="Audit",
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            settings_svc=mock_settings_service,
        )
        assert isinstance(result, SettingResponseSchema)
        assert result.is_locked is True
        mock_settings_service.lock_setting.assert_called_once_with(
            "test.setting", mock_legal_entity_id, mock_token_payload.user_id, "Audit"
        )

    async def test_lock_setting_not_found(self, mock_settings_service, mock_token_payload, mock_legal_entity_id):
        mock_settings_service.lock_setting.return_value = None
        with pytest.raises(HTTPException) as exc:
            await lock_setting(
                key="missing",
                reason="",
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                settings_svc=mock_settings_service,
            )
        assert exc.value.status_code == 404

    async def test_unlock_setting_success(self, mock_settings_service, mock_token_payload, mock_legal_entity_id):
        result = await unlock_setting(
            key="test.setting",
            reason="Done",
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            settings_svc=mock_settings_service,
        )
        assert isinstance(result, SettingResponseSchema)
        assert result.is_locked is False
        mock_settings_service.unlock_setting.assert_called_once_with(
            "test.setting", mock_legal_entity_id, mock_token_payload.user_id, "Done"
        )

    async def test_unlock_setting_not_found(self, mock_settings_service, mock_token_payload, mock_legal_entity_id):
        mock_settings_service.unlock_setting.return_value = None
        with pytest.raises(HTTPException) as exc:
            await unlock_setting(
                key="missing",
                reason="",
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                settings_svc=mock_settings_service,
            )
        assert exc.value.status_code == 404


# =============================================================================
# Tests for Dependency Injection
# =============================================================================

@pytest.mark.asyncio
async def test_get_settings_svc():
    request = MagicMock()
    request.app.state.container = MagicMock()
    request.app.state.container.resolve.return_value = "service"
    result = await get_settings_svc(request)
    assert result == "service"
