#!/usr/bin/env python3
"""
Module: setting_definition_entity.py
Layer: 6 - Domain / System Settings
Responsibility: Definisi pengaturan (kunci, tipe, deskripsi).
               Mendefinisikan entitas untuk mendefinisikan metadata
               dari setiap pengaturan sistem, termasuk tipe data,
               nilai default, validasi, dan kategori.

Dependencies:
- standard library (uuid, datetime, re, decimal)
- domain.system_settings.setting_value_vo (SettingDataType)

Audit: Setiap perubahan definisi pengaturan dictat.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from domain.system_settings.setting_value_vo import SettingDataType

logger = logging.getLogger(__name__)


# === 1. SETTING DEFINITION ENTITY ===


@dataclass
class SettingDefinitionEntity:
    """
    Entitas definisi pengaturan.

    Business context: Mendefinisikan metadata untuk setiap pengaturan
    sistem termasuk bagaimana nilai harus divalidasi.
    """

    definition_id: UUID
    key: str
    data_type: SettingDataType
    default_value: Any
    description: str
    is_required: bool = False
    is_sensitive: bool = False
    is_locked: bool = False
    category: str = "general"
    min_value: int | float | Decimal | None = None
    max_value: int | float | Decimal | None = None
    allowed_values: list[Any] | None = None
    regex_pattern: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    version: int = 1

    def __post_init__(self) -> None:
        """Validasi definisi."""
        if not self.key or len(self.key.strip()) < 2:
            raise ValueError("Setting key must be at least 2 characters")
        if not self.description:
            raise ValueError("Description is required")
        # Validate default value matches data type
        self.validate(self.default_value)

    def validate(self, value: Any) -> Any:
        """
        Memvalidasi nilai terhadap definisi.

        Args:
            value: Nilai yang akan divalidasi

        Returns:
            Nilai yang sudah dikonversi ke tipe yang benar

        Raises:
            ValueError: Jika nilai tidak valid
        """
        # Check required
        if self.is_required and (value is None or value == ""):
            raise ValueError(f"Setting '{self.key}' is required")

        if value is None:
            return None

        # Type validation and conversion
        if self.data_type == SettingDataType.STRING:
            if not isinstance(value, str):
                value = str(value)
            if self.regex_pattern and not re.match(self.regex_pattern, value):
                raise ValueError(f"Value '{value}' does not match pattern {self.regex_pattern}")

        elif self.data_type == SettingDataType.INTEGER:
            try:
                value = int(value)
                if self.min_value is not None and value < self.min_value:
                    raise ValueError(f"Value {value} is below minimum {self.min_value}")
                if self.max_value is not None and value > self.max_value:
                    raise ValueError(f"Value {value} exceeds maximum {self.max_value}")
            except (ValueError, TypeError):
                raise ValueError(f"Value '{value}' is not a valid integer")

        elif self.data_type == SettingDataType.DECIMAL:
            try:
                value = Decimal(str(value))
                if self.min_value is not None and value < Decimal(str(self.min_value)):
                    raise ValueError(f"Value {value} is below minimum {self.min_value}")
                if self.max_value is not None and value > Decimal(str(self.max_value)):
                    raise ValueError(f"Value {value} exceeds maximum {self.max_value}")
            except (ValueError, TypeError):
                raise ValueError(f"Value '{value}' is not a valid decimal")

        elif self.data_type == SettingDataType.BOOLEAN:
            if isinstance(value, str):
                value = value.lower() in ("true", "1", "yes", "on")
            elif isinstance(value, int | float):
                value = bool(value)
            elif not isinstance(value, bool):
                raise ValueError(f"Value '{value}' is not a valid boolean")

        elif self.data_type == SettingDataType.JSON:
            if isinstance(value, str):
                import json

                try:
                    value = json.loads(value)
                except json.JSONDecodeError:
                    raise ValueError(f"Value '{value}' is not valid JSON")
            elif not isinstance(value, dict | list):
                raise ValueError(f"Value '{value}' is not valid JSON (dict or list expected)")

        # Check allowed values
        if self.allowed_values and value not in self.allowed_values:
            raise ValueError(f"Value '{value}' not in allowed values: {self.allowed_values}")

        return value

    def to_dict(self) -> dict[str, Any]:
        return {
            "definition_id": str(self.definition_id),
            "key": self.key,
            "data_type": self.data_type.value,
            "default_value": self.default_value,
            "description": self.description,
            "is_required": self.is_required,
            "is_sensitive": self.is_sensitive,
            "is_locked": self.is_locked,
            "category": self.category,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "allowed_values": self.allowed_values,
            "regex_pattern": self.regex_pattern,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version": self.version,
        }


# === 2. SETTING DEFINITION REPOSITORY PROTOCOL ===


class SettingDefinitionRepository:
    """
    Repository protocol untuk SettingDefinitionEntity.
    """

    async def get_by_id(self, definition_id: UUID) -> SettingDefinitionEntity | None:
        raise NotImplementedError

    async def get_by_key(self, key: str) -> SettingDefinitionEntity | None:
        raise NotImplementedError

    async def get_by_category(self, category: str) -> list[SettingDefinitionEntity]:
        raise NotImplementedError

    async def save(self, definition: SettingDefinitionEntity) -> None:
        raise NotImplementedError

    async def delete(self, definition_id: UUID) -> None:
        raise NotImplementedError

    async def list_all(self, limit: int = 100, offset: int = 0) -> list[SettingDefinitionEntity]:
        raise NotImplementedError


# === 3. EXPORTS ===

__all__ = [
    "SettingDefinitionEntity",
    "SettingDefinitionRepository",
]
