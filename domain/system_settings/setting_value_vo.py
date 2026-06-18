#!/usr/bin/env python3
"""
Module: setting_value_vo.py
Layer: 6 - Domain / System Settings
Responsibility: Value object nilai pengaturan dengan validasi tipe.
               Mendefinisikan value object immutable untuk nilai pengaturan
               sistem, termasuk metadata seperti siapa yang mengubah dan kapan.

Dependencies:
- standard library (datetime, decimal, json, logging)
- domain.system_settings.setting_definition_entity (SettingDataType)

Audit: Setiap perubahan nilai pengaturan dictat.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# === 1. CONSTANTS & ENUMS ===


class SettingDataType(Enum):
    """Tipe data untuk nilai pengaturan."""

    STRING = "string"
    INTEGER = "integer"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"
    JSON = "json"
    DATE = "date"
    DATETIME = "datetime"


# === 2. SETTING VALUE VALUE OBJECT ===


@dataclass(frozen=True)
class SettingValueVO:
    """
    Value object untuk nilai pengaturan (immutable).

    Business context: Menyimpan nilai pengaturan dengan metadata
    untuk audit trail. Immutable untuk mencegah perubahan tidak sah.
    """

    value: Any
    data_type: SettingDataType
    set_by: str = "system"
    set_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        """Validasi nilai sesuai tipe data."""
        self._validate_value()

    def _validate_value(self) -> None:
        """Memvalidasi nilai berdasarkan tipe data."""
        if self.value is None:
            return

        if self.data_type == SettingDataType.STRING:
            if not isinstance(self.value, str):
                raise ValueError(f"Expected string, got {type(self.value).__name__}")

        elif self.data_type == SettingDataType.INTEGER:
            if not isinstance(self.value, int) or isinstance(self.value, bool):
                raise ValueError(f"Expected integer, got {type(self.value).__name__}")

        elif self.data_type == SettingDataType.DECIMAL:
            if not isinstance(self.value, (int, float, Decimal)):
                raise ValueError(f"Expected decimal, got {type(self.value).__name__}")

        elif self.data_type == SettingDataType.BOOLEAN:
            if not isinstance(self.value, bool):
                raise ValueError(f"Expected boolean, got {type(self.value).__name__}")

        elif self.data_type == SettingDataType.JSON:
            if not isinstance(self.value, (dict, list)):
                raise ValueError(f"Expected JSON (dict/list), got {type(self.value).__name__}")

        elif self.data_type == SettingDataType.DATE:
            # Validation for date format
            if isinstance(self.value, str):
                try:
                    from datetime import date

                    date.fromisoformat(self.value)
                except ValueError:
                    raise ValueError(f"Invalid date format: {self.value}. Expected YYYY-MM-DD")
            elif not hasattr(self.value, "isoformat"):
                raise ValueError(f"Expected date or ISO string, got {type(self.value).__name__}")

        elif self.data_type == SettingDataType.DATETIME:
            # Validation for datetime format
            if isinstance(self.value, str):
                try:
                    datetime.fromisoformat(self.value)
                except ValueError:
                    raise ValueError(f"Invalid datetime format: {self.value}")
            elif not hasattr(self.value, "isoformat"):
                raise ValueError(
                    f"Expected datetime or ISO string, got {type(self.value).__name__}"
                )

    def get_typed_value(self) -> Any:
        """Mendapatkan nilai dalam tipe Python yang sesuai."""
        if self.data_type == SettingDataType.DECIMAL:
            return Decimal(str(self.value))
        elif self.data_type == SettingDataType.DATE:
            if isinstance(self.value, str):
                from datetime import date

                return date.fromisoformat(self.value)
            return self.value
        elif self.data_type == SettingDataType.DATETIME:
            if isinstance(self.value, str):
                return datetime.fromisoformat(self.value)
            return self.value
        elif self.data_type == SettingDataType.JSON:
            return self.value  # Already dict/list
        else:
            return self.value

    def to_serializable(self) -> Any:
        """Mengkonversi ke format yang dapat diserialisasi JSON."""
        if self.data_type == SettingDataType.DECIMAL:
            return float(self.value) if self.value is not None else None
        elif self.data_type == SettingDataType.DATE or self.data_type == SettingDataType.DATETIME:
            if hasattr(self.value, "isoformat"):
                return self.value.isoformat()
            return self.value
        elif self.data_type == SettingDataType.JSON:
            return self.value
        else:
            return self.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.to_serializable(),
            "data_type": self.data_type.value,
            "set_by": self.set_by,
            "set_at": self.set_at.isoformat(),
        }

    def __repr__(self) -> str:
        return f"SettingValueVO(data_type={self.data_type.value}, value={self.to_serializable()})"


# === 3. EXPORTS ===

__all__ = [
    "SettingDataType",
    "SettingValueVO",
]
