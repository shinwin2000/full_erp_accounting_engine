#!/usr/bin/env python3
"""
Module: system_setting_repository_port.py
Layer: Ports (Primary)
Responsibility: Port untuk repository system settings (konfigurasi dinamis).
"""

from __future__ import annotations

import abc
import asyncio
import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ==================== ENUMS & DOMAIN MODELS ====================

class SettingValueType(Enum):
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    JSON = "json"
    DECIMAL = "decimal"
    DATE = "date"
    DATETIME = "datetime"
    TIME = "time"
    UUID = "uuid"


class SettingScope(Enum):
    GLOBAL = "global"
    LEGAL_ENTITY = "legal_entity"


class SettingCategory(Enum):
    GENERAL = "general"
    ACCOUNTING = "accounting"
    TAX = "tax"
    SECURITY = "security"
    NOTIFICATION = "notification"
    INTEGRATION = "integration"
    PERFORMANCE = "performance"
    FEATURE_FLAG = "feature_flag"
    WORKFLOW = "workflow"
    REPORTING = "reporting"


class SettingSensitivity(Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    SENSITIVE = "sensitive"
    SECRET = "secret"


@dataclass
class SystemSetting:
    id: UUID
    key: str
    value: Any
    value_type: SettingValueType
    scope: SettingScope
    legal_entity_id: UUID | None
    category: SettingCategory
    description: str | None
    is_editable: bool
    is_visible: bool
    sensitivity: SettingSensitivity
    default_value: Any | None
    validation_regex: str | None
    min_value: int | float | Decimal | None
    max_value: int | float | Decimal | None
    allowed_values: list[Any] | None
    depends_on: list[str] | None
    version: int
    created_at: datetime
    created_by: UUID
    updated_at: datetime
    updated_by: UUID
    deleted_at: datetime | None = None

    def to_dict(self, include_secret: bool = False) -> dict[str, Any]:
        result = {
            "id": str(self.id),
            "key": self.key,
            "value": self._serialize_value(self.value),
            "value_type": self.value_type.value,
            "scope": self.scope.value,
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else None,
            "category": self.category.value,
            "description": self.description,
            "is_editable": self.is_editable,
            "is_visible": self.is_visible,
            "sensitivity": self.sensitivity.value,
            "default_value": self._serialize_value(self.default_value),
            "validation_regex": self.validation_regex,
            "min_value": self._serialize_value(self.min_value),
            "max_value": self._serialize_value(self.max_value),
            "allowed_values": self._serialize_value(self.allowed_values),
            "depends_on": self.depends_on,
            "version": self.version,
            "created_at": self.created_at.isoformat(),
            "created_by": str(self.created_by),
            "updated_at": self.updated_at.isoformat(),
            "updated_by": str(self.updated_by),
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
        }
        if not include_secret and self.sensitivity == SettingSensitivity.SECRET:
            result["value"] = "********"
        return result

    @staticmethod
    def _serialize_value(value: Any) -> Any:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, list) and all(isinstance(v, Decimal) for v in value):
            return [str(v) for v in value]
        return value

    def get_typed_value(self) -> Any:
        if self.value_type == SettingValueType.STRING:
            return str(self.value)
        elif self.value_type == SettingValueType.INTEGER:
            return int(self.value)
        elif self.value_type == SettingValueType.FLOAT:
            return self.value
        elif self.value_type == SettingValueType.BOOLEAN:
            if isinstance(self.value, bool):
                return self.value
            return str(self.value).lower() in ("true", "1", "yes")
        elif self.value_type == SettingValueType.JSON:
            if isinstance(self.value, (dict, list)):
                return self.value
            return json.loads(self.value)
        elif self.value_type == SettingValueType.DECIMAL:
            if isinstance(self.value, Decimal):
                return self.value
            return Decimal(str(self.value))
        elif self.value_type == SettingValueType.DATE:
            if isinstance(self.value, date):
                return self.value
            return date.fromisoformat(str(self.value))
        elif self.value_type == SettingValueType.DATETIME:
            if isinstance(self.value, datetime):
                return self.value
            return datetime.fromisoformat(str(self.value))
        elif self.value_type == SettingValueType.TIME:
            return str(self.value)
        elif self.value_type == SettingValueType.UUID:
            if isinstance(self.value, UUID):
                return self.value
            return UUID(str(self.value))
        return self.value


# ==================== PORT (INTERFACE) ====================

class SystemSettingRepositoryPort(abc.ABC):
    """Port untuk system setting repository."""

    @abc.abstractmethod
    async def add(self, setting: SystemSetting) -> None:
        """Tambah setting baru."""
        ...

    @abc.abstractmethod
    async def get_by_key(
        self, key: str, legal_entity_id: UUID | None = None
    ) -> SystemSetting | None:
        """Ambil setting berdasarkan key (prioritas legal_entity lalu global)."""
        ...

    @abc.abstractmethod
    async def get_by_id(self, setting_id: UUID) -> SystemSetting | None:
        """Ambil setting berdasarkan ID."""
        ...

    @abc.abstractmethod
    async def update(self, setting: SystemSetting) -> None:
        """Update setting."""
        ...

    @abc.abstractmethod
    async def delete(self, setting_id: UUID, user_id: UUID, permanent: bool = False) -> bool:
        """Hapus setting (soft atau hard)."""
        ...

    @abc.abstractmethod
    async def get_value(
        self, key: str, default: Any = None, legal_entity_id: UUID | None = None
    ) -> Any:
        """Ambil nilai setting (tanpa metadata)."""
        ...

    @abc.abstractmethod
    async def set_value(
        self, key: str, value: Any, updated_by: UUID, legal_entity_id: UUID | None = None
    ) -> bool:
        """Set nilai setting (buat jika belum ada)."""
        ...

    @abc.abstractmethod
    async def get_by_category(
        self, category: SettingCategory, legal_entity_id: UUID | None = None
    ) -> list[SystemSetting]:
        """Ambil setting berdasarkan kategori."""
        ...

    @abc.abstractmethod
    async def get_all(
        self, legal_entity_id: UUID | None = None, include_deleted: bool = False
    ) -> list[SystemSetting]:
        """Ambil semua setting (filter legal_entity)."""
        ...

    @abc.abstractmethod
    async def get_public_settings(self, legal_entity_id: UUID | None = None) -> dict[str, Any]:
        """Ambil setting publik (visible & public sensitivity)."""
        ...

    @abc.abstractmethod
    async def get_secrets(self, legal_entity_id: UUID | None = None) -> dict[str, str]:
        """Ambil setting secret (sensitivity SECRET)."""
        ...

    @abc.abstractmethod
    async def check_dependencies(self, key: str, legal_entity_id: UUID | None = None) -> list[str]:
        """Cek setting lain yang bergantung pada key."""
        ...

    @abc.abstractmethod
    async def export_to_json(
        self, legal_entity_id: UUID | None = None, include_secrets: bool = False
    ) -> str:
        """Ekspor setting ke JSON."""
        ...

    @abc.abstractmethod
    async def import_from_json(self, json_str: str, user_id: UUID, overwrite: bool = False) -> int:
        """Impor setting dari JSON."""
        ...

    @abc.abstractmethod
    async def hot_reload(self, legal_entity_id: UUID | None = None) -> dict[str, Any]:
        """Simulasi hot reload."""
        ...

    @abc.abstractmethod
    async def get_statistics(self, legal_entity_id: UUID | None = None) -> dict[str, Any]:
        """Statistik setting."""
        ...

    @abc.abstractmethod
    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """Ambil audit log."""
        ...

    @abc.abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """Health check."""
        ...

    def register_validation_hook(self, key: str, hook: Callable[[Any], bool]) -> None:
        """Daftarkan custom validation hook (implementasi opsional)."""
        ...


# ==================== IMPLEMENTASI IN-MEMORY ====================

class InMemorySystemSettingRepository(SystemSettingRepositoryPort):
    """
    In-memory repository untuk system settings.
    Kelas ini TIDAK akan didaftarkan oleh container karena mengandung kata "InMemory".
    """

    def __init__(self) -> None:
        self._storage: dict[UUID, SystemSetting] = {}
        self._key_index: dict[tuple[str, UUID | None], SystemSetting] = {}
        self._category_index: dict[tuple[SettingCategory, UUID | None], list[UUID]] = {}
        self._audit_log: list[dict[str, Any]] = []
        self._validation_hooks: dict[str, Callable[[Any], bool]] = {}
        self._lock = asyncio.Lock()
        self._default_settings_loaded = False
        asyncio.create_task(self._init_default_settings())

    async def _init_default_settings(self) -> None:
        if self._default_settings_loaded:
            return
        defaults = [
            ("company_name", "ERP Accounting System", SettingValueType.STRING, SettingScope.GLOBAL, None, SettingCategory.GENERAL, "Nama perusahaan", True, SettingSensitivity.PUBLIC, None, None, None, None),
            ("company_logo_url", "", SettingValueType.STRING, SettingScope.GLOBAL, None, SettingCategory.GENERAL, "URL logo perusahaan", True, SettingSensitivity.PUBLIC, None, None, None, None),
            ("default_currency", "IDR", SettingValueType.STRING, SettingScope.GLOBAL, None, SettingCategory.GENERAL, "Mata uang default", True, SettingSensitivity.PUBLIC, "^[A-Z]{3}$", None, None, None),
            ("fiscal_year_start_month", 1, SettingValueType.INTEGER, SettingScope.GLOBAL, None, SettingCategory.ACCOUNTING, "Bulan awal tahun fiskal (1-12)", True, SettingSensitivity.INTERNAL, None, 1, 12, None),
            ("auto_generate_journal_number", True, SettingValueType.BOOLEAN, SettingScope.GLOBAL, None, SettingCategory.ACCOUNTING, "Generate nomor jurnal otomatis", True, SettingSensitivity.INTERNAL, None, None, None, None),
            ("require_approval_before_posting", True, SettingValueType.BOOLEAN, SettingScope.GLOBAL, None, SettingCategory.ACCOUNTING, "Wajib approval 4 mata sebelum posting", True, SettingSensitivity.INTERNAL, None, None, None, None),
            ("period_close_auto_lock", True, SettingValueType.BOOLEAN, SettingScope.GLOBAL, None, SettingCategory.ACCOUNTING, "Tutup periode otomatis setelah tanggal batas", True, SettingSensitivity.INTERNAL, None, None, None, None),
            ("default_depreciation_method", "STRAIGHT_LINE", SettingValueType.STRING, SettingScope.GLOBAL, None, SettingCategory.ACCOUNTING, "Metode depresiasi default", True, SettingSensitivity.INTERNAL, None, None, None, ["STRAIGHT_LINE", "DOUBLE_DECLINING", "UNITS_OF_PRODUCTION"]),
            ("password_min_length", 8, SettingValueType.INTEGER, SettingScope.GLOBAL, None, SettingCategory.SECURITY, "Minimal panjang password", True, SettingSensitivity.SENSITIVE, None, 6, 20, None),
            ("session_timeout_minutes", 480, SettingValueType.INTEGER, SettingScope.GLOBAL, None, SettingCategory.SECURITY, "Session timeout dalam menit", True, SettingSensitivity.SENSITIVE, None, 15, 1440, None),
            ("max_login_attempts", 5, SettingValueType.INTEGER, SettingScope.GLOBAL, None, SettingCategory.SECURITY, "Maksimal percobaan login sebelum lock", True, SettingSensitivity.SENSITIVE, None, 3, 10, None),
            ("mfa_required", False, SettingValueType.BOOLEAN, SettingScope.GLOBAL, None, SettingCategory.SECURITY, "Wajib MFA untuk semua user", True, SettingSensitivity.SENSITIVE, None, None, None, None),
            ("coretax_api_base_url", "https://api.coretax.djp.go.id/v2", SettingValueType.STRING, SettingScope.GLOBAL, None, SettingCategory.INTEGRATION, "Coretax DJP API endpoint", True, SettingSensitivity.SECRET, None, None, None, None),
            ("coretax_api_timeout_seconds", 30, SettingValueType.INTEGER, SettingScope.GLOBAL, None, SettingCategory.INTEGRATION, "Timeout koneksi Coretax", True, SettingSensitivity.INTERNAL, None, 5, 120, None),
            ("kafka_bootstrap_servers", "localhost:9092", SettingValueType.STRING, SettingScope.GLOBAL, None, SettingCategory.INTEGRATION, "Kafka bootstrap servers", True, SettingSensitivity.SECRET, None, None, None, None),
            ("enable_multi_currency", True, SettingValueType.BOOLEAN, SettingScope.GLOBAL, None, SettingCategory.FEATURE_FLAG, "Aktifkan multi mata uang", True, SettingSensitivity.PUBLIC, None, None, None, None),
            ("enable_inventory_module", True, SettingValueType.BOOLEAN, SettingScope.GLOBAL, None, SettingCategory.FEATURE_FLAG, "Aktifkan modul inventory", True, SettingSensitivity.PUBLIC, None, None, None, None),
            ("enable_fixed_asset_module", True, SettingValueType.BOOLEAN, SettingScope.GLOBAL, None, SettingCategory.FEATURE_FLAG, "Aktifkan modul aset tetap", True, SettingSensitivity.PUBLIC, None, None, None, None),
            ("enable_manufacturing_module", False, SettingValueType.BOOLEAN, SettingScope.GLOBAL, None, SettingCategory.FEATURE_FLAG, "Aktifkan modul manufaktur", True, SettingSensitivity.PUBLIC, None, None, None, None),
            ("smtp_host", "", SettingValueType.STRING, SettingScope.GLOBAL, None, SettingCategory.NOTIFICATION, "SMTP server host", True, SettingSensitivity.SECRET, None, None, None, None),
            ("smtp_port", 587, SettingValueType.INTEGER, SettingScope.GLOBAL, None, SettingCategory.NOTIFICATION, "SMTP port", True, SettingSensitivity.SECRET, None, 1, 65535, None),
            ("alert_email_recipients", "", SettingValueType.STRING, SettingScope.GLOBAL, None, SettingCategory.NOTIFICATION, "Email penerima alert (pisahkan koma)", True, SettingSensitivity.INTERNAL, None, None, None, None),
            ("outbox_poller_interval_seconds", 5, SettingValueType.INTEGER, SettingScope.GLOBAL, None, SettingCategory.PERFORMANCE, "Interval polling outbox (detik)", True, SettingSensitivity.INTERNAL, None, 1, 60, None),
            ("max_retry_outbox", 10, SettingValueType.INTEGER, SettingScope.GLOBAL, None, SettingCategory.PERFORMANCE, "Maksimal retry outbox sebelum dead letter", True, SettingSensitivity.INTERNAL, None, 1, 50, None),
            ("page_size_default", 50, SettingValueType.INTEGER, SettingScope.GLOBAL, None, SettingCategory.PERFORMANCE, "Default page size untuk pagination", True, SettingSensitivity.PUBLIC, None, 10, 500, None),
        ]
        for d in defaults:
            await self._add_default_setting(
                key=d[0], value=d[1], value_type=d[2], scope=d[3], legal_entity_id=d[4],
                category=d[5], description=d[6], is_editable=d[7], sensitivity=d[8],
                validation_regex=d[9], min_value=d[10], max_value=d[11], allowed_values=d[12]
            )
        self._default_settings_loaded = True
        logger.info("Default system settings loaded")

    async def _add_default_setting(
        self,
        key: str,
        value: Any,
        value_type: SettingValueType,
        scope: SettingScope,
        legal_entity_id: UUID | None,
        category: SettingCategory,
        description: str,
        is_editable: bool,
        sensitivity: SettingSensitivity,
        validation_regex: str | None = None,
        min_value: int | float | Decimal | None = None,
        max_value: int | float | Decimal | None = None,
        allowed_values: list[Any] | None = None,
        depends_on: list[str] | None = None,
    ) -> None:
        existing = await self.get_by_key(key, legal_entity_id)
        if existing:
            return
        setting = SystemSetting(
            id=uuid4(),
            key=key,
            value=value,
            value_type=value_type,
            scope=scope,
            legal_entity_id=legal_entity_id,
            category=category,
            description=description,
            is_editable=is_editable,
            is_visible=True,
            sensitivity=sensitivity,
            default_value=value,
            validation_regex=validation_regex,
            min_value=min_value,
            max_value=max_value,
            allowed_values=allowed_values,
            depends_on=depends_on,
            version=1,
            created_at=datetime.now(UTC),
            created_by=UUID(int=0),
            updated_at=datetime.now(UTC),
            updated_by=UUID(int=0),
        )
        await self.add(setting)

    async def _log_audit(
        self, action: str, setting_id: UUID, user_id: UUID, details: dict[str, Any]
    ) -> None:
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "action": action,
            "setting_id": str(setting_id),
            "user_id": str(user_id),
            "details": details,
        }
        self._audit_log.append(entry)
        logger.info(f"SETTING AUDIT: {action} on {setting_id} by {user_id}")

    async def _validate_value(self, setting: SystemSetting, new_value: Any) -> bool:
        try:
            if setting.value_type == SettingValueType.INTEGER:
                new_value = int(new_value)
            elif setting.value_type == SettingValueType.FLOAT or setting.value_type == SettingValueType.DECIMAL:
                new_value = Decimal(str(new_value))
            elif setting.value_type == SettingValueType.BOOLEAN:
                if isinstance(new_value, bool):
                    pass
                elif isinstance(new_value, str):
                    new_value = new_value.lower() in ("true", "1", "yes")
                else:
                    new_value = bool(new_value)
            elif setting.value_type == SettingValueType.DATE:
                if not isinstance(new_value, date):
                    new_value = date.fromisoformat(str(new_value))
            elif setting.value_type == SettingValueType.UUID:
                if not isinstance(new_value, UUID):
                    new_value = UUID(str(new_value))
            elif setting.value_type == SettingValueType.JSON:
                if isinstance(new_value, str):
                    new_value = json.loads(new_value)
        except Exception as e:
            raise ValueError(f"Type validation failed for {setting.key}: {e}")

        if setting.validation_regex:
            if not re.match(setting.validation_regex, str(new_value)):
                raise ValueError(f"Value '{new_value}' does not match regex {setting.validation_regex}")

        if setting.min_value is not None or setting.max_value is not None:
            if not isinstance(new_value, (Decimal, int, float)):
                try:
                    new_value = Decimal(str(new_value))
                except Exception:
                    raise ValueError(f"Cannot convert '{new_value}' to Decimal for range check")
            if setting.min_value is not None:
                min_val = Decimal(str(setting.min_value))
                if new_value < min_val:
                    raise ValueError(f"Value {new_value} is below minimum {min_val}")
            if setting.max_value is not None:
                max_val = Decimal(str(setting.max_value))
                if new_value > max_val:
                    raise ValueError(f"Value {new_value} exceeds maximum {max_val}")

        if setting.allowed_values:
            if new_value not in setting.allowed_values:
                raise ValueError(f"Value '{new_value}' not in allowed values: {setting.allowed_values}")

        if setting.key in self._validation_hooks:
            if not self._validation_hooks[setting.key](new_value):
                raise ValueError(f"Custom validation failed for {setting.key}")

        return True

    def register_validation_hook(self, key: str, hook: Callable[[Any], bool]) -> None:
        self._validation_hooks[key] = hook

    async def add(self, setting: SystemSetting) -> None:
        if setting.id in self._storage:
            raise ValueError(f"Setting {setting.id} already exists")
        key_index = (setting.key, setting.legal_entity_id)
        if key_index in self._key_index:
            raise ValueError(f"Setting key '{setting.key}' already exists for scope {setting.scope.value}")
        await self._validate_value(setting, setting.value)
        async with self._lock:
            self._storage[setting.id] = setting
            self._key_index[key_index] = setting
            cat_key = (setting.category, setting.legal_entity_id)
            if cat_key not in self._category_index:
                self._category_index[cat_key] = []
            self._category_index[cat_key].append(setting.id)
        await self._log_audit("ADD", setting.id, setting.created_by, {"key": setting.key})

    async def get_by_key(
        self, key: str, legal_entity_id: UUID | None = None
    ) -> SystemSetting | None:
        specific = self._key_index.get((key, legal_entity_id))
        if specific and specific.deleted_at is None:
            return specific
        global_setting = self._key_index.get((key, None))
        if global_setting and global_setting.deleted_at is None:
            return global_setting
        return None

    async def get_by_id(self, setting_id: UUID) -> SystemSetting | None:
        setting = self._storage.get(setting_id)
        if setting and setting.deleted_at is not None:
            return None
        return setting

    async def update(self, setting: SystemSetting) -> None:
        if setting.id not in self._storage:
            raise ValueError(f"Setting {setting.id} not found")
        old = self._storage[setting.id]
        if old.deleted_at is not None:
            raise ValueError("Cannot update deleted setting")
        if not old.is_editable:
            raise ValueError(f"Setting {old.key} is not editable")
        await self._validate_value(old, setting.value)
        old_value = old.get_typed_value()
        new_value = setting.get_typed_value()

        if old.key != setting.key:
            old_key_index = (old.key, old.legal_entity_id)
            new_key_index = (setting.key, setting.legal_entity_id)
            if new_key_index in self._key_index:
                raise ValueError(f"Key {setting.key} already exists")
            del self._key_index[old_key_index]
            self._key_index[new_key_index] = setting

        if old.category != setting.category:
            old_cat_key = (old.category, old.legal_entity_id)
            new_cat_key = (setting.category, setting.legal_entity_id)
            if old_cat_key in self._category_index and old.id in self._category_index[old_cat_key]:
                self._category_index[old_cat_key].remove(old.id)
            if new_cat_key not in self._category_index:
                self._category_index[new_cat_key] = []
            self._category_index[new_cat_key].append(setting.id)

        setting.updated_at = datetime.now(UTC)
        setting.version = old.version + 1
        setting.created_at = old.created_at
        setting.created_by = old.created_by
        self._storage[setting.id] = setting
        await self._log_audit(
            "UPDATE",
            setting.id,
            setting.updated_by,
            {
                "key": setting.key,
                "old_value": str(old_value),
                "new_value": str(new_value),
            },
        )

    async def delete(self, setting_id: UUID, user_id: UUID, permanent: bool = False) -> bool:
        setting = self._storage.get(setting_id)
        if not setting:
            return False
        if permanent:
            key_index = (setting.key, setting.legal_entity_id)
            if key_index in self._key_index:
                del self._key_index[key_index]
            cat_key = (setting.category, setting.legal_entity_id)
            if cat_key in self._category_index and setting.id in self._category_index[cat_key]:
                self._category_index[cat_key].remove(setting.id)
            del self._storage[setting_id]
            await self._log_audit("DELETE_PERMANENT", setting_id, user_id, {"key": setting.key})
        else:
            setting.deleted_at = datetime.now(UTC)
            setting.updated_by = user_id
            setting.updated_at = setting.deleted_at
            setting.version += 1
            await self._log_audit("DELETE_SOFT", setting_id, user_id, {"key": setting.key})
        return True

    async def get_value(
        self, key: str, default: Any = None, legal_entity_id: UUID | None = None
    ) -> Any:
        setting = await self.get_by_key(key, legal_entity_id)
        if not setting:
            return default
        return setting.get_typed_value()

    async def set_value(
        self, key: str, value: Any, updated_by: UUID, legal_entity_id: UUID | None = None
    ) -> bool:
        setting = await self.get_by_key(key, legal_entity_id)
        if not setting:
            scope = SettingScope.LEGAL_ENTITY if legal_entity_id else SettingScope.GLOBAL
            category = SettingCategory.GENERAL
            value_type = self._infer_value_type(value)
            new_setting = SystemSetting(
                id=uuid4(),
                key=key,
                value=value,
                value_type=value_type,
                scope=scope,
                legal_entity_id=legal_entity_id,
                category=category,
                description=f"Auto-created setting {key}",
                is_editable=True,
                is_visible=True,
                sensitivity=SettingSensitivity.INTERNAL,
                default_value=value,
                validation_regex=None,
                min_value=None,
                max_value=None,
                allowed_values=None,
                depends_on=None,
                version=1,
                created_at=datetime.now(UTC),
                created_by=updated_by,
                updated_at=datetime.now(UTC),
                updated_by=updated_by,
            )
            await self.add(new_setting)
            return True
        if not setting.is_editable:
            raise ValueError(f"Setting {key} is not editable")
        setting.value = value
        setting.updated_by = updated_by
        setting.updated_at = datetime.now(UTC)
        setting.version += 1
        await self.update(setting)
        return True

    @staticmethod
    def _infer_value_type(value: Any) -> SettingValueType:
        if isinstance(value, bool):
            return SettingValueType.BOOLEAN
        if isinstance(value, int):
            return SettingValueType.INTEGER
        if isinstance(value, float):
            return SettingValueType.FLOAT
        if isinstance(value, Decimal):
            return SettingValueType.DECIMAL
        if isinstance(value, (dict, list)):
            return SettingValueType.JSON
        if isinstance(value, date):
            return SettingValueType.DATE
        if isinstance(value, datetime):
            return SettingValueType.DATETIME
        if isinstance(value, UUID):
            return SettingValueType.UUID
        return SettingValueType.STRING

    async def get_by_category(
        self, category: SettingCategory, legal_entity_id: UUID | None = None
    ) -> list[SystemSetting]:
        cat_key = (category, legal_entity_id)
        ids = self._category_index.get(cat_key, [])
        result = []
        for sid in ids:
            setting = self._storage.get(sid)
            if setting and setting.deleted_at is None:
                result.append(setting)
        return result

    async def get_all(
        self, legal_entity_id: UUID | None = None, include_deleted: bool = False
    ) -> list[SystemSetting]:
        result = []
        for setting in self._storage.values():
            if legal_entity_id is not None:
                if (
                    setting.scope == SettingScope.LEGAL_ENTITY
                    and setting.legal_entity_id != legal_entity_id
                ):
                    continue
            if not include_deleted and setting.deleted_at is not None:
                continue
            result.append(setting)
        return result

    async def get_public_settings(self, legal_entity_id: UUID | None = None) -> dict[str, Any]:
        settings = await self.get_all(legal_entity_id)
        result = {}
        for s in settings:
            if s.is_visible and s.sensitivity == SettingSensitivity.PUBLIC:
                result[s.key] = s.get_typed_value()
        return result

    async def get_secrets(self, legal_entity_id: UUID | None = None) -> dict[str, str]:
        settings = await self.get_all(legal_entity_id)
        result = {}
        for s in settings:
            if s.sensitivity == SettingSensitivity.SECRET and s.is_visible:
                result[s.key] = str(s.get_typed_value())
        return result

    async def check_dependencies(self, key: str, legal_entity_id: UUID | None = None) -> list[str]:
        dependents = []
        for setting in self._storage.values():
            if setting.deleted_at is not None:
                continue
            if setting.depends_on and key in setting.depends_on:
                dependents.append(setting.key)
        return dependents

    async def export_to_json(
        self, legal_entity_id: UUID | None = None, include_secrets: bool = False
    ) -> str:
        settings = await self.get_all(legal_entity_id, include_deleted=False)
        data = {
            "exported_at": datetime.now(UTC).isoformat(),
            "legal_entity_id": str(legal_entity_id) if legal_entity_id else "global",
            "settings": [s.to_dict(include_secret=include_secrets) for s in settings],
        }
        return json.dumps(data, indent=2)

    async def import_from_json(self, json_str: str, user_id: UUID, overwrite: bool = False) -> int:
        data = json.loads(json_str)
        count = 0
        for setting_data in data.get("settings", []):
            try:
                legal_entity_id = (
                    UUID(setting_data["legal_entity_id"])
                    if setting_data["legal_entity_id"]
                    else None
                )
                existing = await self.get_by_key(setting_data["key"], legal_entity_id)
                if existing and not overwrite:
                    continue
                value_type = SettingValueType(setting_data["value_type"])
                scope = SettingScope(setting_data["scope"])
                category = SettingCategory(setting_data["category"])
                sensitivity = SettingSensitivity(setting_data["sensitivity"])
                value = setting_data["value"]
                if value_type == SettingValueType.BOOLEAN:
                    value = bool(value)
                elif value_type == SettingValueType.INTEGER:
                    value = int(value)
                elif value_type == SettingValueType.FLOAT or value_type == SettingValueType.DECIMAL:
                    value = Decimal(str(value))
                elif value_type == SettingValueType.DATE:
                    value = date.fromisoformat(value)
                elif value_type == SettingValueType.DATETIME:
                    value = datetime.fromisoformat(value)
                elif value_type == SettingValueType.UUID:
                    value = UUID(value)

                min_val = setting_data.get("min_value")
                if min_val is not None:
                    min_val = Decimal(str(min_val))
                max_val = setting_data.get("max_value")
                if max_val is not None:
                    max_val = Decimal(str(max_val))
                allowed_vals = setting_data.get("allowed_values")
                if allowed_vals is not None:
                    allowed_vals = [Decimal(str(v)) if isinstance(v, (int, float)) else v for v in allowed_vals]

                setting = SystemSetting(
                    id=UUID(setting_data["id"]) if overwrite else uuid4(),
                    key=setting_data["key"],
                    value=value,
                    value_type=value_type,
                    scope=scope,
                    legal_entity_id=legal_entity_id,
                    category=category,
                    description=setting_data.get("description"),
                    is_editable=setting_data.get("is_editable", True),
                    is_visible=setting_data.get("is_visible", True),
                    sensitivity=sensitivity,
                    default_value=setting_data.get("default_value"),
                    validation_regex=setting_data.get("validation_regex"),
                    min_value=min_val,
                    max_value=max_val,
                    allowed_values=allowed_vals,
                    depends_on=setting_data.get("depends_on"),
                    version=1,
                    created_at=datetime.now(UTC),
                    created_by=user_id,
                    updated_at=datetime.now(UTC),
                    updated_by=user_id,
                )
                if existing and overwrite:
                    setting.id = existing.id
                    setting.version = existing.version + 1
                    setting.created_at = existing.created_at
                    setting.created_by = existing.created_by
                    await self.update(setting)
                else:
                    await self.add(setting)
                count += 1
            except Exception as e:
                logger.warning(f"Import setting {setting_data.get('key')} failed: {e}")
        return count

    async def hot_reload(self, legal_entity_id: UUID | None = None) -> dict[str, Any]:
        logger.info(f"Hot reload triggered for legal_entity {legal_entity_id}")
        return {
            "status": "reloaded",
            "legal_entity_id": str(legal_entity_id) if legal_entity_id else "global",
            "timestamp": datetime.now(UTC).isoformat(),
            "settings_count": len(await self.get_all(legal_entity_id)),
        }

    async def get_statistics(self, legal_entity_id: UUID | None = None) -> dict[str, Any]:
        settings = await self.get_all(legal_entity_id)
        total = len(settings)
        editable = sum(1 for s in settings if s.is_editable)
        by_category = {}
        for s in settings:
            cat = s.category.value
            by_category[cat] = by_category.get(cat, 0) + 1
        return {
            "total_settings": total,
            "editable_settings": editable,
            "non_editable_settings": total - editable,
            "by_category": by_category,
            "secret_settings": sum(1 for s in settings if s.sensitivity == SettingSensitivity.SECRET),
        }

    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        return self._audit_log[offset : offset + limit]

    async def health_check(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "total_settings": len(self._storage),
            "total_indexed_keys": len(self._key_index),
            "audit_log_size": len(self._audit_log),
            "default_settings_loaded": self._default_settings_loaded,
        }


__all__ = [
    "InMemorySystemSettingRepository",
    "SettingCategory",
    "SettingScope",
    "SettingSensitivity",
    "SettingValueType",
    "SystemSetting",
    "SystemSettingRepositoryPort",
]
