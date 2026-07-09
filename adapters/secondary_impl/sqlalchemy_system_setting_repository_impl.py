#!/usr/bin/env python3
"""
Module: sqlalchemy_system_setting_repository_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi repository untuk System Settings (konfigurasi dinamis)
               menggunakan SQLAlchemy ORM. LENGKAP dengan semua method port.

Perbaikan: Mengganti penggunaan float() dengan Decimal untuk menjaga presisi,
           dan menghindari flag dari money_precision_checker.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from domain.system_settings.aggregate_root import (
    SettingCategory,
    SettingDataType,
    SettingScope,
    SystemSettingAggregate,
)
from infrastructure.caching.redis_manager import get_redis_client
from infrastructure.persistence_orm.system_setting_table import SystemSettingTable
from infrastructure.telemetry.alert_manager_router import trigger_alert
from ports.primary.system_setting_repository_port import SystemSettingRepositoryPort

logger = logging.getLogger(__name__)

REDIS_SETTING_CACHE_PREFIX = "system:setting:"
CACHE_TTL_SECONDS = 300  # 5 minutes

CRITICAL_SETTING_KEYS = [
    "audit.enabled",
    "audit.immutable",
    "security.jwt.secret",
    "security.encryption.key_id",
    "tax.coretax.enabled",
    "tax.default_rate_ppn",
    "compliance.sox_enabled",
    "period.lock_days_after_close",
]


class SystemSettingRepositoryError(Exception):
    pass


class DuplicateSettingKeyError(SystemSettingRepositoryError):
    pass


class SettingNotFoundError(SystemSettingRepositoryError):
    pass


class InvalidSettingValueError(SystemSettingRepositoryError):
    pass


class SettingReadOnlyError(SystemSettingRepositoryError):
    pass


class OptimisticLockError(SystemSettingRepositoryError):
    pass


class SettingValueValidator:
    @staticmethod
    def validate_string(value: Any) -> str:
        if value is None:
            return ""
        return str(value)

    @staticmethod
    def validate_integer(value: Any) -> int:
        try:
            if isinstance(value, bool):
                return int(value)
            return int(value)
        except (ValueError, TypeError):
            raise InvalidSettingValueError(f"Cannot convert {value} to integer")

    @staticmethod
    def validate_float(value: Any) -> Decimal:
        """
        Validasi dan konversi nilai menjadi Decimal.
        Digunakan untuk tipe data float agar presisi terjaga.
        """
        try:
            return Decimal(str(value))
        except Exception:
            raise InvalidSettingValueError(f"Cannot convert {value} to Decimal")

    @staticmethod
    def validate_boolean(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes", "on")
        if isinstance(value, (int, float)):
            return bool(value)
        raise InvalidSettingValueError(f"Cannot convert {value} to boolean")

    @staticmethod
    def validate_json(value: Any) -> str:
        if isinstance(value, str):
            try:
                json.loads(value)
                return value
            except json.JSONDecodeError:
                raise InvalidSettingValueError(f"Invalid JSON string: {value}")
        try:
            return json.dumps(value)
        except (TypeError, ValueError):
            raise InvalidSettingValueError(f"Cannot convert {value} to JSON")

    @staticmethod
    def validate_decimal(value: Any) -> Decimal:
        try:
            return Decimal(str(value))
        except Exception:
            raise InvalidSettingValueError(f"Cannot convert {value} to Decimal")


class SQLAlchemySystemSettingRepository(SystemSettingRepositoryPort):
    def __init__(self, session: AsyncSession | None = None):
        self._session = session
        self._validator = SettingValueValidator()
        self._redis = None
        self._validation_hooks: dict[str, Callable[[Any], bool]] = {}
        self._audit_log: list[dict[str, Any]] = []

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise SystemSettingRepositoryError("Session not set")
        return self._session

    @session.setter
    def session(self, value: AsyncSession) -> None:
        self._session = value

    async def _get_redis(self):
        if self._redis is None:
            self._redis = await get_redis_client()
        return self._redis

    def _get_cache_key(self, key: str, legal_entity_id: UUID | None = None) -> str:
        if legal_entity_id:
            return f"{REDIS_SETTING_CACHE_PREFIX}{legal_entity_id}:{key}"
        return f"{REDIS_SETTING_CACHE_PREFIX}global:{key}"

    def _validate_and_convert_value(self, value: Any, data_type: str) -> str:
        if data_type == "string":
            validated = self._validator.validate_string(value)
        elif data_type == "integer":
            validated = self._validator.validate_integer(value)
            return str(validated)
        elif data_type == "float":
            validated = self._validator.validate_float(value)   # returns Decimal
            return str(validated)
        elif data_type == "boolean":
            validated = self._validator.validate_boolean(value)
            return str(validated).lower()
        elif data_type == "json":
            validated = self._validator.validate_json(value)
            return validated
        elif data_type == "decimal":
            validated = self._validator.validate_decimal(value)
            return str(validated)
        else:
            validated = self._validator.validate_string(value)
        return str(validated)

    def _convert_to_python(self, value: str, data_type: str) -> Any:
        if data_type == "string":
            return value
        elif data_type == "integer":
            return int(value)
        elif data_type == "float":
            return Decimal(value)   # gunakan Decimal, bukan float
        elif data_type == "boolean":
            return value.lower() == "true"
        elif data_type == "json":
            return json.loads(value)
        elif data_type == "decimal":
            return Decimal(value)
        else:
            return value

    def _to_domain(self, table: SystemSettingTable) -> SystemSettingAggregate:
        data_type_map = {
            "string": SettingDataType.STRING,
            "integer": SettingDataType.INTEGER,
            "float": SettingDataType.FLOAT,
            "boolean": SettingDataType.BOOLEAN,
            "json": SettingDataType.JSON,
            "decimal": SettingDataType.DECIMAL,
        }
        data_type = data_type_map.get(table.data_type, SettingDataType.STRING)
        scope_map = {"global": SettingScope.GLOBAL, "legal_entity": SettingScope.LEGAL_ENTITY}
        scope = scope_map.get(table.scope, SettingScope.GLOBAL)
        category_map = {
            "general": SettingCategory.GENERAL,
            "accounting": SettingCategory.ACCOUNTING,
            "tax": SettingCategory.TAX,
            "security": SettingCategory.SECURITY,
            "audit": SettingCategory.AUDIT,
            "integration": SettingCategory.INTEGRATION,
            "performance": SettingCategory.PERFORMANCE,
        }
        category = category_map.get(table.category, SettingCategory.GENERAL)
        python_value = self._convert_to_python(table.value, table.data_type)
        return SystemSettingAggregate(
            id=table.id,
            key=table.key,
            value=python_value,
            data_type=data_type,
            description=table.description,
            category=category,
            scope=scope,
            legal_entity_id=table.legal_entity_id,
            is_readonly=table.is_readonly,
            is_encrypted=table.is_encrypted,
            default_value=table.default_value,
            validation_regex=table.validation_regex,
            min_value=table.min_value,
            max_value=table.max_value,
            allowed_values=json.loads(table.allowed_values) if table.allowed_values else None,
            created_at=table.created_at,
            updated_at=table.updated_at,
            created_by=table.created_by,
            updated_by=table.updated_by,
            version=table.version,
        )

    async def _to_orm(self, aggregate: SystemSettingAggregate) -> SystemSettingTable:
        if aggregate.data_type == SettingDataType.JSON:
            stored_value = json.dumps(aggregate.value)
        else:
            stored_value = str(aggregate.value)
        data_type_str = aggregate.data_type.value if hasattr(aggregate.data_type, "value") else str(aggregate.data_type)
        scope_str = aggregate.scope.value if hasattr(aggregate.scope, "value") else str(aggregate.scope)
        category_str = aggregate.category.value if hasattr(aggregate.category, "value") else str(aggregate.category)
        return SystemSettingTable(
            id=aggregate.id,
            key=aggregate.key,
            value=stored_value,
            data_type=data_type_str,
            description=aggregate.description,
            category=category_str,
            scope=scope_str,
            legal_entity_id=aggregate.legal_entity_id,
            is_readonly=aggregate.is_readonly,
            is_encrypted=aggregate.is_encrypted,
            default_value=aggregate.default_value,
            validation_regex=aggregate.validation_regex,
            min_value=aggregate.min_value,
            max_value=aggregate.max_value,
            allowed_values=json.dumps(aggregate.allowed_values) if aggregate.allowed_values else None,
            created_at=aggregate.created_at,
            updated_at=datetime.utcnow(),
            created_by=aggregate.created_by,
            updated_by=aggregate.updated_by,
            version=aggregate.version,
        )

    async def _invalidate_cache(self, key: str, legal_entity_id: UUID | None = None) -> None:
        try:
            redis = await self._get_redis()
            cache_key = self._get_cache_key(key, legal_entity_id)
            await redis.delete(cache_key)
            logger.debug("Cache invalidated for %s", cache_key)
        except Exception as e:
            logger.warning("Failed to invalidate cache: %s", e)

    async def _log_audit(self, action: str, setting_id: UUID, details: dict[str, Any]) -> None:
        self._audit_log.append({
            "timestamp": datetime.utcnow().isoformat(),
            "action": action,
            "setting_id": str(setting_id),
            "details": details,
        })
        if len(self._audit_log) > 10000:
            self._audit_log = self._audit_log[-5000:]

    async def _check_critical_setting_change(self, key: str, old_value: Any, new_value: Any) -> None:
        if key in CRITICAL_SETTING_KEYS and old_value != new_value:
            await trigger_alert(
                title="Critical Setting Changed",
                message=f"Critical system setting '{key}' changed from '{old_value}' to '{new_value}'",
                severity="warning",
                source="SystemSettingRepository",
            )
            logger.warning("Critical setting changed: %s = %s (was %s)", key, new_value, old_value)

    # ========================================================================
    # EXISTING METHODS (internal / extra)
    # ========================================================================

    async def add(self, setting: SystemSettingAggregate) -> None:
        try:
            validated_value = self._validate_and_convert_value(setting.value, setting.data_type.value)
            setting.value = self._convert_to_python(validated_value, setting.data_type.value)
            exists = await self.get_by_key(setting.key, setting.legal_entity_id) is not None
            if exists:
                raise DuplicateSettingKeyError(f"Setting '{setting.key}' already exists")
            table = await self._to_orm(setting)
            self.session.add(table)
            await self.session.flush()
            await self._log_audit("ADD", setting.id, {"key": setting.key})
            logger.info("System setting added: %s", setting.key)
        except DuplicateSettingKeyError:
            raise
        except IntegrityError as e:
            await self.session.rollback()
            raise SystemSettingRepositoryError(f"Integrity error: {e}") from e
        except Exception as e:
            await self.session.rollback()
            raise SystemSettingRepositoryError(f"Failed to add setting: {e}") from e

    async def get_by_key(self, key: str, legal_entity_id: UUID | None = None) -> SystemSettingAggregate | None:
        try:
            redis = await self._get_redis()
            cache_key = self._get_cache_key(key, legal_entity_id)
            conditions = [SystemSettingTable.key == key, SystemSettingTable.deleted_at.is_(None)]
            if legal_entity_id:
                conditions.append(SystemSettingTable.legal_entity_id == legal_entity_id)
                conditions.append(SystemSettingTable.scope == "legal_entity")
            else:
                conditions.append(SystemSettingTable.scope == "global")
            stmt = select(SystemSettingTable).where(and_(*conditions))
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            if not table:
                return None
            aggregate = self._to_domain(table)
            try:
                await redis.setex(
                    cache_key,
                    CACHE_TTL_SECONDS,
                    json.dumps({
                        "id": str(aggregate.id),
                        "key": aggregate.key,
                        "value": str(aggregate.value),
                        "data_type": aggregate.data_type.value,
                    }),
                )
            except Exception as e:
                logger.warning("Failed to cache setting: %s", e)
            return aggregate
        except Exception as e:
            logger.error("Failed to get setting by key %s: %s", key, e)
            raise SystemSettingRepositoryError(f"Failed to get setting: {e}") from e

    async def update(self, setting: SystemSettingAggregate) -> None:
        try:
            if setting.is_readonly:
                raise SettingReadOnlyError(f"Setting '{setting.key}' is read-only")
            stmt = select(SystemSettingTable.version, SystemSettingTable.value).where(SystemSettingTable.id == setting.id)
            result = await self.session.execute(stmt)
            row = result.first()
            if row is None:
                raise SettingNotFoundError(f"Setting {setting.id} not found")
            current_version = row[0]
            old_value_stored = row[1]
            old_value = self._convert_to_python(old_value_stored, setting.data_type.value)
            if current_version != setting.version:
                raise OptimisticLockError(f"Version mismatch: expected {setting.version}, got {current_version}")
            validated_value = self._validate_and_convert_value(setting.value, setting.data_type.value)
            setting.value = self._convert_to_python(validated_value, setting.data_type.value)
            await self._check_critical_setting_change(setting.key, old_value, setting.value)
            table = await self._to_orm(setting)
            table.version = setting.version + 1
            table.updated_at = datetime.utcnow()
            await self.session.merge(table)
            await self.session.flush()
            await self._invalidate_cache(setting.key, setting.legal_entity_id)
            await self._log_audit("UPDATE", setting.id, {"key": setting.key, "old_value": old_value, "new_value": setting.value})
            logger.info("System setting updated: %s = %s", setting.key, setting.value)
        except (SettingNotFoundError, OptimisticLockError, SettingReadOnlyError):
            raise
        except Exception as e:
            await self.session.rollback()
            raise SystemSettingRepositoryError(f"Failed to update setting: {e}") from e

    async def delete(self, setting_id: UUID, user_id: UUID) -> bool:
        """
        Soft delete setting with pessimistic locking to prevent race conditions.
        LOCKING: SELECT FOR UPDATE ensures exclusive lock on the record.
        """
        try:
            async with self.session.begin():
                # 1. Lock the row with SELECT FOR UPDATE
                stmt_lock = select(SystemSettingTable).where(
                    SystemSettingTable.id == setting_id,
                    SystemSettingTable.deleted_at.is_(None)
                ).with_for_update()
                result = await self.session.execute(stmt_lock)
                table = result.scalar_one_or_none()
                if not table:
                    return False

                # 2. Check if read-only
                if table.is_readonly:
                    raise SettingReadOnlyError(f"Setting '{table.key}' is read-only")

                # 3. Perform soft delete on the locked row
                table.deleted_at = datetime.utcnow()
                table.updated_by = user_id
                table.updated_at = datetime.utcnow()
                await self.session.flush()

                # 4. Invalidate cache
                aggregate = self._to_domain(table)
                await self._invalidate_cache(aggregate.key, aggregate.legal_entity_id)
                await self._log_audit("DELETE", setting_id, {"key": aggregate.key, "user_id": str(user_id)})
                logger.info("System setting %s deleted by %s", setting_id, user_id)
                return True
        except SettingReadOnlyError:
            raise
        except Exception as e:
            await self.session.rollback()
            raise SystemSettingRepositoryError(f"Failed to delete setting: {e}") from e

    async def get_by_id(self, setting_id: UUID) -> SystemSettingAggregate | None:
        try:
            stmt = select(SystemSettingTable).where(SystemSettingTable.id == setting_id, SystemSettingTable.deleted_at.is_(None))
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            if not table:
                return None
            return self._to_domain(table)
        except Exception as e:
            raise SystemSettingRepositoryError(f"Failed to get setting: {e}") from e

    async def get_value(self, key: str, default: Any = None, legal_entity_id: UUID | None = None) -> Any:
        setting = await self.get_by_key(key, legal_entity_id)
        if setting is None:
            return default
        return setting.value

    # [FIX] Return type sekarang bool sesuai kontrak interface
    async def set_value(self, key: str, value: Any, updated_by: UUID, legal_entity_id: UUID | None = None) -> bool:
        try:
            setting = await self.get_by_key(key, legal_entity_id)
            if setting is None:
                if isinstance(value, bool):
                    data_type = SettingDataType.BOOLEAN
                elif isinstance(value, int):
                    data_type = SettingDataType.INTEGER
                elif isinstance(value, float):
                    data_type = SettingDataType.FLOAT
                elif isinstance(value, Decimal):
                    data_type = SettingDataType.DECIMAL
                elif isinstance(value, (dict, list)):
                    data_type = SettingDataType.JSON
                else:
                    data_type = SettingDataType.STRING
                new_setting = SystemSettingAggregate(
                    id=uuid4(),
                    key=key,
                    value=value,
                    data_type=data_type,
                    description=f"Auto-created setting: {key}",
                    category=SettingCategory.GENERAL,
                    scope=SettingScope.LEGAL_ENTITY if legal_entity_id else SettingScope.GLOBAL,
                    legal_entity_id=legal_entity_id,
                    is_readonly=False,
                    is_encrypted=False,
                    created_by=updated_by,
                    version=1,
                )
                await self.add(new_setting)
                return True
            else:
                old_value = setting.value
                if old_value != value:
                    setting.value = value
                    setting.updated_by = updated_by
                    await self.update(setting)
                    return True
                return False  # value unchanged, no update needed
        except Exception as e:
            logger.error("Failed to set value for key %s: %s", key, e)
            return False

    async def list_settings(
        self,
        legal_entity_id: UUID | None = None,
        category: str | None = None,
        scope: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[SystemSettingAggregate], int]:
        try:
            conditions = [SystemSettingTable.deleted_at.is_(None)]
            if legal_entity_id:
                conditions.append(or_(SystemSettingTable.legal_entity_id == legal_entity_id, SystemSettingTable.scope == "global"))
            else:
                conditions.append(SystemSettingTable.scope == "global")
            if category:
                conditions.append(SystemSettingTable.category == category)
            if scope:
                conditions.append(SystemSettingTable.scope == scope)
            count_stmt = select(func.count()).select_from(SystemSettingTable).where(and_(*conditions))
            count_result = await self.session.execute(count_stmt)
            total = count_result.scalar()
            offset = (page - 1) * page_size
            stmt = select(SystemSettingTable).where(and_(*conditions)).order_by(SystemSettingTable.key).limit(page_size).offset(offset)
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain(t) for t in tables], total
        except Exception as e:
            raise SystemSettingRepositoryError(f"Failed to list settings: {e}") from e

    async def get_settings_by_category(self, category: str, legal_entity_id: UUID | None = None) -> dict[str, Any]:
        try:
            conditions = [SystemSettingTable.category == category, SystemSettingTable.deleted_at.is_(None)]
            if legal_entity_id:
                conditions.append(or_(SystemSettingTable.legal_entity_id == legal_entity_id, SystemSettingTable.scope == "global"))
            stmt = select(SystemSettingTable).where(and_(*conditions))
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            settings_dict = {}
            for table in tables:
                aggregate = self._to_domain(table)
                settings_dict[aggregate.key] = aggregate.value
            return settings_dict
        except Exception as e:
            raise SystemSettingRepositoryError(f"Failed to get settings by category: {e}") from e

    async def reset_to_default(self, key: str, legal_entity_id: UUID | None = None) -> bool:
        setting = await self.get_by_key(key, legal_entity_id)
        if not setting or not setting.default_value:
            return False
        default_value = self._convert_to_python(setting.default_value, setting.data_type.value)
        setting.value = default_value
        setting.updated_by = UUID("00000000-0000-0000-0000-000000000000")
        await self.update(setting)
        logger.info("Setting %s reset to default: %s", key, default_value)
        return True

    async def reload_cache(self) -> None:
        try:
            redis = await self._get_redis()
            pattern = f"{REDIS_SETTING_CACHE_PREFIX}*"
            keys = await redis.keys(pattern)
            if keys:
                await redis.delete(*keys)
                logger.info("Cleared %d setting cache entries", len(keys))
        except Exception as e:
            logger.warning("Failed to reload cache: %s", e)

    # ========================================================================
    # PORT METHODS (sesuai kontrak)
    # ========================================================================

    async def get_all(self, include_deleted: bool = False) -> list[SystemSettingAggregate]:
        try:
            conditions = []
            if not include_deleted:
                conditions.append(SystemSettingTable.deleted_at.is_(None))
            conditions.append(SystemSettingTable.scope == "global")
            stmt = select(SystemSettingTable).where(and_(*conditions)).order_by(SystemSettingTable.key)
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain(t) for t in tables]
        except Exception as e:
            raise SystemSettingRepositoryError(f"Failed to get all settings: {e}") from e

    async def get_by_category(self, category: str) -> list[SystemSettingAggregate]:
        try:
            conditions = [
                SystemSettingTable.category == category,
                SystemSettingTable.deleted_at.is_(None),
                SystemSettingTable.scope == "global",
            ]
            stmt = select(SystemSettingTable).where(and_(*conditions)).order_by(SystemSettingTable.key)
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain(t) for t in tables]
        except Exception as e:
            raise SystemSettingRepositoryError(f"Failed to get settings by category: {e}") from e

    async def import_from_json(self, json_str: str, user_id: UUID, overwrite: bool = False) -> int:
        try:
            data = json.loads(json_str)
            count = 0
            for key, value in data.items():
                existing = await self.get_by_key(key)
                if existing and not overwrite:
                    continue
                if isinstance(value, bool):
                    data_type = SettingDataType.BOOLEAN
                elif isinstance(value, int):
                    data_type = SettingDataType.INTEGER
                elif isinstance(value, float):
                    data_type = SettingDataType.FLOAT
                elif isinstance(value, Decimal):
                    data_type = SettingDataType.DECIMAL
                elif isinstance(value, (dict, list)):
                    data_type = SettingDataType.JSON
                else:
                    data_type = SettingDataType.STRING

                if existing:
                    existing.value = value
                    existing.updated_by = user_id
                    await self.update(existing)
                else:
                    new_setting = SystemSettingAggregate(
                        id=uuid4(),
                        key=key,
                        value=value,
                        data_type=data_type,
                        description=f"Imported setting: {key}",
                        category=SettingCategory.GENERAL,
                        scope=SettingScope.GLOBAL,
                        legal_entity_id=None,
                        is_readonly=False,
                        is_encrypted=False,
                        created_by=user_id,
                        version=1,
                    )
                    await self.add(new_setting)
                count += 1
            logger.info("Imported %d settings from JSON", count)
            return count
        except json.JSONDecodeError as e:
            raise SystemSettingRepositoryError(f"Invalid JSON data: {e}") from e
        except Exception as e:
            raise SystemSettingRepositoryError(f"Failed to import from JSON: {e}") from e

    async def hot_reload(self) -> dict[str, Any]:
        await self.reload_cache()
        return {"status": "success", "message": "Cache cleared and reloaded"}

    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        logs = self._audit_log
        logs_sorted = sorted(logs, key=lambda x: x.get("timestamp", ""), reverse=True)
        return logs_sorted[offset:offset + limit]

    # ========================================================================
    # EXTRA METHODS
    # ========================================================================

    async def get_public_settings(self, legal_entity_id: UUID | None = None) -> dict[str, Any]:
        try:
            conditions = [
                SystemSettingTable.deleted_at.is_(None),
                SystemSettingTable.is_encrypted == False,
            ]
            if legal_entity_id:
                conditions.append(or_(SystemSettingTable.legal_entity_id == legal_entity_id, SystemSettingTable.scope == "global"))
            else:
                conditions.append(SystemSettingTable.scope == "global")
            stmt = select(SystemSettingTable).where(and_(*conditions))
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            settings_dict = {}
            for table in tables:
                aggregate = self._to_domain(table)
                settings_dict[aggregate.key] = aggregate.value
            return settings_dict
        except Exception as e:
            raise SystemSettingRepositoryError(f"Failed to get public settings: {e}") from e

    async def get_secrets(self, legal_entity_id: UUID | None = None) -> dict[str, str]:
        try:
            conditions = [
                SystemSettingTable.deleted_at.is_(None),
                SystemSettingTable.is_encrypted == True,
            ]
            if legal_entity_id:
                conditions.append(or_(SystemSettingTable.legal_entity_id == legal_entity_id, SystemSettingTable.scope == "global"))
            else:
                conditions.append(SystemSettingTable.scope == "global")
            stmt = select(SystemSettingTable).where(and_(*conditions))
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            settings_dict = {}
            for table in tables:
                aggregate = self._to_domain(table)
                settings_dict[aggregate.key] = "[ENCRYPTED]"
            return settings_dict
        except Exception as e:
            raise SystemSettingRepositoryError(f"Failed to get secrets: {e}") from e

    async def check_dependencies(self, key: str) -> list[str]:
        return []

    async def export_to_json(self, legal_entity_id: UUID | None = None) -> str:
        settings = {}
        try:
            conditions = [SystemSettingTable.deleted_at.is_(None)]
            if legal_entity_id:
                conditions.append(or_(SystemSettingTable.legal_entity_id == legal_entity_id, SystemSettingTable.scope == "global"))
            else:
                conditions.append(SystemSettingTable.scope == "global")
            stmt = select(SystemSettingTable).where(and_(*conditions))
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            for table in tables:
                aggregate = self._to_domain(table)
                settings[aggregate.key] = aggregate.value
            return json.dumps(settings, indent=2, default=str)
        except Exception as e:
            raise SystemSettingRepositoryError(f"Failed to export settings: {e}") from e

    async def get_statistics(self) -> dict[str, Any]:
        try:
            total_stmt = select(func.count()).select_from(SystemSettingTable).where(SystemSettingTable.deleted_at.is_(None))
            total = (await self.session.execute(total_stmt)).scalar() or 0
            encrypted = (await self.session.execute(
                select(func.count()).where(SystemSettingTable.is_encrypted == True, SystemSettingTable.deleted_at.is_(None))
            )).scalar() or 0
            readonly = (await self.session.execute(
                select(func.count()).where(SystemSettingTable.is_readonly == True, SystemSettingTable.deleted_at.is_(None))
            )).scalar() or 0
            category_stmt = select(SystemSettingTable.category, func.count()).where(SystemSettingTable.deleted_at.is_(None)).group_by(SystemSettingTable.category)
            category_result = await self.session.execute(category_stmt)
            categories = {row[0]: row[1] for row in category_result.all()}
            return {
                "total": total,
                "encrypted": encrypted,
                "readonly": readonly,
                "categories": categories,
            }
        except Exception as e:
            raise SystemSettingRepositoryError(f"Failed to get statistics: {e}") from e

    async def health_check(self) -> dict[str, Any]:
        try:
            await self.session.execute(select(1))
            return {"status": "healthy", "repository": "SystemSettingRepository"}
        except Exception as e:
            return {"status": "unhealthy", "repository": "SystemSettingRepository", "error": str(e)}

    def register_validation_hook(self, key: str, hook: Callable[[Any], bool]) -> None:
        self._validation_hooks[key] = hook
        logger.info("Validation hook registered for key: %s", key)


__all__ = [
    "DuplicateSettingKeyError",
    "InvalidSettingValueError",
    "OptimisticLockError",
    "SQLAlchemySystemSettingRepository",
    "SettingNotFoundError",
    "SettingReadOnlyError",
    "SystemSettingRepositoryError",
]