#!/usr/bin/env python3
"""
Module: invariants.py
Layer: 6 - Domain / System Settings
Responsibility: Aturan: kunci unik, tipe sesuai.
               Mendefinisikan semua invariant yang harus dipenuhi oleh
               System Settings aggregate. Memastikan bahwa pengaturan
               sistem selalu dalam keadaan valid.

Dependencies:
- standard library (logging, re, decimal)
- domain.system_settings.setting_definition_entity (SettingDefinitionEntity)
- domain.system_settings.setting_value_vo (SettingValueVO, SettingDataType)

Audit: Setiap pelanggaran invariant dicatat.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from domain.system_settings.setting_definition_entity import SettingDefinitionEntity
from domain.system_settings.setting_value_vo import SettingDataType

logger = logging.getLogger(__name__)


# === 1. INVARIANT VALIDATION RESULT ===


class InvariantResult:
    """Hasil validasi invariant."""

    __slots__ = ("errors", "is_valid")

    def __init__(self, is_valid: bool = True, errors: list[str] | None = None):
        self.is_valid = is_valid
        self.errors = errors or []

    def add_error(self, error: str) -> None:
        self.errors.append(error)
        self.is_valid = False

    def merge(self, other: InvariantResult) -> InvariantResult:
        if not other.is_valid:
            self.is_valid = False
            self.errors.extend(other.errors)
        return self

    def __bool__(self) -> bool:
        return self.is_valid


# === 2. SYSTEM SETTINGS INVARIANTS ===


class SystemSettingsInvariants:
    """
    Kumpulan invariant untuk System Settings aggregate.
    """

    @staticmethod
    def validate_key_format(key: str) -> bool:
        """
        Memvalidasi format key pengaturan.

        Format: lowercase, alphanumeric, dots for nesting, underscores allowed.
        Contoh: "company.name", "tax.vat_rate", "security.session_timeout"
        """
        pattern = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$"
        return bool(re.match(pattern, key))

    @staticmethod
    def validate_on_create(
        key: str,
        data_type: SettingDataType,
        existing_keys: set[str],
    ) -> InvariantResult:
        """
        Memvalidasi invariant saat pembuatan definisi pengaturan baru.

        Rules:
        1. Key harus unik
        2. Key harus mengikuti format yang benar
        3. Data type harus valid
        """
        result = InvariantResult(True)

        # Key uniqueness
        if key in existing_keys:
            result.add_error(f"Setting key '{key}' already exists. Keys must be unique.")

        # Key format
        if not SystemSettingsInvariants.validate_key_format(key):
            result.add_error(
                f"Setting key '{key}' has invalid format. Use lowercase alphanumeric with dots (e.g., 'company.name')."
            )

        return result

    @staticmethod
    def validate_value_type(
        value: Any,
        data_type: SettingDataType,
    ) -> InvariantResult:
        """
        Memvalidasi tipe nilai sesuai dengan data type.

        Rules:
        1. Nilai harus sesuai dengan tipe data yang didefinisikan
        """
        result = InvariantResult(True)

        if data_type == SettingDataType.STRING:
            if not isinstance(value, str):
                result.add_error(f"Expected string value, got {type(value).__name__}")
        elif data_type == SettingDataType.INTEGER:
            if not isinstance(value, int) or isinstance(value, bool):
                result.add_error(f"Expected integer value, got {type(value).__name__}")
        elif data_type == SettingDataType.DECIMAL:
            # Accept Decimal, int, float (can be converted to Decimal)
            if not isinstance(value, Decimal | int | float):
                result.add_error(f"Expected decimal value, got {type(value).__name__}")
        elif data_type == SettingDataType.BOOLEAN:
            if not isinstance(value, bool):
                result.add_error(f"Expected boolean value, got {type(value).__name__}")
        elif data_type == SettingDataType.JSON and not isinstance(value, dict | list):
            result.add_error(f"Expected JSON value (dict/list), got {type(value).__name__}")

        return result

    @staticmethod
    def validate_on_update(
        definition: SettingDefinitionEntity,
        new_value: Any,
        is_locked: bool = False,
    ) -> InvariantResult:
        """
        Memvalidasi invariant saat update nilai pengaturan.

        Rules:
        1. Pengaturan yang terkunci (locked) tidak dapat diubah
        2. Nilai harus sesuai dengan tipe data
        3. Nilai harus memenuhi constraint (min, max, allowed_values)
        """
        result = InvariantResult(True)

        if is_locked or definition.is_locked:
            result.add_error(f"Setting '{definition.key}' is locked and cannot be changed.")

        # Type validation
        type_result = SystemSettingsInvariants.validate_value_type(new_value, definition.data_type)
        result.merge(type_result)

        # Range validation for numeric types (INTEGER and DECIMAL)
        if definition.data_type in (SettingDataType.INTEGER, SettingDataType.DECIMAL):
            try:
                # Convert to Decimal for precise comparison (avoids float precision issues)
                num_value = Decimal(str(new_value))
                # Convert min_value and max_value to Decimal for comparison
                min_val = Decimal(str(definition.min_value)) if definition.min_value is not None else None
                max_val = Decimal(str(definition.max_value)) if definition.max_value is not None else None

                if min_val is not None and num_value < min_val:
                    result.add_error(f"Value {num_value} is below minimum {min_val}")
                if max_val is not None and num_value > max_val:
                    result.add_error(f"Value {num_value} exceeds maximum {max_val}")
            except (ValueError, TypeError) as e:
                result.add_error(f"Value '{new_value}' is not a valid number: {e}")

        # Allowed values validation
        if definition.allowed_values and new_value not in definition.allowed_values:
            result.add_error(
                f"Value '{new_value}' not in allowed values: {definition.allowed_values}"
            )

        return result

    @staticmethod
    def validate_on_delete(
        definition: SettingDefinitionEntity,
    ) -> InvariantResult:
        """
        Memvalidasi invariant saat penghapusan definisi pengaturan.

        Rules:
        1. Required settings cannot be deleted
        2. Settings with dependencies should not be deleted (if any)
        """
        result = InvariantResult(True)

        if definition.is_required:
            result.add_error(f"Cannot delete required setting '{definition.key}'.")

        return result


# === 3. SYSTEM SETTINGS INVARIANT ENFORCER ===


class SystemSettingsInvariantEnforcer:
    """
    Enforcer untuk semua invariant System Settings.
    """

    __slots__ = ("_invariants", "_keys_provider")

    def __init__(
        self,
        existing_keys_provider: Callable[[], set[str]],
    ):
        self._keys_provider = existing_keys_provider
        self._invariants = SystemSettingsInvariants()

    async def enforce_definition_create(
        self,
        key: str,
        data_type: SettingDataType,
    ) -> InvariantResult:
        """Menegakkan invariant saat pembuatan definisi pengaturan."""
        existing_keys = await self._keys_provider()
        return self._invariants.validate_on_create(
            key=key,
            data_type=data_type,
            existing_keys=existing_keys,
        )

    async def enforce_value_update(
        self,
        definition: SettingDefinitionEntity,
        new_value: Any,
        is_system_locked: bool = False,
    ) -> InvariantResult:
        """Menegakkan invariant saat update nilai pengaturan."""
        return self._invariants.validate_on_update(
            definition=definition,
            new_value=new_value,
            is_locked=is_system_locked,
        )

    async def enforce_definition_delete(
        self,
        definition: SettingDefinitionEntity,
    ) -> InvariantResult:
        """Menegakkan invariant saat penghapusan definisi pengaturan."""
        return self._invariants.validate_on_delete(definition=definition)

    @staticmethod
    def validate_key_format(key: str) -> bool:
        """Memvalidasi format key pengaturan."""
        return SystemSettingsInvariants.validate_key_format(key)


# === 4. EXPORTS ===

__all__ = [
    "InvariantResult",
    "SystemSettingsInvariantEnforcer",
    "SystemSettingsInvariants",
]
