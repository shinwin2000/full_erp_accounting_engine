# tests/adapters/secondary_impl/test_sqlalchemy_system_setting_repository_impl.py
"""
Comprehensive tests for sqlalchemy_system_setting_repository_impl.py.

Covers:
- All custom exceptions: construction and inheritance
- SettingValueValidator: validate_string, validate_integer, validate_float,
  validate_boolean, validate_json, validate_decimal (with error cases)
- SQLAlchemySystemSettingRepository:
  - __init__, session property getter/setter
  - _validate_and_convert_value (all data types + error)
  - _convert_to_python (all data types)
  - _to_domain (mapping from ORM to domain)
  - _get_cache_key, _invalidate_cache, _log_audit, _check_critical_setting_change
  - add, get_by_key, update, delete (with optimistic lock, read-only, not found)
  - get_by_id, get_value, set_value (create or update), list_settings,
    get_settings_by_category, reset_to_default, reload_cache
  - Port methods: get_all, get_by_category, import_from_json, hot_reload, get_audit_log
  - Extra methods: get_public_settings, get_secrets, check_dependencies,
    export_to_json, get_statistics, health_check, register_validation_hook
- All exceptions: InvalidSettingValueError, SettingNotFoundError,
  DuplicateSettingKeyError, OptimisticLockError, SettingReadOnlyError,
  SystemSettingRepositoryError
- Mocked dependencies: AsyncSession, Redis client, trigger_alert
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from adapters.secondary_impl.sqlalchemy_system_setting_repository_impl import (
    DuplicateSettingKeyError,
    InvalidSettingValueError,
    OptimisticLockError,
    SettingNotFoundError,
    SettingReadOnlyError,
    SettingValueValidator,
    SQLAlchemySystemSettingRepository,
    SystemSettingRepositoryError,
)
from domain.system_settings.aggregate_root import (
    SettingCategory,
    SettingDataType,
    SettingScope,
    SystemSettingAggregate,
)
from infrastructure.persistence_orm.system_setting_table import SystemSettingTable

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_session():
    """Mock AsyncSession with common methods."""
    session = AsyncMock()
    session.add = AsyncMock()
    session.flush = AsyncMock()
    session.rollback = AsyncMock()
    session.merge = AsyncMock()
    session.execute = AsyncMock()
    session.begin = AsyncMock()
    return session


@pytest.fixture
def mock_redis():
    """Mock Redis client."""
    redis = AsyncMock()
    redis.setex = AsyncMock()
    redis.delete = AsyncMock()
    redis.keys = AsyncMock(return_value=[])
    return redis


@pytest.fixture
def repo(mock_session, mock_redis):
    """Repository with mocked session and Redis."""
    with patch("adapters.secondary_impl.sqlalchemy_system_setting_repository_impl.get_redis_client") as mock_get_redis:
        mock_get_redis.return_value = mock_redis
        repo = SQLAlchemySystemSettingRepository(session=mock_session)
        # Assign redis directly to avoid async get
        repo._redis = mock_redis
        return repo


@pytest.fixture
def sample_aggregate():
    """Sample domain aggregate."""
    return SystemSettingAggregate(
        id=uuid4(),
        key="test.setting",
        value="test_value",
        data_type=SettingDataType.STRING,
        description="Test setting",
        category=SettingCategory.GENERAL,
        scope=SettingScope.GLOBAL,
        legal_entity_id=None,
        is_readonly=False,
        is_encrypted=False,
        default_value="default",
        validation_regex=None,
        min_value=None,
        max_value=None,
        allowed_values=None,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        created_by=uuid4(),
        updated_by=uuid4(),
        version=1,
    )


@pytest.fixture
def sample_table(sample_aggregate):
    """Sample ORM table corresponding to aggregate."""
    return SystemSettingTable(
        id=sample_aggregate.id,
        key=sample_aggregate.key,
        value="test_value",
        data_type="string",
        description=sample_aggregate.description,
        category="general",
        scope="global",
        legal_entity_id=None,
        is_readonly=False,
        is_encrypted=False,
        default_value="default",
        validation_regex=None,
        min_value=None,
        max_value=None,
        allowed_values=None,
        created_at=sample_aggregate.created_at,
        updated_at=sample_aggregate.updated_at,
        created_by=sample_aggregate.created_by,
        updated_by=sample_aggregate.updated_by,
        version=1,
        deleted_at=None,
    )


# ============================================================================
# Tests for Exceptions
# ============================================================================

class TestExceptions:
    def test_system_setting_repository_error(self):
        with pytest.raises(SystemSettingRepositoryError):
            raise SystemSettingRepositoryError("Test")

    def test_duplicate_setting_key_error(self):
        with pytest.raises(DuplicateSettingKeyError):
            raise DuplicateSettingKeyError("Duplicate")

    def test_setting_not_found_error(self):
        with pytest.raises(SettingNotFoundError):
            raise SettingNotFoundError("Not found")

    def test_invalid_setting_value_error(self):
        with pytest.raises(InvalidSettingValueError):
            raise InvalidSettingValueError("Invalid")

    def test_setting_read_only_error(self):
        with pytest.raises(SettingReadOnlyError):
            raise SettingReadOnlyError("Read only")

    def test_optimistic_lock_error(self):
        with pytest.raises(OptimisticLockError):
            raise OptimisticLockError("Lock")


# ============================================================================
# Tests for SettingValueValidator
# ============================================================================

class TestSettingValueValidator:
    def test_validate_string(self):
        assert SettingValueValidator.validate_string("hello") == "hello"
        assert SettingValueValidator.validate_string(123) == "123"
        assert SettingValueValidator.validate_string(None) == ""
        assert SettingValueValidator.validate_string(True) == "True"

    def test_validate_integer(self):
        assert SettingValueValidator.validate_integer(42) == 42
        assert SettingValueValidator.validate_integer("123") == 123
        assert SettingValueValidator.validate_integer(True) == 1
        assert SettingValueValidator.validate_integer(False) == 0
        with pytest.raises(InvalidSettingValueError, match="Cannot convert"):
            SettingValueValidator.validate_integer("abc")

    def test_validate_float(self):
        result = SettingValueValidator.validate_float("3.14")
        assert isinstance(result, Decimal)
        assert result == Decimal("3.14")
        result2 = SettingValueValidator.validate_float(2.5)
        assert result2 == Decimal("2.5")
        with pytest.raises(InvalidSettingValueError, match="Cannot convert"):
            SettingValueValidator.validate_float("not a number")

    def test_validate_boolean(self):
        assert SettingValueValidator.validate_boolean(True) is True
        assert SettingValueValidator.validate_boolean(False) is False
        assert SettingValueValidator.validate_boolean("true") is True
        assert SettingValueValidator.validate_boolean("TRUE") is True
        assert SettingValueValidator.validate_boolean("1") is True
        assert SettingValueValidator.validate_boolean("yes") is True
        assert SettingValueValidator.validate_boolean("on") is True
        assert SettingValueValidator.validate_boolean("false") is False
        assert SettingValueValidator.validate_boolean(0) is False
        assert SettingValueValidator.validate_boolean(1) is True
        with pytest.raises(InvalidSettingValueError, match="Cannot convert"):
            SettingValueValidator.validate_boolean(object())

    def test_validate_json_from_string(self):
        json_str = '{"key": "value"}'
        result = SettingValueValidator.validate_json(json_str)
        assert result == json_str
        # Invalid JSON
        with pytest.raises(InvalidSettingValueError, match="Invalid JSON string"):
            SettingValueValidator.validate_json("{invalid}")

    def test_validate_json_from_dict(self):
        data = {"key": "value", "num": 42}
        result = SettingValueValidator.validate_json(data)
        assert json.loads(result) == data
        # Unserializable object
        with pytest.raises(InvalidSettingValueError, match="Cannot convert"):
            SettingValueValidator.validate_json(object())

    def test_validate_decimal(self):
        result = SettingValueValidator.validate_decimal("123.45")
        assert isinstance(result, Decimal)
        assert result == Decimal("123.45")
        result2 = SettingValueValidator.validate_decimal(Decimal("99.99"))
        assert result2 == Decimal("99.99")
        with pytest.raises(InvalidSettingValueError, match="Cannot convert"):
            SettingValueValidator.validate_decimal("not decimal")


# ============================================================================
# Tests for SQLAlchemySystemSettingRepository
# ============================================================================

class TestSQLAlchemySystemSettingRepository:
    def test_init(self, mock_session):
        repo = SQLAlchemySystemSettingRepository(session=mock_session)
        assert repo._session == mock_session
        assert repo._redis is None
        assert repo._validation_hooks == {}
        assert repo._audit_log == []

    def test_session_property(self, mock_session):
        repo = SQLAlchemySystemSettingRepository(session=mock_session)
        assert repo.session == mock_session
        # Session not set
        repo2 = SQLAlchemySystemSettingRepository()
        with pytest.raises(SystemSettingRepositoryError, match="Session not set"):
            _ = repo2.session

    def test_session_setter(self, mock_session):
        repo = SQLAlchemySystemSettingRepository()
        repo.session = mock_session
        assert repo._session == mock_session

    # ---- _get_cache_key ----

    def test_get_cache_key_global(self, repo):
        key = repo._get_cache_key("test.key", legal_entity_id=None)
        assert key == "system:setting:global:test.key"

    def test_get_cache_key_legal_entity(self, repo):
        le_id = uuid4()
        key = repo._get_cache_key("test.key", legal_entity_id=le_id)
        assert key == f"system:setting:{le_id}:test.key"

    # ---- _validate_and_convert_value ----

    def test_validate_and_convert_value_string(self, repo):
        result = repo._validate_and_convert_value(123, "string")
        assert result == "123"

    def test_validate_and_convert_value_integer(self, repo):
        result = repo._validate_and_convert_value("42", "integer")
        assert result == "42"

    def test_validate_and_convert_value_float(self, repo):
        result = repo._validate_and_convert_value("3.14", "float")
        assert result == "3.14"

    def test_validate_and_convert_value_boolean(self, repo):
        result = repo._validate_and_convert_value("true", "boolean")
        assert result == "true"
        result2 = repo._validate_and_convert_value(0, "boolean")
        assert result2 == "false"

    def test_validate_and_convert_value_json(self, repo):
        data = {"key": "value"}
        result = repo._validate_and_convert_value(data, "json")
        assert json.loads(result) == data

    def test_validate_and_convert_value_decimal(self, repo):
        result = repo._validate_and_convert_value("45.67", "decimal")
        assert result == "45.67"

    def test_validate_and_convert_value_unknown(self, repo):
        result = repo._validate_and_convert_value(123, "unknown")
        assert result == "123"

    def test_validate_and_convert_value_invalid_raises(self, repo):
        with pytest.raises(InvalidSettingValueError):
            repo._validate_and_convert_value("not int", "integer")

    # ---- _convert_to_python ----

    def test_convert_to_python_string(self, repo):
        assert repo._convert_to_python("hello", "string") == "hello"

    def test_convert_to_python_integer(self, repo):
        assert repo._convert_to_python("123", "integer") == 123

    def test_convert_to_python_float(self, repo):
        result = repo._convert_to_python("3.14", "float")
        assert isinstance(result, Decimal)
        assert result == Decimal("3.14")

    def test_convert_to_python_boolean(self, repo):
        assert repo._convert_to_python("true", "boolean") is True
        assert repo._convert_to_python("false", "boolean") is False

    def test_convert_to_python_json(self, repo):
        data = {"key": "value"}
        json_str = json.dumps(data)
        result = repo._convert_to_python(json_str, "json")
        assert result == data

    def test_convert_to_python_decimal(self, repo):
        result = repo._convert_to_python("45.67", "decimal")
        assert isinstance(result, Decimal)
        assert result == Decimal("45.67")

    def test_convert_to_python_unknown(self, repo):
        assert repo._convert_to_python("any", "unknown") == "any"

    # ---- _to_domain ----

    def test_to_domain(self, repo, sample_table):
        aggregate = repo._to_domain(sample_table)
        assert isinstance(aggregate, SystemSettingAggregate)
        assert aggregate.id == sample_table.id
        assert aggregate.key == sample_table.key
        assert aggregate.value == "test_value"
        assert aggregate.data_type == SettingDataType.STRING
        assert aggregate.category == SettingCategory.GENERAL
        assert aggregate.scope == SettingScope.GLOBAL
        assert aggregate.legal_entity_id == sample_table.legal_entity_id
        assert aggregate.is_readonly == sample_table.is_readonly
        assert aggregate.version == sample_table.version

    def test_to_domain_with_float(self, repo, sample_table):
        sample_table.data_type = "float"
        sample_table.value = "12.34"
        aggregate = repo._to_domain(sample_table)
        assert aggregate.value == Decimal("12.34")

    def test_to_domain_with_json(self, repo, sample_table):
        sample_table.data_type = "json"
        sample_table.value = '{"a":1}'
        aggregate = repo._to_domain(sample_table)
        assert aggregate.value == {"a": 1}

    def test_to_domain_with_allowed_values(self, repo, sample_table):
        sample_table.allowed_values = '["a","b"]'
        aggregate = repo._to_domain(sample_table)
        assert aggregate.allowed_values == ["a", "b"]

    # ---- _invalidate_cache ----

    @pytest.mark.asyncio
    async def test_invalidate_cache(self, repo, mock_redis):
        key = "test.key"
        await repo._invalidate_cache(key, legal_entity_id=None)
        mock_redis.delete.assert_called_once_with("system:setting:global:test.key")

    @pytest.mark.asyncio
    async def test_invalidate_cache_with_legal_entity(self, repo, mock_redis):
        le_id = uuid4()
        await repo._invalidate_cache("key", legal_entity_id=le_id)
        mock_redis.delete.assert_called_once_with(f"system:setting:{le_id}:key")

    @pytest.mark.asyncio
    async def test_invalidate_cache_redis_failure(self, repo, mock_redis):
        mock_redis.delete.side_effect = Exception("Redis error")
        # Should not raise, just log warning
        await repo._invalidate_cache("key")

    # ---- _log_audit ----

    @pytest.mark.asyncio
    async def test_log_audit(self, repo):
        setting_id = uuid4()
        await repo._log_audit("TEST", setting_id, {"foo": "bar"})
        assert len(repo._audit_log) == 1
        entry = repo._audit_log[0]
        assert entry["action"] == "TEST"
        assert entry["setting_id"] == str(setting_id)
        assert entry["details"]["foo"] == "bar"
        # Test log size limit
        repo._audit_log = []
        for _i in range(15000):
            await repo._log_audit("TEST", uuid4(), {})
        assert len(repo._audit_log) <= 5000

    # ---- _check_critical_setting_change ----

    @pytest.mark.asyncio
    async def test_check_critical_setting_change(self, repo):
        with patch("adapters.secondary_impl.sqlalchemy_system_setting_repository_impl.trigger_alert") as mock_alert:
            await repo._check_critical_setting_change("audit.enabled", "old", "new")
            mock_alert.assert_called_once()
            # Non-critical
            await repo._check_critical_setting_change("non.critical", "old", "new")
            mock_alert.assert_called_once()  # no extra call

    # ---- add ----

    @pytest.mark.asyncio
    async def test_add_success(self, repo, mock_session, sample_aggregate):
        # Mock get_by_key to return None (not exists)
        repo.get_by_key = AsyncMock(return_value=None)
        await repo.add(sample_aggregate)
        mock_session.add.assert_called_once()
        mock_session.flush.assert_called_once()
        assert len(repo._audit_log) == 1
        assert repo._audit_log[0]["action"] == "ADD"

    @pytest.mark.asyncio
    async def test_add_duplicate_raises(self, repo, mock_session, sample_aggregate):
        repo.get_by_key = AsyncMock(return_value=sample_aggregate)
        with pytest.raises(DuplicateSettingKeyError, match="already exists"):
            await repo.add(sample_aggregate)

    @pytest.mark.asyncio
    async def test_add_integrity_error(self, repo, mock_session, sample_aggregate):
        repo.get_by_key = AsyncMock(return_value=None)
        mock_session.add.side_effect = IntegrityError("mock", "params", "orig")
        with pytest.raises(SystemSettingRepositoryError, match="Integrity error"):
            await repo.add(sample_aggregate)
        mock_session.rollback.assert_called_once()

    # ---- get_by_key ----

    @pytest.mark.asyncio
    async def test_get_by_key_found(self, repo, mock_session, sample_table, sample_aggregate):
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none.return_value = sample_table
        mock_session.execute.return_value = mock_result
        # Redis setex mocked
        result = await repo.get_by_key("test.setting")
        assert result.id == sample_aggregate.id
        mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_by_key_not_found(self, repo, mock_session):
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result
        result = await repo.get_by_key("missing")
        assert result is None

    # ---- update ----

    @pytest.mark.asyncio
    async def test_update_success(self, repo, mock_session, sample_aggregate, sample_table):
        # Mock select for version check
        mock_result = AsyncMock()
        mock_result.first.return_value = (1, "old_value")
        mock_session.execute.return_value = mock_result
        repo._invalidate_cache = AsyncMock()
        repo._check_critical_setting_change = AsyncMock()
        sample_aggregate.version = 1
        await repo.update(sample_aggregate)
        mock_session.merge.assert_called_once()
        mock_session.flush.assert_called_once()
        assert repo._audit_log[-1]["action"] == "UPDATE"

    @pytest.mark.asyncio
    async def test_update_readonly_raises(self, repo, sample_aggregate):
        sample_aggregate.is_readonly = True
        with pytest.raises(SettingReadOnlyError, match="read-only"):
            await repo.update(sample_aggregate)

    @pytest.mark.asyncio
    async def test_update_not_found(self, repo, mock_session, sample_aggregate):
        mock_result = AsyncMock()
        mock_result.first.return_value = None
        mock_session.execute.return_value = mock_result
        with pytest.raises(SettingNotFoundError, match="not found"):
            await repo.update(sample_aggregate)

    @pytest.mark.asyncio
    async def test_update_optimistic_lock(self, repo, mock_session, sample_aggregate):
        mock_result = AsyncMock()
        mock_result.first.return_value = (2, "old_value")  # version mismatch
        mock_session.execute.return_value = mock_result
        sample_aggregate.version = 1
        with pytest.raises(OptimisticLockError, match="Version mismatch"):
            await repo.update(sample_aggregate)

    # ---- delete ----

    @pytest.mark.asyncio
    async def test_delete_success(self, repo, mock_session, sample_table):
        # Mock SELECT FOR UPDATE
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none.return_value = sample_table
        mock_session.execute.return_value = mock_result
        mock_session.begin = AsyncMock()
        repo._invalidate_cache = AsyncMock()

        result = await repo.delete(sample_table.id, user_id=uuid4())
        assert result is True
        assert sample_table.deleted_at is not None
        mock_session.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_not_found(self, repo, mock_session):
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result
        mock_session.begin = AsyncMock()
        result = await repo.delete(uuid4(), user_id=uuid4())
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_readonly_raises(self, repo, mock_session, sample_table):
        sample_table.is_readonly = True
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none.return_value = sample_table
        mock_session.execute.return_value = mock_result
        mock_session.begin = AsyncMock()
        with pytest.raises(SettingReadOnlyError, match="read-only"):
            await repo.delete(sample_table.id, user_id=uuid4())

    # ---- get_by_id ----

    @pytest.mark.asyncio
    async def test_get_by_id_found(self, repo, mock_session, sample_table):
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none.return_value = sample_table
        mock_session.execute.return_value = mock_result
        result = await repo.get_by_id(sample_table.id)
        assert result.id == sample_table.id

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, repo, mock_session):
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result
        result = await repo.get_by_id(uuid4())
        assert result is None

    # ---- get_value ----

    @pytest.mark.asyncio
    async def test_get_value_found(self, repo):
        aggregate = MagicMock()
        aggregate.value = "some_value"
        repo.get_by_key = AsyncMock(return_value=aggregate)
        result = await repo.get_value("key")
        assert result == "some_value"

    @pytest.mark.asyncio
    async def test_get_value_default(self, repo):
        repo.get_by_key = AsyncMock(return_value=None)
        result = await repo.get_value("key", default=42)
        assert result == 42

    # ---- set_value ----

    @pytest.mark.asyncio
    async def test_set_value_existing_update(self, repo):
        aggregate = MagicMock()
        aggregate.value = "old"
        repo.get_by_key = AsyncMock(return_value=aggregate)
        repo.update = AsyncMock()
        result = await repo.set_value("key", "new", updated_by=uuid4())
        assert result is True
        assert aggregate.value == "new"
        repo.update.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_value_existing_no_change(self, repo):
        aggregate = MagicMock()
        aggregate.value = "same"
        repo.get_by_key = AsyncMock(return_value=aggregate)
        repo.update = AsyncMock()
        result = await repo.set_value("key", "same", updated_by=uuid4())
        assert result is False
        repo.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_value_create_new(self, repo):
        repo.get_by_key = AsyncMock(return_value=None)
        repo.add = AsyncMock()
        result = await repo.set_value("new.key", 123, updated_by=uuid4())
        assert result is True
        repo.add.assert_called_once()

    # ---- list_settings ----

    @pytest.mark.asyncio
    async def test_list_settings(self, repo, mock_session, sample_table):
        mock_count = AsyncMock()
        mock_count.scalar.return_value = 1
        mock_result = AsyncMock()
        mock_result.scalars.return_value.all.return_value = [sample_table]
        mock_session.execute.side_effect = [mock_count, mock_result]
        items, total = await repo.list_settings(page=1, page_size=10)
        assert len(items) == 1
        assert total == 1

    # ---- get_settings_by_category ----

    @pytest.mark.asyncio
    async def test_get_settings_by_category(self, repo, mock_session, sample_table):
        mock_result = AsyncMock()
        mock_result.scalars.return_value.all.return_value = [sample_table]
        mock_session.execute.return_value = mock_result
        result = await repo.get_settings_by_category("general")
        assert result["test.setting"] == "test_value"

    # ---- reset_to_default ----

    @pytest.mark.asyncio
    async def test_reset_to_default_success(self, repo):
        aggregate = MagicMock()
        aggregate.default_value = "default_val"
        repo.get_by_key = AsyncMock(return_value=aggregate)
        repo.update = AsyncMock()
        result = await repo.reset_to_default("key")
        assert result is True
        repo.update.assert_called_once()

    @pytest.mark.asyncio
    async def test_reset_to_default_no_default(self, repo):
        aggregate = MagicMock()
        aggregate.default_value = None
        repo.get_by_key = AsyncMock(return_value=aggregate)
        result = await repo.reset_to_default("key")
        assert result is False

    # ---- reload_cache ----

    @pytest.mark.asyncio
    async def test_reload_cache(self, repo, mock_redis):
        mock_redis.keys.return_value = ["key1", "key2"]
        await repo.reload_cache()
        mock_redis.delete.assert_called_with("key1", "key2")
        mock_redis.keys.assert_called_once_with("system:setting:*")

    # ---- get_all (port) ----

    @pytest.mark.asyncio
    async def test_get_all(self, repo, mock_session, sample_table):
        mock_result = AsyncMock()
        mock_result.scalars.return_value.all.return_value = [sample_table]
        mock_session.execute.return_value = mock_result
        result = await repo.get_all()
        assert len(result) == 1

    # ---- get_by_category (port) ----

    @pytest.mark.asyncio
    async def test_get_by_category_port(self, repo, mock_session, sample_table):
        mock_result = AsyncMock()
        mock_result.scalars.return_value.all.return_value = [sample_table]
        mock_session.execute.return_value = mock_result
        result = await repo.get_by_category("general")
        assert len(result) == 1

    # ---- import_from_json ----

    @pytest.mark.asyncio
    async def test_import_from_json(self, repo):
        json_str = '{"key1": "value1", "key2": 42}'
        repo.get_by_key = AsyncMock(return_value=None)
        repo.add = AsyncMock()
        result = await repo.import_from_json(json_str, user_id=uuid4(), overwrite=False)
        assert result == 2
        assert repo.add.call_count == 2

    @pytest.mark.asyncio
    async def test_import_from_json_overwrite(self, repo):
        json_str = '{"key1": "new"}'
        existing = MagicMock()
        repo.get_by_key = AsyncMock(return_value=existing)
        repo.update = AsyncMock()
        result = await repo.import_from_json(json_str, user_id=uuid4(), overwrite=True)
        assert result == 1
        repo.update.assert_called_once()
        assert existing.value == "new"

    @pytest.mark.asyncio
    async def test_import_from_json_invalid(self, repo):
        with pytest.raises(SystemSettingRepositoryError, match="Invalid JSON"):
            await repo.import_from_json("{invalid}", user_id=uuid4())

    # ---- hot_reload ----

    @pytest.mark.asyncio
    async def test_hot_reload(self, repo):
        repo.reload_cache = AsyncMock()
        result = await repo.hot_reload()
        assert result["status"] == "success"
        repo.reload_cache.assert_called_once()

    # ---- get_audit_log ----

    @pytest.mark.asyncio
    async def test_get_audit_log(self, repo):
        await repo._log_audit("A", uuid4(), {})
        await repo._log_audit("B", uuid4(), {})
        logs = await repo.get_audit_log(limit=1, offset=0)
        assert len(logs) == 1
        assert logs[0]["action"] == "B"  # sorted descending by timestamp

    # ---- get_public_settings ----

    @pytest.mark.asyncio
    async def test_get_public_settings(self, repo, mock_session, sample_table):
        mock_result = AsyncMock()
        mock_result.scalars.return_value.all.return_value = [sample_table]
        mock_session.execute.return_value = mock_result
        result = await repo.get_public_settings()
        assert result["test.setting"] == "test_value"

    # ---- get_secrets ----

    @pytest.mark.asyncio
    async def test_get_secrets(self, repo, mock_session, sample_table):
        sample_table.is_encrypted = True
        mock_result = AsyncMock()
        mock_result.scalars.return_value.all.return_value = [sample_table]
        mock_session.execute.return_value = mock_result
        result = await repo.get_secrets()
        assert result["test.setting"] == "[ENCRYPTED]"

    # ---- check_dependencies ----

    @pytest.mark.asyncio
    async def test_check_dependencies(self, repo):
        result = await repo.check_dependencies("key")
        assert result == []

    # ---- export_to_json ----

    @pytest.mark.asyncio
    async def test_export_to_json(self, repo, mock_session, sample_table):
        mock_result = AsyncMock()
        mock_result.scalars.return_value.all.return_value = [sample_table]
        mock_session.execute.return_value = mock_result
        result = await repo.export_to_json()
        data = json.loads(result)
        assert "test.setting" in data

    # ---- get_statistics ----

    @pytest.mark.asyncio
    async def test_get_statistics(self, repo, mock_session):
        # Mock multiple execute calls
        mock_count = AsyncMock()
        mock_count.scalar.side_effect = [10, 2, 3]
        mock_cat = AsyncMock()
        mock_cat.all.return_value = [("general", 5), ("security", 3)]
        mock_session.execute.side_effect = [mock_count, mock_count, mock_count, mock_cat]
        stats = await repo.get_statistics()
        assert stats["total"] == 10
        assert stats["encrypted"] == 2
        assert stats["readonly"] == 3
        assert stats["categories"]["general"] == 5

    # ---- health_check ----

    @pytest.mark.asyncio
    async def test_health_check_healthy(self, repo, mock_session):
        mock_session.execute.return_value = AsyncMock()
        result = await repo.health_check()
        assert result["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_health_check_unhealthy(self, repo, mock_session):
        mock_session.execute.side_effect = Exception("DB down")
        result = await repo.health_check()
        assert result["status"] == "unhealthy"
        assert "error" in result

    # ---- register_validation_hook ----

    def test_register_validation_hook(self, repo):
        def hook(x):
            return True
        repo.register_validation_hook("test.key", hook)
        assert repo._validation_hooks["test.key"] == hook
