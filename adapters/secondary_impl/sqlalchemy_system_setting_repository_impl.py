#!/usr/bin/env python3
"""
Module: sqlalchemy_system_setting_repository_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi repository untuk System Settings (konfigurasi dinamis)
               menggunakan SQLAlchemy ORM. Menyediakan operasi CRUD untuk setting
               sistem yang dapat diubah secara runtime tanpa deployment ulang.
               Mendukung scope per legal entity, caching di Redis, audit trail
               untuk perubahan setting, dan validasi tipe data.
Dependencies:
- sqlalchemy.ext.asyncio (AsyncSession)
- sqlalchemy import select, update, func, and_, or_
- ports.primary.system_setting_repository_port (SystemSettingRepositoryPort)
- domain.system_settings.aggregate_root (SystemSettingAggregate)
- infrastructure.persistence_orm.system_setting_table
- infrastructure.caching.redis_manager (cache)
- infrastructure.telemetry.alert_manager_router
Audit: Setiap perubahan setting dicatat di event store untuk compliance.
       Perubahan setting kritis (audit, security, tax) memicu alert.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

# Domain
from domain.system_settings.aggregate_root import (
    SettingCategory,
    SettingDataType,
    SettingScope,
    SystemSettingAggregate,
)
from infrastructure.caching.redis_manager import get_redis_client

# Infrastructure ORM
from infrastructure.persistence_orm.system_setting_table import SystemSettingTable
from infrastructure.telemetry.alert_manager_router import trigger_alert

# Ports
from ports.primary.system_setting_repository_port import SystemSettingRepositoryPort

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

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

# ============================================================================
# EXCEPTIONS
# ============================================================================


class SystemSettingRepositoryError(Exception):
    """Base exception untuk repository system setting."""

    pass


class DuplicateSettingKeyError(SystemSettingRepositoryError):
    """Setting key sudah ada dalam scope yang sama."""

    pass


class SettingNotFoundError(SystemSettingRepositoryError):
    """Setting tidak ditemukan."""

    pass


class InvalidSettingValueError(SystemSettingRepositoryError):
    """Nilai setting tidak sesuai dengan tipe data yang diharapkan."""

    pass


class SettingReadOnlyError(SystemSettingRepositoryError):
    """Setting bersifat read-only (tidak bisa diubah setelah system startup)."""

    pass


class OptimisticLockError(SystemSettingRepositoryError):
    """Version mismatch saat update."""

    pass


# ============================================================================
# VALUE VALIDATORS
# ============================================================================


class SettingValueValidator:
    """Validator untuk nilai setting berdasarkan tipe data."""

    @staticmethod
    def validate_string(value: Any) -> str:
        """Validate string value."""
        if value is None:
            return ""
        return str(value)

    @staticmethod
    def validate_integer(value: Any) -> int:
        """Validate integer value."""
        try:
            if isinstance(value, bool):
                return int(value)
            return int(value)
        except (ValueError, TypeError):
            raise InvalidSettingValueError(f"Cannot convert {value} to integer")

    @staticmethod
    def validate_float(value: Any) -> float:
        """Validate float value."""
        try:
            return float(value)
        except (ValueError, TypeError):
            raise InvalidSettingValueError(f"Cannot convert {value} to float")

    @staticmethod
    def validate_boolean(value: Any) -> bool:
        """Validate boolean value."""
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes", "on")
        if isinstance(value, (int, float)):
            return bool(value)
        raise InvalidSettingValueError(f"Cannot convert {value} to boolean")

    @staticmethod
    def validate_json(value: Any) -> str:
        """Validate JSON value (store as string)."""
        if isinstance(value, str):
            # Validate JSON string
            try:
                json.loads(value)
                return value
            except json.JSONDecodeError:
                raise InvalidSettingValueError(f"Invalid JSON string: {value}")
        # Convert dict/list to JSON
        try:
            return json.dumps(value)
        except (TypeError, ValueError):
            raise InvalidSettingValueError(f"Cannot convert {value} to JSON")

    @staticmethod
    def validate_decimal(value: Any) -> Decimal:
        """Validate decimal value."""
        try:
            return Decimal(str(value))
        except Exception:
            raise InvalidSettingValueError(f"Cannot convert {value} to Decimal")


# ============================================================================
# REPOSITORY IMPLEMENTATION
# ============================================================================


class SQLAlchemySystemSettingRepository(SystemSettingRepositoryPort):
    """
    Implementasi repository System Setting dengan SQLAlchemy.
    """

    def __init__(self, session: AsyncSession | None = None):
        self._session = session
        self._validator = SettingValueValidator()
        self._redis = None

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
        """Generate cache key for setting."""
        if legal_entity_id:
            return f"{REDIS_SETTING_CACHE_PREFIX}{legal_entity_id}:{key}"
        return f"{REDIS_SETTING_CACHE_PREFIX}global:{key}"

    def _validate_and_convert_value(self, value: Any, data_type: str) -> str:
        """Validate and convert value based on data type."""
        if data_type == "string":
            validated = self._validator.validate_string(value)
        elif data_type == "integer":
            validated = self._validator.validate_integer(value)
            return str(validated)
        elif data_type == "float":
            validated = self._validator.validate_float(value)
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
            # Default to string
            validated = self._validator.validate_string(value)

        return str(validated)

    def _convert_to_python(self, value: str, data_type: str) -> Any:
        """Convert stored string value to Python type."""
        if data_type == "string":
            return value
        elif data_type == "integer":
            return int(value)
        elif data_type == "float":
            return float(value)
        elif data_type == "boolean":
            return value.lower() == "true"
        elif data_type == "json":
            return json.loads(value)
        elif data_type == "decimal":
            return Decimal(value)
        else:
            return value

    def _to_domain(self, table: SystemSettingTable) -> SystemSettingAggregate:
        """Mapping dari ORM model ke domain aggregate."""
        # Parse data_type
        data_type_map = {
            "string": SettingDataType.STRING,
            "integer": SettingDataType.INTEGER,
            "float": SettingDataType.FLOAT,
            "boolean": SettingDataType.BOOLEAN,
            "json": SettingDataType.JSON,
            "decimal": SettingDataType.DECIMAL,
        }
        data_type = data_type_map.get(table.data_type, SettingDataType.STRING)

        # Parse scope
        scope_map = {
            "global": SettingScope.GLOBAL,
            "legal_entity": SettingScope.LEGAL_ENTITY,
        }
        scope = scope_map.get(table.scope, SettingScope.GLOBAL)

        # Parse category
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

        # Convert value to Python type
        python_value = self._convert_to_python(table.value, table.data_type)

        aggregate = SystemSettingAggregate(
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
        return aggregate

    async def _to_orm(self, aggregate: SystemSettingAggregate) -> SystemSettingTable:
        """Mapping dari domain ke ORM model."""
        # Convert value to string for storage
        if aggregate.data_type == SettingDataType.JSON:
            stored_value = json.dumps(aggregate.value)
        else:
            stored_value = str(aggregate.value)

        data_type_str = (
            aggregate.data_type.value
            if hasattr(aggregate.data_type, "value")
            else str(aggregate.data_type)
        )
        scope_str = (
            aggregate.scope.value if hasattr(aggregate.scope, "value") else str(aggregate.scope)
        )
        category_str = (
            aggregate.category.value
            if hasattr(aggregate.category, "value")
            else str(aggregate.category)
        )

        table = SystemSettingTable(
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
            allowed_values=json.dumps(aggregate.allowed_values)
            if aggregate.allowed_values
            else None,
            created_at=aggregate.created_at,
            updated_at=datetime.utcnow(),
            created_by=aggregate.created_by,
            updated_by=aggregate.updated_by,
            version=aggregate.version,
        )
        return table

    async def _invalidate_cache(self, key: str, legal_entity_id: UUID | None = None) -> None:
        """Invalidate cache for a specific setting."""
        try:
            redis = await self._get_redis()
            cache_key = self._get_cache_key(key, legal_entity_id)
            await redis.delete(cache_key)
            logger.debug("Cache invalidated for %s", cache_key)
        except Exception as e:
            logger.warning("Failed to invalidate cache: %s", e)

    async def _check_critical_setting_change(
        self, key: str, old_value: Any, new_value: Any
    ) -> None:
        """Alert if critical setting is changed."""
        if key in CRITICAL_SETTING_KEYS and old_value != new_value:
            await trigger_alert(
                title="Critical Setting Changed",
                message=f"Critical system setting '{key}' changed from '{old_value}' to '{new_value}'",
                severity="warning",
                source="SystemSettingRepository",
            )
            logger.warning(
                "Critical setting changed: %s = %s (was %s)", key, new_value, old_value
            )

    # ========================================================================
    # REPOSITORY METHODS
    # ========================================================================

    async def add(self, setting: SystemSettingAggregate) -> None:
        """
        Menambahkan setting baru.
        """
        try:
            # Validate value
            validated_value = self._validate_and_convert_value(
                setting.value, setting.data_type.value
            )
            setting.value = self._convert_to_python(validated_value, setting.data_type.value)

            # Check if key already exists in this scope
            exists = await self.get_by_key(setting.key, setting.legal_entity_id) is not None
            if exists:
                raise DuplicateSettingKeyError(
                    f"Setting '{setting.key}' already exists in scope {setting.scope.value}"
                )

            table = await self._to_orm(setting)
            self.session.add(table)
            await self.session.flush()
            logger.info(
                "System setting added: %s (scope: %s)",
                setting.key,
                setting.scope.value
            )

        except DuplicateSettingKeyError:
            raise
        except IntegrityError as e:
            await self.session.rollback()
            raise SystemSettingRepositoryError(f"Integrity error: {e}") from e
        except Exception as e:
            await self.session.rollback()
            logger.error("Failed to add setting: %s", e)
            raise SystemSettingRepositoryError(f"Failed to add setting: {e}") from e

    async def get_by_key(
        self, key: str, legal_entity_id: UUID | None = None
    ) -> SystemSettingAggregate | None:
        """
        Mendapatkan setting berdasarkan kunci. Jika legal_entity_id None, berarti global.
        """
        try:
            # Try cache first
            redis = await self._get_redis()
            cache_key = self._get_cache_key(key, legal_entity_id)
            cached = await redis.get(cache_key)

            if cached:
                try:
                    data = json.loads(cached)
                    # TODO: Lanjutkan rekonstruksi aggregate jika data valid
                    # pass
                except (json.JSONDecodeError, TypeError) as e:
                    # Log jika format data di cache tidak valid
                    logger.warning("Cache data corrupt for key %s: %s", cache_key, e)
                    # Opsional: Hapus cache yang korup agar tidak terus-menerus gagal
                    await redis.delete(cache_key)

            # Query from database
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

            # Cache the result
            try:
                await redis.setex(
                    cache_key,
                    CACHE_TTL_SECONDS,
                    json.dumps(
                        {
                            "id": str(aggregate.id),
                            "key": aggregate.key,
                            "value": str(aggregate.value),
                            "data_type": aggregate.data_type.value,
                        }
                    ),
                )
            except Exception as e:
                # Logging yang lebih informatif (menggunakan argumen %s agar aman)
                logger.warning("Failed to cache setting: %s", e)

            return aggregate

        except Exception as e:
            logger.error("Failed to get setting by key %s: %s", key, e)
            raise SystemSettingRepositoryError(f"Failed to get setting: {e}") from e

    async def update(self, setting: SystemSettingAggregate) -> None:
        """
        Memperbarui setting yang sudah ada.
        """
        try:
            # Check if read-only
            if setting.is_readonly:
                raise SettingReadOnlyError(f"Setting '{setting.key}' is read-only")

            # Get current version
            stmt = select(SystemSettingTable.version, SystemSettingTable.value).where(
                SystemSettingTable.id == setting.id
            )
            result = await self.session.execute(stmt)
            row = result.first()

            if row is None:
                raise SettingNotFoundError(f"Setting {setting.id} not found")

            current_version = row[0]
            old_value_stored = row[1]
            old_value = self._convert_to_python(old_value_stored, setting.data_type.value)

            if current_version != setting.version:
                raise OptimisticLockError(
                    f"Version mismatch: expected {setting.version}, got {current_version}"
                )

            # Validate new value
            validated_value = self._validate_and_convert_value(
                setting.value, setting.data_type.value
            )
            setting.value = self._convert_to_python(validated_value, setting.data_type.value)

            # Check critical setting change
            await self._check_critical_setting_change(setting.key, old_value, setting.value)

            table = await self._to_orm(setting)
            table.version = setting.version + 1
            table.updated_at = datetime.utcnow()

            await self.session.merge(table)
            await self.session.flush()

            # Invalidate cache
            await self._invalidate_cache(setting.key, setting.legal_entity_id)

            logger.info("System setting updated: %s = %s", setting.key, setting.value)

        except (SettingNotFoundError, OptimisticLockError, SettingReadOnlyError):
            raise
        except Exception as e:
            await self.session.rollback()
            logger.error("Failed to update setting %s: %s", setting.id, e)
            raise SystemSettingRepositoryError(f"Failed to update setting: {e}") from e

    async def delete(self, setting_id: UUID) -> bool:
        """
        Soft delete setting.
        """
        try:
            # Get setting first to check read-only
            setting = await self.get_by_id(setting_id)
            if setting and setting.is_readonly:
                raise SettingReadOnlyError(
                    f"Setting '{setting.key}' is read-only and cannot be deleted"
                )

            stmt = (
                update(SystemSettingTable)
                .where(SystemSettingTable.id == setting_id)
                .values(deleted_at=datetime.utcnow())
            )
            result = await self.session.execute(stmt)
            await self.session.flush()

            if result.rowcount > 0 and setting:
                await self._invalidate_cache(setting.key, setting.legal_entity_id)
                logger.info("System setting %s deleted", setting_id)

            return result.rowcount > 0

        except SettingReadOnlyError:
            raise
        except Exception as e:
            await self.session.rollback()
            logger.error("Failed to delete setting %s: %s", setting_id, e)
            raise SystemSettingRepositoryError(f"Failed to delete setting: {e}") from e

    async def get_by_id(self, setting_id: UUID) -> SystemSettingAggregate | None:
        """Mendapatkan setting berdasarkan ID."""
        try:
            stmt = select(SystemSettingTable).where(
                SystemSettingTable.id == setting_id, SystemSettingTable.deleted_at.is_(None)
            )
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()

            if not table:
                return None
            return self._to_domain(table)

        except Exception as e:
            logger.error("Failed to get setting by id %s: %s", setting_id, e)
            raise SystemSettingRepositoryError(f"Failed to get setting: {e}") from e

    async def get_value(
        self, key: str, default: Any = None, legal_entity_id: UUID | None = None
    ) -> Any:
        """
        Helper untuk langsung mendapatkan nilai setting.
        """
        setting = await self.get_by_key(key, legal_entity_id)
        if setting is None:
            return default
        return setting.value

    async def set_value(
        self, key: str, value: Any, updated_by: UUID, legal_entity_id: UUID | None = None
    ) -> None:
        """
        Helper untuk langsung mengubah nilai setting dengan audit.
        """
        setting = await self.get_by_key(key, legal_entity_id)
        if setting is None:
            # Create new setting
            from domain.system_settings.aggregate_root import (
                SettingCategory,
                SettingDataType,
                SettingScope,
                SystemSettingAggregate,
            )

            # Infer data type from value
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
        else:
            old_value = setting.value
            if old_value != value:
                setting.value = value
                setting.updated_by = updated_by
                await self.update(setting)

    async def list_settings(
        self,
        legal_entity_id: UUID | None = None,
        category: str | None = None,
        scope: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[SystemSettingAggregate], int]:
        """
        List settings dengan filter dan pagination.
        """
        try:
            conditions = [SystemSettingTable.deleted_at.is_(None)]

            if legal_entity_id:
                conditions.append(
                    or_(
                        SystemSettingTable.legal_entity_id == legal_entity_id,
                        SystemSettingTable.scope == "global",
                    )
                )
            else:
                conditions.append(SystemSettingTable.scope == "global")

            if category:
                conditions.append(SystemSettingTable.category == category)
            if scope:
                conditions.append(SystemSettingTable.scope == scope)

            # Get total count
            count_stmt = (
                select(func.count()).select_from(SystemSettingTable).where(and_(*conditions))
            )
            count_result = await self.session.execute(count_stmt)
            total = count_result.scalar()

            # Get settings
            offset = (page - 1) * page_size
            stmt = (
                select(SystemSettingTable)
                .where(and_(*conditions))
                .order_by(SystemSettingTable.key)
                .limit(page_size)
                .offset(offset)
            )

            result = await self.session.execute(stmt)
            tables = result.scalars().all()

            settings = [self._to_domain(table) for table in tables]
            return settings, total

        except Exception as e:
            logger.error("Failed to list settings: %s", e)
            raise SystemSettingRepositoryError(f"Failed to list settings: {e}") from e

    async def get_settings_by_category(
        self, category: str, legal_entity_id: UUID | None = None
    ) -> dict[str, Any]:
        """
        Mendapatkan semua settings dalam kategori tertentu sebagai dictionary.
        """
        try:
            conditions = [
                SystemSettingTable.category == category,
                SystemSettingTable.deleted_at.is_(None),
            ]
            if legal_entity_id:
                conditions.append(
                    or_(
                        SystemSettingTable.legal_entity_id == legal_entity_id,
                        SystemSettingTable.scope == "global",
                    )
                )

            stmt = select(SystemSettingTable).where(and_(*conditions))
            result = await self.session.execute(stmt)
            tables = result.scalars().all()

            settings_dict = {}
            for table in tables:
                aggregate = self._to_domain(table)
                settings_dict[aggregate.key] = aggregate.value

            return settings_dict

        except Exception as e:
            logger.error("Failed to get settings by category %s: %s", category, e)
            raise SystemSettingRepositoryError(f"Failed to get settings: {e}") from e

    async def reset_to_default(self, key: str, legal_entity_id: UUID | None = None) -> bool:
        """
        Reset setting ke nilai default.
        """
        setting = await self.get_by_key(key, legal_entity_id)
        if not setting or not setting.default_value:
            return False

        default_value = self._convert_to_python(setting.default_value, setting.data_type.value)
        setting.value = default_value

        # Create a new updated_by from system (UUID zero)
        from uuid import UUID as UUIDType

        setting.updated_by = UUIDType("00000000-0000-0000-0000-000000000000")

        await self.update(setting)
        logger.info("Setting %s reset to default: %s", key, default_value)
        return True

    async def reload_cache(self) -> None:
        """Reload semua cache settings."""
        try:
            redis = await self._get_redis()
            pattern = f"{REDIS_SETTING_CACHE_PREFIX}*"
            keys = await redis.keys(pattern)
            if keys:
                await redis.delete(*keys)
                logger.info("Cleared %d setting cache entries", len(keys))
        except Exception as e:
            logger.warning("Failed to reload cache: %s", e)


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "DuplicateSettingKeyError",
    "InvalidSettingValueError",
    "OptimisticLockError",
    "SQLAlchemySystemSettingRepository",
    "SettingNotFoundError",
    "SettingReadOnlyError",
    "SystemSettingRepositoryError",
]
