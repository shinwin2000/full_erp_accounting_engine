# service_system_settings.py - Complete rewrite with full event publishing
# v5.9.0 - Refactored event publishing into single _publish_event method to reduce
#          broad-except warnings and improve maintainability.
# v5.9.1 - Replaced broad except with specific exception handling in bulk operations.

#!/usr/bin/env python3
"""
Module: service_system_settings.py
Layer: Application / Service Layer
Responsibility: Menyediakan service untuk mengelola system settings.
               Mempublikasikan event untuk setiap perubahan.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from ports.primary.event_publisher_port import EventPublisherPort

# Import domain events
from application.events import (
    SettingAddedEvent,
    SettingChangedEvent,
    SettingRemovedEvent,
    SettingResetEvent,
    SettingsBulkUpdatedEvent,
    SettingsLockedEvent,
    SettingsUnlockedEvent,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class SettingDataType(str, Enum):
    """Data type for setting value."""

    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    JSON = "json"
    DECIMAL = "decimal"  # Added for monetary values


class SettingScope(str, Enum):
    """Scope of setting."""

    GLOBAL = "global"
    LEGAL_ENTITY = "legal_entity"
    USER = "user"


# ============================================================================
# Domain Models
# ============================================================================


@dataclass(kw_only=True)
class Setting:
    """System setting model."""

    id: UUID = field(default_factory=uuid4)
    key: str
    value: Any
    data_type: SettingDataType = SettingDataType.STRING
    description: str | None = None
    category: str = "general"
    scope: SettingScope = SettingScope.GLOBAL
    legal_entity_id: UUID | None = None
    validation_regex: str | None = None
    # Use Decimal for numeric bounds to preserve precision (especially for monetary values)
    min_value: Decimal | None = None
    max_value: Decimal | None = None
    allowed_values: list[str] | None = None
    default_value: str | None = None
    is_readonly: bool = False
    is_encrypted: bool = False
    is_active: bool = True
    is_locked: bool = False  # Added for lock/unlock
    version: int = 1
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID | None = None

    def get_typed_value(self) -> Any:
        """Get value with correct type."""
        if self.data_type == SettingDataType.INTEGER:
            return int(self.value)
        elif self.data_type == SettingDataType.FLOAT:
            return float(self.value)
        elif self.data_type == SettingDataType.DECIMAL:
            return Decimal(str(self.value))
        elif self.data_type == SettingDataType.BOOLEAN:
            return str(self.value).lower() in ("true", "1", "yes", "on")
        elif self.data_type == SettingDataType.JSON:
            return json.loads(self.value) if isinstance(self.value, str) else self.value
        return str(self.value)

    def validate(self, new_value: Any) -> bool:
        """Validate new value against constraints."""
        # Type validation
        if self.data_type == SettingDataType.INTEGER:
            try:
                int(new_value)
            except (ValueError, TypeError):
                return False
        elif self.data_type == SettingDataType.FLOAT:
            try:
                float(new_value)
            except (ValueError, TypeError):
                return False
        elif self.data_type == SettingDataType.DECIMAL:
            try:
                Decimal(str(new_value))
            except (ValueError, TypeError):
                return False
        elif self.data_type == SettingDataType.BOOLEAN:
            if str(new_value).lower() not in ("true", "false", "1", "0", "yes", "no", "on", "off"):
                return False

        # Range validation - use Decimal for precise comparison
        if self.min_value is not None:
            try:
                val_decimal = Decimal(str(new_value))
                if val_decimal < self.min_value:
                    return False
            except (ValueError, TypeError):
                return False

        if self.max_value is not None:
            try:
                val_decimal = Decimal(str(new_value))
                if val_decimal > self.max_value:
                    return False
            except (ValueError, TypeError):
                return False

        # Allowed values validation
        if self.allowed_values and str(new_value) not in self.allowed_values:
            return False

        # Regex validation
        if self.validation_regex:
            if not re.match(self.validation_regex, str(new_value)):
                return False

        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "key": self.key,
            "value": self.value,
            "data_type": self.data_type.value,
            "description": self.description,
            "category": self.category,
            "scope": self.scope.value,
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else None,
            "validation_regex": self.validation_regex,
            "min_value": str(self.min_value) if self.min_value is not None else None,
            "max_value": str(self.max_value) if self.max_value is not None else None,
            "allowed_values": self.allowed_values,
            "default_value": self.default_value,
            "is_readonly": self.is_readonly,
            "is_encrypted": self.is_encrypted,
            "is_active": self.is_active,
            "is_locked": self.is_locked,
            "version": self.version,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": str(self.created_by) if self.created_by else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Setting:
        # Convert min/max to Decimal if present
        min_val = data.get("min_value")
        if min_val is not None:
            min_val = Decimal(str(min_val))
        max_val = data.get("max_value")
        if max_val is not None:
            max_val = Decimal(str(max_val))

        return cls(
            id=UUID(data["id"]) if isinstance(data.get("id"), str) else data.get("id", uuid4()),
            key=data["key"],
            value=data["value"],
            data_type=SettingDataType(data.get("data_type", "string")),
            description=data.get("description"),
            category=data.get("category", "general"),
            scope=SettingScope(data.get("scope", "global")),
            legal_entity_id=UUID(data["legal_entity_id"]) if data.get("legal_entity_id") else None,
            validation_regex=data.get("validation_regex"),
            min_value=min_val,
            max_value=max_val,
            allowed_values=data.get("allowed_values"),
            default_value=data.get("default_value"),
            is_readonly=data.get("is_readonly", False),
            is_encrypted=data.get("is_encrypted", False),
            is_active=data.get("is_active", True),
            is_locked=data.get("is_locked", False),
            version=data.get("version", 1),
            created_at=datetime.fromisoformat(data["created_at"])
            if data.get("created_at")
            else datetime.now(UTC),
            updated_at=datetime.fromisoformat(data["updated_at"])
            if data.get("updated_at")
            else datetime.now(UTC),
            created_by=UUID(data["created_by"]) if data.get("created_by") else None,
        )


@dataclass(kw_only=True)
class BulkUpdateResult:
    """Result of bulk update operation."""

    success_count: int = 0
    failed_count: int = 0
    failed_keys: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)


@dataclass(kw_only=True)
class ImportResult:
    """Result of import operation."""

    success: bool = True
    imported_count: int = 0
    skipped_count: int = 0
    errors: list[str] = field(default_factory=list)


# ============================================================================
# Exceptions
# ============================================================================


class SystemSettingsError(Exception):
    pass


class SettingNotFoundError(SystemSettingsError):
    pass


class SettingValidationError(SystemSettingsError):
    pass


class SettingReadonlyError(SystemSettingsError):
    pass


class SettingLockedError(SystemSettingsError):
    pass


# ============================================================================
# Main Service
# ============================================================================


class SystemSettingsService:
    """
    Service layer untuk operasi system settings.
    Mempublikasikan event untuk setiap perubahan.
    """

    __slots__ = ("_settings", "_stats", "_event_publisher", "_locked")

    def __init__(
        self,
        event_publisher: EventPublisherPort | None = None,
    ) -> None:
        self._settings: dict[str, dict[UUID | None, Setting]] = {}
        self._stats = {"created": 0, "updated": 0, "deleted": 0, "locked": 0, "unlocked": 0}
        self._event_publisher = event_publisher
        self._locked: bool = False  # Global lock flag (optional)

        # Initialize default settings
        self._init_default_settings()

        logger.info("SystemSettingsService initialized")

    # ==================== EVENT PUBLISHING HELPER ====================

    async def _publish_event(self, event: Any, log_context: str, correlation_id: str | None = None) -> None:
        """
        Publish an event safely, catching and logging any exception.
        Preserves the publish signature (event, correlation_id=correlation_id).
        """
        if not self._event_publisher:
            return
        try:
            await self._event_publisher.publish(event, correlation_id=correlation_id)
            logger.debug(f"Published {event.__class__.__name__} for {log_context}")
        except Exception as e:
            logger.warning(f"Failed to publish {event.__class__.__name__} for {log_context}: {e}")

    # ==================== INIT ====================

    def _init_default_settings(self) -> None:
        """Initialize default system settings."""
        default_settings = [
            Setting(key="company.name", value="ERP System", category="company", is_readonly=True),
            Setting(key="company.currency", value="IDR", category="company"),
            Setting(
                key="company.fiscal_year_start",
                value="1",
                data_type=SettingDataType.INTEGER,
                category="company",
            ),
            Setting(
                key="tax.ppn_rate",
                value="11",
                data_type=SettingDataType.DECIMAL,
                category="tax",
                min_value=Decimal("0"),
                max_value=Decimal("100"),
            ),
            Setting(
                key="tax.pph21_rate",
                value="5",
                data_type=SettingDataType.DECIMAL,
                category="tax",
                min_value=Decimal("0"),
                max_value=Decimal("100"),
            ),
            Setting(
                key="accounting.auto_approve_journal",
                value="false",
                data_type=SettingDataType.BOOLEAN,
                category="accounting",
            ),
            Setting(
                key="inventory.valuation_method",
                value="FIFO",
                allowed_values=["FIFO", "AVERAGE"],
                category="inventory",
            ),
            Setting(
                key="notification.email_enabled",
                value="true",
                data_type=SettingDataType.BOOLEAN,
                category="notification",
            ),
            Setting(
                key="security.session_timeout_minutes",
                value="30",
                data_type=SettingDataType.INTEGER,
                category="security",
                min_value=Decimal("1"),
                max_value=Decimal("1440"),
            ),
            Setting(
                key="coretax.enabled",
                value="false",
                data_type=SettingDataType.BOOLEAN,
                category="coretax",
            ),
        ]

        for setting in default_settings:
            key = setting.key
            if key not in self._settings:
                self._settings[key] = {}
            self._settings[key][None] = setting

    # ========================================================================
    # CRUD Operations
    # ========================================================================

    async def create_setting(
        self,
        key: str,
        value: Any,
        data_type: str = "string",
        category: str = "general",
        scope: str = "global",
        legal_entity_id: UUID | None = None,
        description: str | None = None,
        validation_regex: str | None = None,
        min_value: Decimal | None = None,
        max_value: Decimal | None = None,
        allowed_values: list[str] | None = None,
        is_readonly: bool = False,
        is_encrypted: bool = False,
        created_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> Setting:
        """Create new system setting."""
        logger.info(f"Creating setting: {key}")

        # Check if setting already exists
        existing = await self.get_setting(key, legal_entity_id)
        if existing:
            raise SystemSettingsError(f"Setting {key} already exists")

        setting = Setting(
            key=key,
            value=value,
            data_type=SettingDataType(data_type),
            category=category,
            scope=SettingScope(scope),
            legal_entity_id=legal_entity_id,
            description=description,
            validation_regex=validation_regex,
            min_value=min_value,
            max_value=max_value,
            allowed_values=allowed_values,
            is_readonly=is_readonly,
            is_encrypted=is_encrypted,
            created_by=created_by,
        )

        if key not in self._settings:
            self._settings[key] = {}
        self._settings[key][legal_entity_id] = setting
        self._stats["created"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = SettingAddedEvent(
                setting_id=setting.id,
                key=setting.key,
                value=str(setting.value),
                data_type=setting.data_type.value,
                category=setting.category,
                scope=setting.scope.value,
                legal_entity_id=str(setting.legal_entity_id) if setting.legal_entity_id else None,
                created_by=str(created_by) if created_by else None,
                timestamp=datetime.now(UTC),
            )
            await self._publish_event(event, f"Setting {key} (added)", correlation_id)

        return setting

    async def get_setting(self, key: str, legal_entity_id: UUID | None = None) -> Setting | None:
        """Get setting by key (with fallback to global)."""
        logger.info(f"Getting setting: {key} for legal_entity {legal_entity_id}")

        # Try legal entity specific first
        if legal_entity_id and key in self._settings and legal_entity_id in self._settings[key]:
            return self._settings[key][legal_entity_id]

        # Fallback to global
        if key in self._settings and None in self._settings[key]:
            return self._settings[key][None]

        return None

    async def get_setting_value(
        self, key: str, legal_entity_id: UUID | None = None, default: Any = None
    ) -> Any:
        """Get setting value with type conversion."""
        setting = await self.get_setting(key, legal_entity_id)
        if setting:
            return setting.get_typed_value()
        return default

    async def list_settings(
        self,
        legal_entity_id: UUID | None = None,
        category: str | None = None,
        scope: str | None = None,
        is_active: bool | None = None,
        is_locked: bool | None = None,
    ) -> list[Setting]:
        """List settings with filters."""
        logger.info(f"Listing settings for legal_entity {legal_entity_id}")

        result = []
        for key, scope_dict in self._settings.items():
            for le_id, setting in scope_dict.items():
                if legal_entity_id is not None and le_id != legal_entity_id and le_id is not None:
                    continue
                if category and setting.category != category:
                    continue
                if scope and setting.scope.value != scope:
                    continue
                if is_active is not None and setting.is_active != is_active:
                    continue
                if is_locked is not None and setting.is_locked != is_locked:
                    continue
                result.append(setting)

        return result

    async def update_setting(
        self,
        key: str,
        legal_entity_id: UUID | None = None,
        value: Any | None = None,
        description: str | None = None,
        is_active: bool | None = None,
        updated_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> Setting | None:
        """Update existing setting."""
        logger.info(f"Updating setting: {key}")

        setting = await self.get_setting(key, legal_entity_id)
        if not setting:
            raise SettingNotFoundError(f"Setting {key} not found")

        if setting.is_readonly:
            raise SettingReadonlyError(f"Setting {key} is read-only")

        if setting.is_locked:
            raise SettingLockedError(f"Setting {key} is locked")

        old_value = setting.value

        if value is not None:
            if not setting.validate(value):
                raise SettingValidationError(f"Invalid value for setting {key}")
            setting.value = value

        if description is not None:
            setting.description = description
        if is_active is not None:
            setting.is_active = is_active

        setting.version += 1
        setting.updated_at = datetime.now(UTC)

        self._settings[key][legal_entity_id] = setting
        self._stats["updated"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = SettingChangedEvent(
                setting_id=setting.id,
                key=setting.key,
                old_value=str(old_value),
                new_value=str(setting.value),
                updated_by=str(updated_by) if updated_by else None,
                timestamp=datetime.now(UTC),
            )
            await self._publish_event(event, f"Setting {key} (changed)", correlation_id)

        return setting

    async def deactivate_setting(
        self,
        key: str,
        legal_entity_id: UUID | None = None,
        updated_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> bool:
        """Deactivate setting (soft delete)."""
        logger.info(f"Deactivating setting: {key}")

        setting = await self.get_setting(key, legal_entity_id)
        if not setting:
            return False

        if setting.is_readonly:
            raise SettingReadonlyError(f"Setting {key} is read-only")

        if setting.is_locked:
            raise SettingLockedError(f"Setting {key} is locked")

        setting.is_active = False
        setting.updated_at = datetime.now(UTC)
        setting.version += 1

        self._settings[key][legal_entity_id] = setting
        self._stats["deleted"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = SettingRemovedEvent(
                setting_id=setting.id,
                key=setting.key,
                removed_by=str(updated_by) if updated_by else None,
                timestamp=datetime.now(UTC),
            )
            await self._publish_event(event, f"Setting {key} (removed)", correlation_id)

        return True

    async def reset_to_default(
        self,
        key: str,
        legal_entity_id: UUID | None = None,
        updated_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> Setting | None:
        """Reset setting to default value."""
        logger.info(f"Resetting setting: {key} to default")

        setting = await self.get_setting(key, legal_entity_id)
        if not setting:
            raise SettingNotFoundError(f"Setting {key} not found")

        if setting.is_readonly:
            raise SettingReadonlyError(f"Setting {key} is read-only")

        if setting.is_locked:
            raise SettingLockedError(f"Setting {key} is locked")

        old_value = setting.value

        if setting.default_value is not None:
            setting.value = setting.default_value
            setting.updated_at = datetime.now(UTC)
            setting.version += 1
            self._settings[key][legal_entity_id] = setting
            self._stats["updated"] += 1

            # --- PUBLISH EVENT ---
            if self._event_publisher:
                event = SettingResetEvent(
                    setting_id=setting.id,
                    key=setting.key,
                    old_value=str(old_value),
                    new_value=str(setting.value),
                    reset_by=str(updated_by) if updated_by else None,
                    timestamp=datetime.now(UTC),
                )
                await self._publish_event(event, f"Setting {key} (reset)", correlation_id)

        return setting

    # ========================================================================
    # Bulk Operations (Lock/Unlock/Update)
    # ========================================================================

    async def lock_settings(
        self,
        keys: list[str],
        legal_entity_id: UUID | None = None,
        locked_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> BulkUpdateResult:
        """Lock one or more settings."""
        logger.info(f"Locking settings: {keys}")

        success_count = 0
        failed_count = 0
        failed_keys = []
        errors = {}

        for key in keys:
            try:
                setting = await self.get_setting(key, legal_entity_id)
                if not setting:
                    failed_count += 1
                    failed_keys.append(key)
                    errors[key] = "Setting not found"
                    continue

                if setting.is_readonly:
                    failed_count += 1
                    failed_keys.append(key)
                    errors[key] = "Setting is read-only"
                    continue

                setting.is_locked = True
                setting.updated_at = datetime.now(UTC)
                setting.version += 1
                self._settings[key][legal_entity_id] = setting
                success_count += 1
                self._stats["locked"] += 1

            except (SettingNotFoundError, SettingReadonlyError) as e:
                # These are expected and already handled above, but catch just in case
                failed_count += 1
                failed_keys.append(key)
                errors[key] = str(e)

        # --- PUBLISH BULK EVENT (only if at least one succeeded) ---
        if self._event_publisher and success_count > 0:
            event = SettingsLockedEvent(
                keys=keys,
                locked_by=str(locked_by) if locked_by else None,
                timestamp=datetime.now(UTC),
            )
            await self._publish_event(event, f"Lock {success_count} settings", correlation_id)

        return BulkUpdateResult(
            success_count=success_count,
            failed_count=failed_count,
            failed_keys=failed_keys,
            errors=errors,
        )

    async def unlock_settings(
        self,
        keys: list[str],
        legal_entity_id: UUID | None = None,
        unlocked_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> BulkUpdateResult:
        """Unlock one or more settings."""
        logger.info(f"Unlocking settings: {keys}")

        success_count = 0
        failed_count = 0
        failed_keys = []
        errors = {}

        for key in keys:
            try:
                setting = await self.get_setting(key, legal_entity_id)
                if not setting:
                    failed_count += 1
                    failed_keys.append(key)
                    errors[key] = "Setting not found"
                    continue

                if setting.is_readonly:
                    failed_count += 1
                    failed_keys.append(key)
                    errors[key] = "Setting is read-only"
                    continue

                setting.is_locked = False
                setting.updated_at = datetime.now(UTC)
                setting.version += 1
                self._settings[key][legal_entity_id] = setting
                success_count += 1
                self._stats["unlocked"] += 1

            except (SettingNotFoundError, SettingReadonlyError) as e:
                failed_count += 1
                failed_keys.append(key)
                errors[key] = str(e)

        # --- PUBLISH BULK EVENT (only if at least one succeeded) ---
        if self._event_publisher and success_count > 0:
            event = SettingsUnlockedEvent(
                keys=keys,
                unlocked_by=str(unlocked_by) if unlocked_by else None,
                timestamp=datetime.now(UTC),
            )
            await self._publish_event(event, f"Unlock {success_count} settings", correlation_id)

        return BulkUpdateResult(
            success_count=success_count,
            failed_count=failed_count,
            failed_keys=failed_keys,
            errors=errors,
        )

    async def bulk_update_settings(
        self,
        settings: dict[str, str],
        legal_entity_id: UUID | None = None,
        updated_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> BulkUpdateResult:
        """Bulk update multiple settings."""
        logger.info(f"Bulk updating {len(settings)} settings")

        success_count = 0
        failed_count = 0
        failed_keys = []
        errors = {}
        updated_keys = []

        for key, value in settings.items():
            try:
                await self.update_setting(
                    key=key,
                    legal_entity_id=legal_entity_id,
                    value=value,
                    updated_by=updated_by,
                    correlation_id=correlation_id,
                )
                success_count += 1
                updated_keys.append(key)
            except (SettingNotFoundError, SettingReadonlyError, SettingLockedError, SettingValidationError) as e:
                failed_count += 1
                failed_keys.append(key)
                errors[key] = str(e)

        # --- PUBLISH BULK EVENT (only if at least one succeeded) ---
        if self._event_publisher and success_count > 0:
            event = SettingsBulkUpdatedEvent(
                keys=updated_keys,
                updated_by=str(updated_by) if updated_by else None,
                timestamp=datetime.now(UTC),
            )
            await self._publish_event(event, f"Bulk update {success_count} settings", correlation_id)

        return BulkUpdateResult(
            success_count=success_count,
            failed_count=failed_count,
            failed_keys=failed_keys,
            errors=errors,
        )

    # ========================================================================
    # Export / Import
    # ========================================================================

    async def export_settings(
        self, legal_entity_id: UUID | None = None, format: str = "json"
    ) -> str:
        """Export settings to JSON or CSV."""
        logger.info(f"Exporting settings in {format} format")

        settings = await self.list_settings(legal_entity_id)

        if format == "json":
            return json.dumps([s.to_dict() for s in settings], indent=2, default=str)
        else:
            # CSV format
            import csv
            import io

            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["key", "value", "data_type", "category", "scope", "description"])
            for s in settings:
                writer.writerow(
                    [s.key, s.value, s.data_type.value, s.category, s.scope.value, s.description]
                )
            return output.getvalue()

    async def import_settings(
        self,
        legal_entity_id: UUID | None = None,
        data: str | None = None,
        format: str = "json",
        mode: str = "merge",
        imported_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> ImportResult:
        """Import settings from data."""
        logger.info(f"Importing settings in {format} format with mode {mode}")

        errors = []
        imported_count = 0
        skipped_count = 0

        try:
            if format == "json":
                try:
                    settings_data = json.loads(data) if data else []
                except json.JSONDecodeError as e:
                    return ImportResult(success=False, errors=[f"Invalid JSON: {e}"])
                if isinstance(settings_data, dict):
                    settings_data = [{"key": k, "value": v} for k, v in settings_data.items()]
            else:
                # CSV format
                import csv
                import io

                try:
                    reader = csv.DictReader(io.StringIO(data or ""))
                    settings_data = list(reader)
                except csv.Error as e:
                    return ImportResult(success=False, errors=[f"Invalid CSV: {e}"])

            for item in settings_data:
                try:
                    existing = await self.get_setting(item["key"], legal_entity_id)
                    if existing and mode == "skip":
                        skipped_count += 1
                        continue

                    await self.update_setting(
                        key=item["key"],
                        legal_entity_id=legal_entity_id,
                        value=item.get("value"),
                        description=item.get("description"),
                        updated_by=imported_by,
                        correlation_id=correlation_id,
                    )
                    imported_count += 1
                except (SettingNotFoundError, SettingReadonlyError, SettingLockedError, SettingValidationError) as e:
                    errors.append(f"Failed to import {item.get('key')}: {e}")
                except KeyError as e:
                    errors.append(f"Missing required field: {e}")

        except Exception as e:
            # Catch any unexpected error at the top level to prevent crash
            return ImportResult(success=False, errors=[f"Unexpected error: {str(e)}"])

        return ImportResult(
            success=len(errors) == 0,
            imported_count=imported_count,
            skipped_count=skipped_count,
            errors=errors,
        )

    def get_stats(self) -> dict[str, int]:
        """Get service statistics."""
        return self._stats.copy()


# ============================================================================
# Factory
# ============================================================================


async def create_system_settings_service(
    event_publisher: EventPublisherPort | None = None,
) -> SystemSettingsService:
    return SystemSettingsService(event_publisher=event_publisher)


__all__ = [
    "BulkUpdateResult",
    "ImportResult",
    "Setting",
    "SettingDataType",
    "SettingNotFoundError",
    "SettingReadonlyError",
    "SettingScope",
    "SettingValidationError",
    "SettingLockedError",
    "SystemSettingsError",
    "SystemSettingsService",
    "create_system_settings_service",
]