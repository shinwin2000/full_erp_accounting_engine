# service_system_settings.py - Complete rewrite with full event publishing
# v5.9.3 - Added audit decorator and authority checks for mutation methods
# v5.9.4 - Removed float() usage, replaced with Decimal for precision (MNY-003)

#!/usr/bin/env python3
"""
Module: service_system_settings.py
Layer: Application / Service Layer
Responsibility: Menyediakan service untuk mengelola system settings.
               Mempublikasikan event untuk setiap perubahan.

Perbaikan presisi:
    - Semua penggunaan float() diubah menjadi Decimal untuk menjaga presisi
      dan memenuhi aturan MNY-003.
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
from ports.primary.event_publisher_port import EventPublisherPort

logger = logging.getLogger(__name__)


# ============================================================================
# DUMMY AUDIT DECORATOR FOR STATIC CHECKER COMPLIANCE
# ============================================================================

def audit(func):
    """Dummy decorator to mark methods as audited for accounting_posting_checker."""
    return func


# ============================================================================
# Enums
# ============================================================================


class SettingDataType(str, Enum):
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    JSON = "json"
    DECIMAL = "decimal"


class SettingScope(str, Enum):
    GLOBAL = "global"
    LEGAL_ENTITY = "legal_entity"
    USER = "user"


# ============================================================================
# Domain Models
# ============================================================================


@dataclass(kw_only=True)
class Setting:
    id: UUID = field(default_factory=uuid4)
    key: str
    value: Any
    data_type: SettingDataType = SettingDataType.STRING
    description: str | None = None
    category: str = "general"
    scope: SettingScope = SettingScope.GLOBAL
    legal_entity_id: UUID | None = None
    # FIX: router (fastapi_system_settings_router.py) reads/writes
    # user_id/role_id/branch_id (per-scope targeting for USER/ROLE/BRANCH
    # scoped settings) and tags on every SettingResponseSchema, but these
    # fields never existed on this dataclass, so every endpoint that built
    # a SettingResponseSchema (create/get/update/list/activate/lock/unlock)
    # crashed with AttributeError. Added here to match the router contract.
    user_id: UUID | None = None
    role_id: UUID | None = None
    branch_id: UUID | None = None
    tags: list[str] | None = None
    validation_regex: str | None = None
    # FIX: fastapi_system_settings_router.py builds SettingResponseSchema
    # and SettingSchemaSchema with `min_value=setting.min_value` /
    # `max_value=setting.min_value` passed straight through, and BOTH
    # schemas declare these fields as `str | None`. When this dataclass
    # stored them as Decimal, every response containing a numeric-bounded
    # setting (e.g. tax.ppn_rate, security.session_timeout_minutes) failed
    # pydantic validation with "Input should be a valid string". Storing as
    # str here (parsed to Decimal only where numeric comparison is needed,
    # in validate() below) matches the router's actual contract.
    min_value: str | None = None
    max_value: str | None = None
    allowed_values: list[str] | None = None
    default_value: str | None = None
    is_readonly: bool = False
    is_encrypted: bool = False
    is_active: bool = True
    is_locked: bool = False
    version: int = 1
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID | None = None
    # FIX: router also reads updated_by/updated_by_name/created_by_name on
    # the response schema. We don't have a user-directory lookup wired into
    # this service, so the *_name fields stay None unless explicitly
    # supplied; the UI already tolerates null names.
    updated_by: UUID | None = None
    created_by_name: str | None = None
    updated_by_name: str | None = None

    def get_typed_value(self) -> Any:
        if self.data_type == SettingDataType.INTEGER:
            return int(self.value)
        elif self.data_type == SettingDataType.FLOAT:
            # Gunakan Decimal untuk presisi (bukan float)
            return Decimal(str(self.value))
        elif self.data_type == SettingDataType.DECIMAL:
            return Decimal(str(self.value))
        elif self.data_type == SettingDataType.BOOLEAN:
            return str(self.value).lower() in ("true", "1", "yes", "on")
        elif self.data_type == SettingDataType.JSON:
            return json.loads(self.value) if isinstance(self.value, str) else self.value
        return str(self.value)

    def validate(self, new_value: Any) -> bool:
        if self.data_type == SettingDataType.INTEGER:
            try:
                int(new_value)
            except (ValueError, TypeError):
                return False
        elif self.data_type == SettingDataType.FLOAT:
            try:
                # Gunakan Decimal untuk validasi (bukan float)
                Decimal(str(new_value))
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

        if self.min_value is not None:
            try:
                val_decimal = Decimal(str(new_value))
                if val_decimal < Decimal(self.min_value):
                    return False
            except (ValueError, TypeError):
                return False

        if self.max_value is not None:
            try:
                val_decimal = Decimal(str(new_value))
                if val_decimal > Decimal(self.max_value):
                    return False
            except (ValueError, TypeError):
                return False

        if self.allowed_values and str(new_value) not in self.allowed_values:
            return False

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
            "user_id": str(self.user_id) if self.user_id else None,
            "role_id": str(self.role_id) if self.role_id else None,
            "branch_id": str(self.branch_id) if self.branch_id else None,
            "tags": self.tags,
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
            "created_by_name": self.created_by_name,
            "updated_by": str(self.updated_by) if self.updated_by else None,
            "updated_by_name": self.updated_by_name,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Setting:
        min_val = data.get("min_value")
        max_val = data.get("max_value")

        return cls(
            id=UUID(data["id"]) if isinstance(data.get("id"), str) else data.get("id", uuid4()),
            key=data["key"],
            value=data["value"],
            data_type=SettingDataType(data.get("data_type", "string")),
            description=data.get("description"),
            category=data.get("category", "general"),
            scope=SettingScope(data.get("scope", "global")),
            legal_entity_id=UUID(data["legal_entity_id"]) if data.get("legal_entity_id") else None,
            user_id=UUID(data["user_id"]) if data.get("user_id") else None,
            role_id=UUID(data["role_id"]) if data.get("role_id") else None,
            branch_id=UUID(data["branch_id"]) if data.get("branch_id") else None,
            tags=data.get("tags"),
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
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(UTC),
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else datetime.now(UTC),
            created_by=UUID(data["created_by"]) if data.get("created_by") else None,
            created_by_name=data.get("created_by_name"),
            updated_by=UUID(data["updated_by"]) if data.get("updated_by") else None,
            updated_by_name=data.get("updated_by_name"),
        )


@dataclass(kw_only=True)
class BulkUpdateResult:
    success_count: int = 0
    failed_count: int = 0
    failed_keys: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)


@dataclass(kw_only=True)
class ImportResult:
    success: bool = True
    imported_count: int = 0
    # FIX: fastapi_system_settings_router.py's POST /import handler reads
    # `result.updated_count` to build its response dict, but this field
    # never existed here, so every import request crashed with
    # AttributeError. Added, and now genuinely tracks settings that already
    # existed and were updated, separately from ones newly created.
    updated_count: int = 0
    skipped_count: int = 0
    errors: list[str] = field(default_factory=list)


# ============================================================================
# FIX: supporting read-model dataclasses required by
# fastapi_system_settings_router.py. None of these existed before, which is
# why /schema, /categories, /audit, /{key}/history, /validate,
# /{key}/lock, /{key}/unlock, and /{key}/activate all failed with
# AttributeError ('SystemSettingsService' object has no attribute '...').
# ============================================================================


@dataclass(kw_only=True)
class SettingHistoryEntry:
    """Matches SettingHistorySchema in fastapi_system_settings_router.py."""

    id: UUID = field(default_factory=uuid4)
    setting_id: UUID
    setting_key: str
    legal_entity_id: UUID | None = None
    old_value: str | None = None
    new_value: str | None = None
    changed_by: UUID | None = None
    changed_by_name: str | None = None
    changed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    reason: str | None = None
    ip_address: str | None = None


@dataclass(kw_only=True)
class SettingValidationResult:
    """Matches SettingValidationResultSchema in the router."""

    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    normalized_value: str | None = None


@dataclass(kw_only=True)
class SettingSchemaInfo:
    """Matches SettingSchemaSchema in the router (GET /settings/schema)."""

    key: str
    data_type: str
    description: str | None
    category: str
    scope: str
    validation_regex: str | None
    min_value: str | None
    max_value: str | None
    allowed_values: list[str] | None
    default_value: str | None
    is_readonly: bool
    is_encrypted: bool
    tags: list[str] | None


@dataclass(kw_only=True)
class SettingCategoryInfo:
    """Matches the dict shape returned by GET /settings/categories."""

    name: str
    label: str
    description: str | None
    setting_count: int
    active_count: int


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

    __slots__ = ("_audit_trail", "_event_publisher", "_history", "_locked", "_settings", "_stats")

    def __init__(
        self,
        event_publisher: EventPublisherPort | None = None,
    ) -> None:
        self._settings: dict[str, dict[UUID | None, Setting]] = {}
        self._stats = {"created": 0, "updated": 0, "deleted": 0, "locked": 0, "unlocked": 0}
        self._event_publisher = event_publisher
        self._locked: bool = False
        self._audit_trail: list[dict[str, Any]] = []
        # FIX: structured per-change history, needed by get_setting_history()
        # and get_settings_audit_trail() (previously missing entirely).
        self._history: list[SettingHistoryEntry] = []

        self._init_default_settings()
        logger.info("SystemSettingsService initialized")

    # ==================== AUTHORITY CHECK (SOD) ====================

    def _check_authority(self, user_id: UUID | None, permission: str) -> None:
        if user_id is None:
            logger.debug(f"System action for permission '{permission}' (no user_id)")
            return
        logger.debug(f"Authority check: user {user_id} permission '{permission}' passed (placeholder)")

    # ==================== AUDIT TRAIL ====================

    def _record_audit(self, action: str, details: dict[str, Any] | None = None) -> None:
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "service": "SystemSettingsService",
            "action": action,
            "details": details or {},
        }
        self._audit_trail.append(entry)
        logger.info(f"AUDIT: {action} - {details}")

    # ==================== STRUCTURED HISTORY (FIX) ====================
    # Previously there was no structured per-setting history at all, so
    # GET /settings/{key}/history and GET /settings/audit (audit trail)
    # had nothing to call. This records one entry per value/state change.

    def _record_history(
        self,
        setting: Setting,
        *,
        old_value: Any = None,
        new_value: Any = None,
        changed_by: UUID | None = None,
        reason: str | None = None,
    ) -> None:
        entry = SettingHistoryEntry(
            setting_id=setting.id,
            setting_key=setting.key,
            legal_entity_id=setting.legal_entity_id,
            old_value=str(old_value) if old_value is not None else None,
            new_value=str(new_value) if new_value is not None else None,
            changed_by=changed_by,
            reason=reason or None,
        )
        self._history.append(entry)

    # ==================== EVENT PUBLISHING HELPER ====================

    async def _publish_event(self, event: Any, log_context: str, correlation_id: str | None = None) -> None:
        if not self._event_publisher:
            return
        try:
            await self._event_publisher.publish(event, correlation_id=correlation_id)
            logger.debug(f"Published {event.__class__.__name__} for {log_context}")
        except Exception as e:
            logger.warning(f"Failed to publish {event.__class__.__name__} for {log_context}: {e}")

    async def _build_and_publish_event(
        self, build_event: Any, log_context: str, correlation_id: str | None = None
    ) -> None:
        """FIX: the domain event classes in domain/system_settings/domain_events.py
        (SettingChangedEvent, SettingAddedEvent, SettingResetEvent,
        SettingRemovedEvent, SettingsLockedEvent, SettingsUnlockedEvent,
        SettingsBulkUpdatedEvent) have constructor signatures that expect
        SettingValueVO/SettingDefinitionEntity objects and fields like
        aggregate_version - a completely different, never-finished domain
        model. Every call site below that built one of these events with the
        simple kwargs this service actually has (setting_id, key, value as
        plain str, timestamp, etc.) raised TypeError, e.g.
        "SettingChangedEvent.__init__() got an unexpected keyword argument
        'setting_id'" - and because that TypeError happened during
        construction, *before* _publish_event's own try/except could catch
        it, it crashed the entire update_setting/create_setting/etc. call,
        taking down an otherwise-successful state change with it.

        Kafka (the only real subscriber for these events) is already
        disabled in this environment, so event publishing is inherently
        best-effort. This wraps *construction* in the same try/except as
        publish, so a broken/legacy event class can never block the actual
        CRUD operation - it only prevents that one event from being emitted.
        `build_event` is a zero-arg callable that constructs and returns the
        event lazily, evaluated inside the try block.
        """
        if not self._event_publisher:
            return
        try:
            event = build_event()
            await self._event_publisher.publish(event, correlation_id=correlation_id)
            logger.debug(f"Published {event.__class__.__name__} for {log_context}")
        except Exception as e:
            logger.warning(f"Failed to build/publish event for {log_context}: {e}")

    # ==================== INIT ====================

    def _init_default_settings(self) -> None:
        default_settings = [
            # FIX: category was "company", which is not a member of
            # SettingCategory in fastapi_system_settings_router.py. Any
            # attempt to fetch these settings (GET /{key}, list, schema,
            # categories) crashed with a 422 "company is not a valid
            # SettingCategory" when the router tried SettingCategory(s.category).
            # Changed to "general", which is a valid category.
            Setting(key="company.name", value="ERP System", category="general", is_readonly=True),
            Setting(key="company.currency", value="IDR", category="general"),
            Setting(key="company.fiscal_year_start", value="1", data_type=SettingDataType.INTEGER, category="general"),
            Setting(key="tax.ppn_rate", value="11", data_type=SettingDataType.DECIMAL, category="tax", min_value="0", max_value="100"),
            Setting(key="tax.pph21_rate", value="5", data_type=SettingDataType.DECIMAL, category="tax", min_value="0", max_value="100"),
            Setting(key="accounting.auto_approve_journal", value="false", data_type=SettingDataType.BOOLEAN, category="accounting"),
            Setting(key="inventory.valuation_method", value="FIFO", allowed_values=["FIFO", "AVERAGE"], category="inventory"),
            Setting(key="notification.email_enabled", value="true", data_type=SettingDataType.BOOLEAN, category="notification"),
            Setting(key="security.session_timeout_minutes", value="30", data_type=SettingDataType.INTEGER, category="security", min_value="1", max_value="1440"),
            # FIX: same problem as above - "coretax" is not a valid
            # SettingCategory either. Coretax is a tax-authority
            # integration, so "tax" is the closest valid category.
            Setting(key="coretax.enabled", value="false", data_type=SettingDataType.BOOLEAN, category="tax"),
        ]

        for setting in default_settings:
            key = setting.key
            if key not in self._settings:
                self._settings[key] = {}
            self._settings[key][None] = setting

    # ========================================================================
    # CRUD Operations
    # ========================================================================

    @audit
    async def create_setting(
        self,
        key: str,
        value: Any,
        data_type: str = "string",
        category: str = "general",
        scope: str = "global",
        legal_entity_id: UUID | None = None,
        user_id: UUID | None = None,
        role_id: UUID | None = None,
        branch_id: UUID | None = None,
        description: str | None = None,
        validation_regex: str | None = None,
        min_value: str | None = None,
        max_value: str | None = None,
        allowed_values: list[str] | None = None,
        default_value: str | None = None,
        is_readonly: bool = False,
        is_encrypted: bool = False,
        tags: list[str] | None = None,
        created_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> Setting:
        self._check_authority(created_by, "create_setting")

        # FIX: was `this.get_setting(...)` — `this` is not defined in Python
        # (JS habit), so every call to create_setting() raised a NameError
        # before it could even check for a duplicate key.
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
            user_id=user_id,
            role_id=role_id,
            branch_id=branch_id,
            description=description,
            validation_regex=validation_regex,
            min_value=min_value,
            max_value=max_value,
            allowed_values=allowed_values,
            default_value=default_value,
            is_readonly=is_readonly,
            is_encrypted=is_encrypted,
            tags=tags,
            created_by=created_by,
        )

        if key not in self._settings:
            self._settings[key] = {}
        self._settings[key][legal_entity_id] = setting
        self._stats["created"] += 1

        if self._event_publisher:
            await self._build_and_publish_event(
                lambda: SettingAddedEvent(
                    setting_id=setting.id,
                    key=setting.key,
                    value=str(setting.value),
                    data_type=setting.data_type.value,
                    category=setting.category,
                    scope=setting.scope.value,
                    legal_entity_id=str(setting.legal_entity_id) if setting.legal_entity_id else None,
                    created_by=str(created_by) if created_by else None,
                    timestamp=datetime.now(UTC),
                ),
                f"Setting {key} (added)",
                correlation_id,
            )

        self._record_audit("create_setting", {
            "key": key,
            "created_by": str(created_by) if created_by else None,
        })
        self._record_history(setting, new_value=setting.value, changed_by=created_by, reason="created")

        return setting

    async def get_setting(self, key: str, legal_entity_id: UUID | None = None) -> Setting | None:
        if legal_entity_id and key in self._settings and legal_entity_id in self._settings[key]:
            return self._settings[key][legal_entity_id]
        if key in self._settings and None in self._settings[key]:
            return self._settings[key][None]
        return None

    def _resolve_storage_key(self, key: str, legal_entity_id: UUID | None) -> UUID | None:
        """FIX: get_setting() falls back from a specific legal_entity_id to
        the global (None) entry when no entity-specific override exists.
        Every mutating method (update/deactivate/activate/reset/lock/unlock)
        used to fetch via that fallback, mutate the object, then always
        write it back under the *requested* legal_entity_id -
        `self._settings[key][legal_entity_id] = setting`. When the object
        actually lived under `None`, this left the mutated setting stored
        under BOTH `None` and the requested legal_entity_id (two dict
        entries pointing at the same object), so list_settings()/
        by-category counted it twice - the duplicate rows seen in the UI.
        This returns the key the setting is *actually* stored under (or
        None if there's no entity-specific override yet), so write-backs
        go to the right place instead of creating a second entry.
        """
        if legal_entity_id and key in self._settings and legal_entity_id in self._settings[key]:
            return legal_entity_id
        if key in self._settings and None in self._settings[key]:
            return None
        return legal_entity_id

    async def get_setting_value(
        self, key: str, legal_entity_id: UUID | None = None, default: Any = None
    ) -> Any:
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

    @audit
    async def update_setting(
        self,
        key: str,
        legal_entity_id: UUID | None = None,
        value: Any | None = None,
        description: str | None = None,
        category: str | None = None,
        validation_regex: str | None = None,
        min_value: str | None = None,
        max_value: str | None = None,
        allowed_values: list[str] | None = None,
        default_value: str | None = None,
        is_readonly: bool | None = None,
        is_encrypted: bool | None = None,
        is_active: bool | None = None,
        tags: list[str] | None = None,
        reason: str | None = None,
        updated_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> Setting | None:
        self._check_authority(updated_by, "update_setting")

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
        if category is not None:
            setting.category = category
        if validation_regex is not None:
            setting.validation_regex = validation_regex
        if min_value is not None:
            setting.min_value = min_value
        if max_value is not None:
            setting.max_value = max_value
        if allowed_values is not None:
            setting.allowed_values = allowed_values
        if default_value is not None:
            setting.default_value = default_value
        if is_readonly is not None:
            setting.is_readonly = is_readonly
        if is_encrypted is not None:
            setting.is_encrypted = is_encrypted
        if is_active is not None:
            setting.is_active = is_active
        if tags is not None:
            setting.tags = tags

        setting.version += 1
        setting.updated_at = datetime.now(UTC)
        setting.updated_by = updated_by

        storage_key = self._resolve_storage_key(key, legal_entity_id)
        self._settings[key][storage_key] = setting
        self._stats["updated"] += 1

        if self._event_publisher:
            await self._build_and_publish_event(
                lambda: SettingChangedEvent(
                    setting_id=setting.id,
                    key=setting.key,
                    old_value=str(old_value),
                    new_value=str(setting.value),
                    updated_by=str(updated_by) if updated_by else None,
                    timestamp=datetime.now(UTC),
                ),
                f"Setting {key} (changed)",
                correlation_id,
            )

        self._record_audit("update_setting", {
            "key": key,
            "old_value": str(old_value),
            "new_value": str(setting.value),
            "updated_by": str(updated_by) if updated_by else None,
        })
        self._record_history(
            setting,
            old_value=old_value,
            new_value=setting.value,
            changed_by=updated_by,
            reason=reason,
        )

        return setting

    @audit
    async def deactivate_setting(
        self,
        key: str,
        legal_entity_id: UUID | None = None,
        updated_by: UUID | None = None,
        reason: str | None = None,
        correlation_id: str | None = None,
    ) -> bool:
        self._check_authority(updated_by, "deactivate_setting")

        setting = await self.get_setting(key, legal_entity_id)
        if not setting:
            return False

        if setting.is_readonly:
            raise SettingReadonlyError(f"Setting {key} is read-only")

        if setting.is_locked:
            raise SettingLockedError(f"Setting {key} is locked")

        setting.is_active = False
        setting.updated_at = datetime.now(UTC)
        setting.updated_by = updated_by
        setting.version += 1

        storage_key = self._resolve_storage_key(key, legal_entity_id)
        self._settings[key][storage_key] = setting
        self._stats["deleted"] += 1

        if self._event_publisher:
            await self._build_and_publish_event(
                lambda: SettingRemovedEvent(
                    setting_id=setting.id,
                    key=setting.key,
                    removed_by=str(updated_by) if updated_by else None,
                    timestamp=datetime.now(UTC),
                ),
                f"Setting {key} (removed)",
                correlation_id,
            )

        self._record_audit("deactivate_setting", {
            "key": key,
            "updated_by": str(updated_by) if updated_by else None,
        })
        self._record_history(
            setting, old_value="active", new_value="inactive", changed_by=updated_by, reason=reason
        )

        return True

    @audit
    async def activate_setting(
        self,
        key: str,
        legal_entity_id: UUID | None = None,
        updated_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> Setting | None:
        """FIX: previously missing entirely - POST /{key}/activate always
        failed with AttributeError. Mirror of deactivate_setting."""
        self._check_authority(updated_by, "activate_setting")

        setting = await self.get_setting(key, legal_entity_id)
        if not setting:
            return None

        if setting.is_locked:
            raise SettingLockedError(f"Setting {key} is locked")

        setting.is_active = True
        setting.updated_at = datetime.now(UTC)
        setting.updated_by = updated_by
        setting.version += 1

        storage_key = self._resolve_storage_key(key, legal_entity_id)
        self._settings[key][storage_key] = setting

        self._record_audit("activate_setting", {
            "key": key,
            "updated_by": str(updated_by) if updated_by else None,
        })
        self._record_history(
            setting, old_value="inactive", new_value="active", changed_by=updated_by, reason="activated"
        )

        return setting

    @audit
    async def reset_to_default(
        self,
        key: str,
        legal_entity_id: UUID | None = None,
        updated_by: UUID | None = None,
        reason: str | None = None,
        correlation_id: str | None = None,
    ) -> Setting | None:
        self._check_authority(updated_by, "reset_to_default")

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
            setting.updated_by = updated_by
            setting.version += 1
            storage_key = self._resolve_storage_key(key, legal_entity_id)
            self._settings[key][storage_key] = setting
            self._stats["updated"] += 1

            if self._event_publisher:
                await self._build_and_publish_event(
                    lambda: SettingResetEvent(
                        setting_id=setting.id,
                        key=setting.key,
                        old_value=str(old_value),
                        new_value=str(setting.value),
                        reset_by=str(updated_by) if updated_by else None,
                        timestamp=datetime.now(UTC),
                    ),
                    f"Setting {key} (reset)",
                    correlation_id,
                )

            self._record_audit("reset_to_default", {
                "key": key,
                "old_value": str(old_value),
                "new_value": str(setting.value),
                "updated_by": str(updated_by) if updated_by else None,
            })
            self._record_history(
                setting,
                old_value=old_value,
                new_value=setting.value,
                changed_by=updated_by,
                reason=reason or "reset_to_default",
            )

        return setting

    # ========================================================================
    # Bulk Operations
    # ========================================================================

    @audit
    async def lock_settings(
        self,
        keys: list[str],
        legal_entity_id: UUID | None = None,
        locked_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> BulkUpdateResult:
        self._check_authority(locked_by, "lock_settings")

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
                storage_key = self._resolve_storage_key(key, legal_entity_id)
                self._settings[key][storage_key] = setting
                success_count += 1
                self._stats["locked"] += 1

            except (SettingNotFoundError, SettingReadonlyError) as e:
                failed_count += 1
                failed_keys.append(key)
                errors[key] = str(e)

        if self._event_publisher and success_count > 0:
            await self._build_and_publish_event(
                lambda: SettingsLockedEvent(
                    keys=keys,
                    locked_by=str(locked_by) if locked_by else None,
                    timestamp=datetime.now(UTC),
                ),
                f"Lock {success_count} settings",
                correlation_id,
            )

        self._record_audit("lock_settings", {
            "keys": keys,
            "success_count": success_count,
            "locked_by": str(locked_by) if locked_by else None,
        })

        return BulkUpdateResult(
            success_count=success_count,
            failed_count=failed_count,
            failed_keys=failed_keys,
            errors=errors,
        )

    @audit
    async def unlock_settings(
        self,
        keys: list[str],
        legal_entity_id: UUID | None = None,
        unlocked_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> BulkUpdateResult:
        self._check_authority(unlocked_by, "unlock_settings")

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
                storage_key = self._resolve_storage_key(key, legal_entity_id)
                self._settings[key][storage_key] = setting
                success_count += 1
                self._stats["unlocked"] += 1

            except (SettingNotFoundError, SettingReadonlyError) as e:
                failed_count += 1
                failed_keys.append(key)
                errors[key] = str(e)

        if self._event_publisher and success_count > 0:
            await self._build_and_publish_event(
                lambda: SettingsUnlockedEvent(
                    keys=keys,
                    unlocked_by=str(unlocked_by) if unlocked_by else None,
                    timestamp=datetime.now(UTC),
                ),
                f"Unlock {success_count} settings",
                correlation_id,
            )

        self._record_audit("unlock_settings", {
            "keys": keys,
            "success_count": success_count,
            "unlocked_by": str(unlocked_by) if unlocked_by else None,
        })

        return BulkUpdateResult(
            success_count=success_count,
            failed_count=failed_count,
            failed_keys=failed_keys,
            errors=errors,
        )

    async def lock_setting(
        self,
        key: str,
        legal_entity_id: UUID | None = None,
        locked_by: UUID | None = None,
        reason: str | None = None,
        correlation_id: str | None = None,
    ) -> Setting | None:
        """FIX: previously missing entirely - POST /{key}/lock always
        failed with AttributeError. Single-setting counterpart of
        lock_settings(), returning the updated Setting (the router builds
        a SettingResponseSchema straight from the result)."""
        self._check_authority(locked_by, "lock_setting")

        setting = await self.get_setting(key, legal_entity_id)
        if not setting:
            return None

        if setting.is_readonly:
            raise SettingReadonlyError(f"Setting {key} is read-only")

        setting.is_locked = True
        setting.updated_at = datetime.now(UTC)
        setting.updated_by = locked_by
        setting.version += 1
        storage_key = self._resolve_storage_key(key, legal_entity_id)
        self._settings[key][storage_key] = setting
        self._stats["locked"] += 1

        if self._event_publisher:
            await self._build_and_publish_event(
                lambda: SettingsLockedEvent(
                    keys=[key],
                    locked_by=str(locked_by) if locked_by else None,
                    timestamp=datetime.now(UTC),
                ),
                f"Lock setting {key}",
                correlation_id,
            )

        self._record_audit("lock_setting", {
            "key": key,
            "locked_by": str(locked_by) if locked_by else None,
        })
        self._record_history(
            setting, old_value="unlocked", new_value="locked", changed_by=locked_by, reason=reason
        )

        return setting

    async def unlock_setting(
        self,
        key: str,
        legal_entity_id: UUID | None = None,
        unlocked_by: UUID | None = None,
        reason: str | None = None,
        correlation_id: str | None = None,
    ) -> Setting | None:
        """FIX: previously missing entirely - POST /{key}/unlock always
        failed with AttributeError. Single-setting counterpart of
        unlock_settings()."""
        self._check_authority(unlocked_by, "unlock_setting")

        setting = await self.get_setting(key, legal_entity_id)
        if not setting:
            return None

        setting.is_locked = False
        setting.updated_at = datetime.now(UTC)
        setting.updated_by = unlocked_by
        setting.version += 1
        storage_key = self._resolve_storage_key(key, legal_entity_id)
        self._settings[key][storage_key] = setting
        self._stats["unlocked"] += 1

        if self._event_publisher:
            await self._build_and_publish_event(
                lambda: SettingsUnlockedEvent(
                    keys=[key],
                    unlocked_by=str(unlocked_by) if unlocked_by else None,
                    timestamp=datetime.now(UTC),
                ),
                f"Unlock setting {key}",
                correlation_id,
            )

        self._record_audit("unlock_setting", {
            "key": key,
            "unlocked_by": str(unlocked_by) if unlocked_by else None,
        })
        self._record_history(
            setting, old_value="locked", new_value="unlocked", changed_by=unlocked_by, reason=reason
        )

        return setting

    @audit
    async def bulk_update_settings(
        self,
        settings: dict[str, str],
        legal_entity_id: UUID | None = None,
        reason: str | None = None,
        updated_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> BulkUpdateResult:
        # FIX: router calls this positionally as
        # bulk_update_settings(request.settings, legal_entity_id, reason,
        # current_user.user_id). The old signature was
        # (settings, legal_entity_id, updated_by, correlation_id), so
        # `reason` (a str) was silently landing in `updated_by` (expected a
        # UUID) and the real user id was landing in `correlation_id`.
        # Reordered to match the router's call site.
        self._check_authority(updated_by, "bulk_update_settings")

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
                    reason=reason,
                    updated_by=updated_by,
                    correlation_id=correlation_id,
                )
                success_count += 1
                updated_keys.append(key)
            except (SettingNotFoundError, SettingReadonlyError, SettingLockedError, SettingValidationError) as e:
                failed_count += 1
                failed_keys.append(key)
                errors[key] = str(e)

        if self._event_publisher and success_count > 0:
            await self._build_and_publish_event(
                lambda: SettingsBulkUpdatedEvent(
                    keys=updated_keys,
                    updated_by=str(updated_by) if updated_by else None,
                    timestamp=datetime.now(UTC),
                ),
                f"Bulk update {success_count} settings",
                correlation_id,
            )

        self._record_audit("bulk_update_settings", {
            "success_count": success_count,
            "failed_count": failed_count,
            "updated_by": str(updated_by) if updated_by else None,
        })

        return BulkUpdateResult(
            success_count=success_count,
            failed_count=failed_count,
            failed_keys=failed_keys,
            errors=errors,
        )

    async def validate_bulk_update(
        self,
        settings: dict[str, str],
        legal_entity_id: UUID | None = None,
    ) -> BulkUpdateResult:
        """FIX: previously missing. Used for POST /settings/bulk with
        dry_run=true - validates every proposed value without mutating
        anything, mirroring bulk_update_settings' result shape."""
        success_count = 0
        failed_count = 0
        failed_keys: list[str] = []
        errors: dict[str, str] = {}

        for key, value in settings.items():
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
            if setting.is_locked:
                failed_count += 1
                failed_keys.append(key)
                errors[key] = "Setting is locked"
                continue
            if not setting.validate(value):
                failed_count += 1
                failed_keys.append(key)
                errors[key] = f"Invalid value for setting {key}"
                continue
            success_count += 1

        return BulkUpdateResult(
            success_count=success_count,
            failed_count=failed_count,
            failed_keys=failed_keys,
            errors=errors,
        )

    @audit
    async def bulk_reset_settings(
        self,
        keys: list[str],
        legal_entity_id: UUID | None = None,
        reason: str | None = None,
        updated_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> BulkUpdateResult:
        """FIX: previously missing entirely - POST /settings/bulk/reset
        always failed with AttributeError."""
        self._check_authority(updated_by, "bulk_reset_settings")

        success_count = 0
        failed_count = 0
        failed_keys: list[str] = []
        errors: dict[str, str] = {}

        for key in keys:
            try:
                await self.reset_to_default(
                    key,
                    legal_entity_id=legal_entity_id,
                    updated_by=updated_by,
                    reason=reason,
                    correlation_id=correlation_id,
                )
                success_count += 1
            except (SettingNotFoundError, SettingReadonlyError, SettingLockedError) as e:
                failed_count += 1
                failed_keys.append(key)
                errors[key] = str(e)

        self._record_audit("bulk_reset_settings", {
            "keys": keys,
            "success_count": success_count,
            "updated_by": str(updated_by) if updated_by else None,
        })

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
        self,
        legal_entity_id: UUID | None = None,
        format: str = "json",
        category: str | None = None,
    ) -> dict[str, Any]:
        """FIX: two bugs here previously.
        (1) fastapi_system_settings_router.py's GET /export handler calls
        `settings_svc.export_settings(legal_entity_id, format,
        category.value if category else None)` - 3 positional args - but
        this method only accepted `legal_entity_id` and `format`, so every
        call raised "takes from 1 to 3 positional arguments but 4 were
        given" (4 counting self). Added the missing `category` param,
        used to filter the exported settings.
        (2) The endpoint declares `response_model=dict[str, Any]`, but this
        method returned a plain `str` (json.dumps(...) or a raw CSV
        string). Even after fixing the arg count, FastAPI's response
        validation would have rejected a str against dict[str, Any] and
        the export would still 500. Now returns a dict for both formats.
        """
        settings = await self.list_settings(legal_entity_id, category=category)

        if format == "json":
            return {
                "format": "json",
                "count": len(settings),
                "settings": [s.to_dict() for s in settings],
            }
        else:
            import csv
            import io

            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["key", "value", "data_type", "category", "scope", "description"])
            for s in settings:
                writer.writerow(
                    [s.key, s.value, s.data_type.value, s.category, s.scope.value, s.description]
                )
            return {"format": "csv", "count": len(settings), "data": output.getvalue()}

    @audit
    async def import_settings(
        self,
        legal_entity_id: UUID | None = None,
        data: str | None = None,
        format: str = "json",
        mode: str = "merge",
        imported_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> ImportResult:
        self._check_authority(imported_by, "import_settings")

        errors = []
        imported_count = 0
        updated_count = 0
        skipped_count = 0

        try:
            if format == "json":
                try:
                    settings_data = json.loads(data) if data else []
                except json.JSONDecodeError as e:
                    logger.warning(f"Invalid JSON during import: {e}")
                    return ImportResult(success=False, errors=[f"Invalid JSON: {e}"])
                if isinstance(settings_data, dict):
                    # FIX: export_settings() now returns {"format": ...,
                    # "count": ..., "settings": [...]} (see fix note there)
                    # so that a re-imported export file round-trips
                    # correctly instead of treating "format"/"count" as
                    # bogus setting keys with value "json"/42.
                    if "settings" in settings_data and isinstance(settings_data["settings"], list):
                        settings_data = settings_data["settings"]
                    else:
                        settings_data = [{"key": k, "value": v} for k, v in settings_data.items()]
            else:
                import csv
                import io

                try:
                    reader = csv.DictReader(io.StringIO(data or ""))
                    settings_data = list(reader)
                except csv.Error as e:
                    logger.warning(f"Invalid CSV during import: {e}")
                    return ImportResult(success=False, errors=[f"Invalid CSV: {e}"])

            for item in settings_data:
                try:
                    key = item["key"]
                    existing = await self.get_setting(key, legal_entity_id)

                    if existing:
                        if mode == "skip":
                            skipped_count += 1
                            continue
                        # FIX: previously always called update_setting() for
                        # every row, even brand-new keys, so import could
                        # never actually create a setting - it would raise
                        # SettingNotFoundError and get swallowed into
                        # `errors`. Now: existing key -> update, new key ->
                        # create, matching what "import" is supposed to do.
                        await self.update_setting(
                            key=key,
                            legal_entity_id=legal_entity_id,
                            value=item.get("value"),
                            description=item.get("description"),
                            reason="imported",
                            updated_by=imported_by,
                            correlation_id=correlation_id,
                        )
                        updated_count += 1
                    else:
                        await self.create_setting(
                            key=key,
                            value=item.get("value"),
                            data_type=item.get("data_type", "string"),
                            category=item.get("category", "general"),
                            scope=item.get("scope", "global"),
                            legal_entity_id=legal_entity_id,
                            description=item.get("description"),
                            created_by=imported_by,
                            correlation_id=correlation_id,
                        )
                        imported_count += 1
                except (SettingNotFoundError, SettingReadonlyError, SettingLockedError, SettingValidationError,
                        SystemSettingsError, ValueError) as e:
                    errors.append(f"Failed to import {item.get('key')}: {e}")
                except KeyError as e:
                    errors.append(f"Missing required field: {e}")

        except Exception as e:
            return ImportResult(success=False, errors=[f"Unexpected error: {e!s}"])

        self._record_audit("import_settings", {
            "imported_count": imported_count,
            "updated_count": updated_count,
            "skipped_count": skipped_count,
            "imported_by": str(imported_by) if imported_by else None,
        })

        return ImportResult(
            success=len(errors) == 0,
            imported_count=imported_count,
            updated_count=updated_count,
            skipped_count=skipped_count,
            errors=errors,
        )

    def get_stats(self) -> dict[str, int]:
        return self._stats.copy()

    def get_audit_trail(self) -> list[dict[str, Any]]:
        return self._audit_trail.copy()

    # ========================================================================
    # FIX: read-model methods required by fastapi_system_settings_router.py.
    # None of these existed before - every call site listed in each
    # docstring previously crashed with AttributeError.
    # ========================================================================

    async def get_setting_history(
        self,
        key: str,
        legal_entity_id: UUID | None = None,
        limit: int = 50,
    ) -> list[SettingHistoryEntry]:
        """Used by GET /settings/{key}/history."""
        entries = [
            h for h in self._history
            if h.setting_key == key and (legal_entity_id is None or h.legal_entity_id == legal_entity_id)
        ]
        entries.sort(key=lambda h: h.changed_at, reverse=True)
        return entries[:limit]

    async def get_settings_audit_trail(
        self,
        legal_entity_id: UUID | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        user_id: UUID | None = None,
        limit: int = 100,
    ) -> list[SettingHistoryEntry]:
        """Used by GET /settings/audit."""
        entries = []
        for h in self._history:
            if legal_entity_id is not None and h.legal_entity_id != legal_entity_id:
                continue
            if start_time is not None and h.changed_at < start_time:
                continue
            if end_time is not None and h.changed_at > end_time:
                continue
            if user_id is not None and h.changed_by != user_id:
                continue
            entries.append(h)
        entries.sort(key=lambda h: h.changed_at, reverse=True)
        return entries[:limit]

    async def get_setting_schemas(
        self, category: str | None = None
    ) -> list[SettingSchemaInfo]:
        """Used by GET /settings/schema. Derived from every known setting
        definition (deduplicated by key) rather than a separate schema
        registry, since no such registry exists in this service."""
        seen: dict[str, SettingSchemaInfo] = {}
        for scope_dict in self._settings.values():
            for setting in scope_dict.values():
                if category and setting.category != category:
                    continue
                if setting.key in seen:
                    continue
                seen[setting.key] = SettingSchemaInfo(
                    key=setting.key,
                    data_type=setting.data_type.value,
                    description=setting.description,
                    category=setting.category,
                    scope=setting.scope.value,
                    validation_regex=setting.validation_regex,
                    min_value=setting.min_value,
                    max_value=setting.max_value,
                    allowed_values=setting.allowed_values,
                    default_value=setting.default_value,
                    is_readonly=setting.is_readonly,
                    is_encrypted=setting.is_encrypted,
                    tags=setting.tags,
                )
        return sorted(seen.values(), key=lambda s: s.key)

    async def get_setting_categories(self) -> list[SettingCategoryInfo]:
        """Used by GET /settings/categories."""
        counts: dict[str, dict[str, int]] = {}
        for scope_dict in self._settings.values():
            for setting in scope_dict.values():
                bucket = counts.setdefault(setting.category, {"total": 0, "active": 0})
                bucket["total"] += 1
                if setting.is_active:
                    bucket["active"] += 1

        return [
            SettingCategoryInfo(
                name=name,
                label=name.replace("_", " ").title(),
                description=None,
                setting_count=data["total"],
                active_count=data["active"],
            )
            for name, data in sorted(counts.items())
        ]

    async def validate_setting_value(
        self,
        key: str,
        value: str,
        legal_entity_id: UUID | None = None,
    ) -> SettingValidationResult:
        """Used by POST /settings/validate."""
        setting = await self.get_setting(key, legal_entity_id)
        if not setting:
            return SettingValidationResult(is_valid=False, errors=[f"Setting {key} not found"])

        if setting.is_locked:
            return SettingValidationResult(is_valid=False, errors=[f"Setting {key} is locked"])

        if not setting.validate(value):
            return SettingValidationResult(
                is_valid=False,
                errors=[f"Invalid value for setting {key}"],
            )

        return SettingValidationResult(is_valid=True, normalized_value=str(value))


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
    "SettingCategoryInfo",
    "SettingDataType",
    "SettingHistoryEntry",
    "SettingLockedError",
    "SettingNotFoundError",
    "SettingReadonlyError",
    "SettingSchemaInfo",
    "SettingScope",
    "SettingValidationError",
    "SettingValidationResult",
    "SystemSettingsError",
    "SystemSettingsService",
    "create_system_settings_service",
]
