#!/usr/bin/env python3
"""
Module: aggregate_root.py
Layer: 6 - Domain / System Settings
Responsibility: Root agregat pengaturan sistem per entitas.
               Mendefinisikan aggregate root untuk pengaturan sistem yang
               dapat dikonfigurasi per legal entity. Menyediakan mekanisme
               untuk menyimpan, mengambil, dan memvalidasi pengaturan.

Dependencies:
- standard library (uuid, datetime, logging)
- domain.system_settings.setting_definition_entity (SettingDefinitionEntity)
- domain.system_settings.setting_value_vo (SettingValueVO)

Audit: Setiap perubahan pengaturan dictat.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from domain.system_settings.setting_definition_entity import (
    SettingDataType,
    SettingDefinitionEntity,
)
from domain.system_settings.setting_value_vo import SettingValueVO

logger = logging.getLogger(__name__)


# === 1. ADDITIONAL ENUMS NEEDED BY REPOSITORY ===


class SettingCategory(Enum):
    """Kategori pengaturan sistem."""

    GENERAL = "general"
    ACCOUNTING = "accounting"
    TAX = "tax"
    SECURITY = "security"
    AUDIT = "audit"
    INTEGRATION = "integration"
    PERFORMANCE = "performance"
    NOTIFICATION = "notification"


class SettingScope(Enum):
    """Scope pengaturan sistem."""

    GLOBAL = "global"
    LEGAL_ENTITY = "legal_entity"


# === 2. CONSTANTS & ENUMS ===


class SystemSettingsStatus(Enum):
    """Status sistem pengaturan."""

    ACTIVE = "active"
    READONLY = "readonly"
    LOCKED = "locked"


# === 3. SYSTEM SETTINGS AGGREGATE ===


@dataclass
class SystemSettings:
    """
    Root aggregate untuk pengaturan sistem.

    Business context: Mengelola semua pengaturan sistem yang dapat
    dikonfigurasi, baik di level global maupun per legal entity.

    Invariants:
    1. Setting key harus unik per scope
    2. Nilai harus sesuai dengan tipe data yang didefinisikan
    3. Pengaturan yang terkunci (locked) tidak dapat diubah
    """

    settings_id: UUID
    legal_entity_id: UUID | None  # None untuk global settings
    status: SystemSettingsStatus
    definitions: dict[str, SettingDefinitionEntity] = field(default_factory=dict)
    values: dict[str, SettingValueVO] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    version: int = 1

    def __post_init__(self) -> None:
        """Inisialisasi default definitions jika kosong."""
        if not self.definitions:
            self._init_default_definitions()

    def _init_default_definitions(self) -> None:
        """Inisialisasi definisi pengaturan default."""
        now = datetime.now(UTC)

        default_definitions = [
            SettingDefinitionEntity(
                definition_id=uuid4(),
                key="company.name",
                data_type=SettingDataType.STRING,
                default_value="My Company",
                description="Company legal name",
                is_required=True,
                is_sensitive=False,
                is_locked=False,
                category="general",
                created_at=now,
                created_by="system",
            ),
            SettingDefinitionEntity(
                definition_id=uuid4(),
                key="company.tax_id",
                data_type=SettingDataType.STRING,
                default_value="",
                description="Company tax ID (NPWP)",
                is_required=True,
                is_sensitive=True,
                is_locked=False,
                category="tax",
                created_at=now,
                created_by="system",
            ),
            SettingDefinitionEntity(
                definition_id=uuid4(),
                key="company.fiscal_year_start",
                data_type=SettingDataType.INTEGER,
                default_value=1,
                description="Fiscal year start month (1-12)",
                is_required=True,
                is_sensitive=False,
                is_locked=True,
                category="accounting",
                created_at=now,
                created_by="system",
            ),
            SettingDefinitionEntity(
                definition_id=uuid4(),
                key="accounting.currency",
                data_type=SettingDataType.STRING,
                default_value="IDR",
                description="Functional currency",
                is_required=True,
                is_sensitive=False,
                is_locked=True,
                category="accounting",
                created_at=now,
                created_by="system",
            ),
            SettingDefinitionEntity(
                definition_id=uuid4(),
                key="tax.vat_rate",
                data_type=SettingDataType.DECIMAL,
                default_value=11.0,
                description="VAT rate percentage",
                is_required=True,
                is_sensitive=False,
                is_locked=False,
                category="tax",
                created_at=now,
                created_by="system",
            ),
            SettingDefinitionEntity(
                definition_id=uuid4(),
                key="tax.corporate_tax_rate",
                data_type=SettingDataType.DECIMAL,
                default_value=22.0,
                description="Corporate income tax rate percentage",
                is_required=True,
                is_sensitive=False,
                is_locked=False,
                category="tax",
                created_at=now,
                created_by="system",
            ),
            SettingDefinitionEntity(
                definition_id=uuid4(),
                key="notification.email_enabled",
                data_type=SettingDataType.BOOLEAN,
                default_value=True,
                description="Enable email notifications",
                is_required=False,
                is_sensitive=False,
                is_locked=False,
                category="notification",
                created_at=now,
                created_by="system",
            ),
            SettingDefinitionEntity(
                definition_id=uuid4(),
                key="security.session_timeout_minutes",
                data_type=SettingDataType.INTEGER,
                default_value=30,
                description="Session timeout in minutes",
                is_required=True,
                is_sensitive=False,
                is_locked=False,
                category="security",
                created_at=now,
                created_by="system",
            ),
            SettingDefinitionEntity(
                definition_id=uuid4(),
                key="security.mfa_required",
                data_type=SettingDataType.BOOLEAN,
                default_value=False,
                description="Require MFA for all users",
                is_required=True,
                is_sensitive=False,
                is_locked=False,
                category="security",
                created_at=now,
                created_by="system",
            ),
            SettingDefinitionEntity(
                definition_id=uuid4(),
                key="audit.retention_days",
                data_type=SettingDataType.INTEGER,
                default_value=365,
                description="Audit log retention in days",
                is_required=True,
                is_sensitive=False,
                is_locked=True,
                category="audit",
                created_at=now,
                created_by="system",
            ),
        ]

        for definition in default_definitions:
            self.definitions[definition.key] = definition
            # Set default value if not already set
            if definition.key not in self.values:
                self.values[definition.key] = SettingValueVO(
                    value=definition.default_value,
                    data_type=definition.data_type,
                )

    def get_setting(self, key: str) -> Any | None:
        """Mendapatkan nilai pengaturan berdasarkan key."""
        setting = self.values.get(key)
        if setting:
            return setting.value
        definition = self.definitions.get(key)
        if definition:
            return definition.default_value
        return None

    def set_setting(
        self,
        key: str,
        value: Any,
        set_by: str,
    ) -> SystemSettings:
        """
        Mengatur nilai pengaturan.

        Args:
            key: Key pengaturan
            value: Nilai baru
            set_by: User yang mengubah

        Returns:
            SystemSettings yang diperbarui

        Raises:
            ValueError: Jika key tidak ditemukan, nilai tidak valid, atau setting terkunci
        """
        definition = self.definitions.get(key)
        if not definition:
            raise ValueError(f"Setting key '{key}' not found")

        if definition.is_locked:
            raise ValueError(f"Setting '{key}' is locked and cannot be changed")

        if self.status == SystemSettingsStatus.LOCKED:
            raise ValueError("System settings are locked")

        # Validate value
        if definition.is_required and (value is None or value == ""):
            raise ValueError(f"Setting '{key}' is required")

        validated_value = definition.validate(value)

        # Create new value VO
        new_value = SettingValueVO(
            value=validated_value,
            data_type=definition.data_type,
            set_by=set_by,
            set_at=datetime.now(UTC),
        )

        new_values = self.values.copy()
        new_values[key] = new_value

        return SystemSettings(
            settings_id=self.settings_id,
            legal_entity_id=self.legal_entity_id,
            status=self.status,
            definitions=self.definitions,
            values=new_values,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            version=self.version + 1,
        )

    def bulk_set_settings(
        self,
        settings: dict[str, Any],
        set_by: str,
    ) -> SystemSettings:
        """Mengatur multiple pengaturan sekaligus."""
        result = self
        for key, value in settings.items():
            result = result.set_setting(key, value, set_by)
        return result

    def reset_to_default(self, key: str, reset_by: str) -> SystemSettings:
        """Mereset pengaturan ke nilai default."""
        definition = self.definitions.get(key)
        if not definition:
            raise ValueError(f"Setting key '{key}' not found")

        return self.set_setting(key, definition.default_value, reset_by)

    def reset_all_to_default(self, reset_by: str) -> SystemSettings:
        """Mereset semua pengaturan ke nilai default."""
        result = self
        for key in self.definitions:
            result = result.reset_to_default(key, reset_by)
        return result

    def lock(self, locked_by: str) -> SystemSettings:
        """Mengunci sistem pengaturan (tidak dapat diubah)."""
        return SystemSettings(
            settings_id=self.settings_id,
            legal_entity_id=self.legal_entity_id,
            status=SystemSettingsStatus.LOCKED,
            definitions=self.definitions,
            values=self.values,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=locked_by,
            version=self.version + 1,
        )

    def unlock(self, unlocked_by: str) -> SystemSettings:
        """Membuka kunci sistem pengaturan."""
        return SystemSettings(
            settings_id=self.settings_id,
            legal_entity_id=self.legal_entity_id,
            status=SystemSettingsStatus.ACTIVE,
            definitions=self.definitions,
            values=self.values,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=unlocked_by,
            version=self.version + 1,
        )

    def add_definition(self, definition: SettingDefinitionEntity, added_by: str) -> SystemSettings:
        """Menambahkan definisi pengaturan baru."""
        if definition.key in self.definitions:
            raise ValueError(f"Setting key '{definition.key}' already exists")

        new_definitions = self.definitions.copy()
        new_definitions[definition.key] = definition

        # Set default value if not exists
        new_values = self.values.copy()
        if definition.key not in new_values:
            new_values[definition.key] = SettingValueVO(
                value=definition.default_value,
                data_type=definition.data_type,
            )

        return SystemSettings(
            settings_id=self.settings_id,
            legal_entity_id=self.legal_entity_id,
            status=self.status,
            definitions=new_definitions,
            values=new_values,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=added_by,
            version=self.version + 1,
        )

    def remove_definition(self, key: str, removed_by: str) -> SystemSettings:
        """Menghapus definisi pengaturan (hanya jika bukan required)."""
        definition = self.definitions.get(key)
        if not definition:
            raise ValueError(f"Setting key '{key}' not found")

        if definition.is_required:
            raise ValueError(f"Cannot remove required setting '{key}'")

        new_definitions = self.definitions.copy()
        del new_definitions[key]

        new_values = self.values.copy()
        new_values.pop(key, None)

        return SystemSettings(
            settings_id=self.settings_id,
            legal_entity_id=self.legal_entity_id,
            status=self.status,
            definitions=new_definitions,
            values=new_values,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=removed_by,
            version=self.version + 1,
        )

    def get_all_settings(self) -> dict[str, Any]:
        """Mendapatkan semua nilai pengaturan."""
        result = {}
        for key, definition in self.definitions.items():
            value = self.values.get(key)
            if value:
                result[key] = value.value
            else:
                result[key] = definition.default_value
        return result

    def get_settings_by_category(self, category: str) -> dict[str, Any]:
        """Mendapatkan pengaturan berdasarkan kategori."""
        result = {}
        for key, definition in self.definitions.items():
            if definition.category == category:
                value = self.values.get(key)
                result[key] = value.value if value else definition.default_value
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "settings_id": str(self.settings_id),
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else "global",
            "status": self.status.value,
            "settings": self.get_all_settings(),
            "definitions_count": len(self.definitions),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version": self.version,
        }


# === 4. ALIAS FOR REPOSITORY COMPATIBILITY ===
SystemSettingAggregate = SystemSettings


# === 5. SYSTEM SETTINGS REPOSITORY PROTOCOL ===


class SystemSettingsRepository:
    """
    Repository protocol untuk SystemSettings aggregate.
    """

    async def get_global(self) -> SystemSettings:
        raise NotImplementedError

    async def get_by_legal_entity(self, legal_entity_id: UUID) -> SystemSettings | None:
        raise NotImplementedError

    async def save(self, settings: SystemSettings) -> None:
        raise NotImplementedError

    async def delete(self, settings_id: UUID) -> None:
        raise NotImplementedError


# === 6. EXPORTS ===

__all__ = [
    "SettingCategory",
    "SettingDataType",
    "SettingScope",
    "SystemSettingAggregate",
    "SystemSettings",
    "SystemSettingsRepository",
    "SystemSettingsStatus",
]
