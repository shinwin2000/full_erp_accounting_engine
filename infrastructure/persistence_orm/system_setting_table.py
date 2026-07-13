#!/usr/bin/env python3
"""
Module: system_setting_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel system_setting.
               Tabel ini menyimpan konfigurasi dinamis sistem yang dapat diubah
               tanpa deployment ulang. Mendukung scope per legal entity, tipe data
               (string, integer, boolean, JSON, decimal), validasi, dan audit trail.
               Setting yang bersifat read-only (kritis) dapat dilindungi.
Dependencies:
- sqlalchemy.orm (Mapped, mapped_column)
- sqlalchemy.dialects.postgresql (UUID, JSONB)
- infrastructure.persistence_orm.base_model (Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin)
Audit: Setiap perubahan setting dicatat di event store.
       Perubahan setting kritis memicu alert.

Perbaikan presisi:
    - Mengganti penggunaan float() pada tipe data 'float' dengan Decimal untuk
      menjaga presisi dan memenuhi aturan MNY-003.
    - Menghapus properti `typed_value_as_float` karena mengembalikan float untuk
      nilai moneter (melanggar MNY-024). Gunakan `typed_value` yang mengembalikan Decimal.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence_orm.base_model import (
    Base,
    LegalEntityMixin,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)

# ============================================================================
# MODEL
# ============================================================================


class SystemSettingTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    """
    Model untuk tabel system_setting.
    """

    __tablename__ = "system_setting"
    __table_args__ = (
        UniqueConstraint("key", "legal_entity_id", name="uq_system_setting_key_legal_entity"),
        CheckConstraint("key IS NOT NULL AND key != ''", name="ck_system_setting_key"),
        CheckConstraint(
            "data_type IN ('string', 'integer', 'float', 'boolean', 'json', 'decimal')",
            name="ck_system_setting_data_type",
        ),
        CheckConstraint(
            "category IN ('general', 'accounting', 'tax', 'security', 'audit', 'integration', 'performance')",
            name="ck_system_setting_category",
        ),
        CheckConstraint("scope IN ('global', 'legal_entity')", name="ck_system_setting_scope"),
        Index("idx_system_setting_key", "key"),
        Index("idx_system_setting_category", "category"),
        Index("idx_system_setting_scope", "scope"),
        Index("idx_system_setting_legal_entity", "legal_entity_id"),
        Index("idx_system_setting_status", "is_active"),
    )

    # Setting identification
    key: Mapped[str] = mapped_column(String(200), nullable=False)  # unique per legal_entity
    data_type: Mapped[str] = mapped_column(String(20), nullable=False, default="string")

    # Value storage (as string, but typed accordingly)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Metadata
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="general")
    scope: Mapped[str] = mapped_column(String(20), nullable=False, default="global")

    # Validation and constraints
    validation_regex: Mapped[str | None] = mapped_column(String(500), nullable=True)
    min_value: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # string representation of min
    max_value: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # string representation of max
    allowed_values: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    # Default and current
    default_value: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Flags
    is_readonly: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_encrypted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Audit
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # ========================================================================
    # PROPERTIES
    # ========================================================================

    @property
    def typed_value(self) -> Any:
        """
        Get value with proper Python type based on data_type.
        Untuk tipe 'float' dan 'decimal', dikembalikan sebagai Decimal.
        """
        if self.data_type == "string":
            return self.value
        elif self.data_type == "integer":
            return int(self.value) if self.value else 0
        elif self.data_type == "float":
            # Mengembalikan Decimal untuk presisi tinggi
            return Decimal(self.value) if self.value else Decimal(0)
        elif self.data_type == "boolean":
            return self.value.lower() in ("true", "1", "yes", "on")
        elif self.data_type == "json":
            import json

            return json.loads(self.value) if self.value else {}
        elif self.data_type == "decimal":
            return Decimal(self.value) if self.value else Decimal(0)
        return self.value

    @typed_value.setter
    def typed_value(self, val: Any) -> None:
        """
        Set value from Python type, converting to string storage.
        Untuk tipe 'float' dan 'decimal', gunakan Decimal untuk presisi.
        """
        if self.data_type == "string":
            self.value = str(val)
        elif self.data_type == "integer":
            self.value = str(int(val))
        elif self.data_type == "float":
            # Simpan sebagai string dari Decimal
            self.value = str(Decimal(str(val)))
        elif self.data_type == "boolean":
            self.value = "true" if val else "false"
        elif self.data_type == "json":
            import json

            self.value = json.dumps(val)
        elif self.data_type == "decimal":
            self.value = str(Decimal(str(val)))
        else:
            self.value = str(val)

    @property
    def is_global(self) -> bool:
        return self.scope == "global"

    @property
    def is_legal_entity_scoped(self) -> bool:
        return self.scope == "legal_entity"

    # ========================================================================
    # METHODS
    # ========================================================================

    def validate(self, val: Any) -> bool:
        """
        Validate a value against constraints.
        Untuk tipe 'float' dan 'decimal', validasi menggunakan Decimal.
        """
        # Type check
        try:
            if self.data_type == "integer":
                int(val)
            elif self.data_type == "float" or self.data_type == "decimal":
                Decimal(str(val))
            elif self.data_type == "boolean":
                if isinstance(val, str):
                    val = val.lower() in ("true", "1", "yes", "on")
        except (ValueError, TypeError):
            return False

        # Min/Max
        if self.min_value is not None:
            min_val = Decimal(self.min_value)
            if self.data_type == "integer":
                if int(val) < int(min_val):
                    return False
            elif self.data_type in ("float", "decimal"):
                if Decimal(str(val)) < min_val:
                    return False

        if self.max_value is not None:
            max_val = Decimal(self.max_value)
            if self.data_type == "integer":
                if int(val) > int(max_val):
                    return False
            elif self.data_type in ("float", "decimal"):
                if Decimal(str(val)) > max_val:
                    return False

        # Allowed values
        if self.allowed_values:
            str_val = str(val).lower()
            if str_val not in [str(v).lower() for v in self.allowed_values]:
                return False

        # Regex
        if self.validation_regex:
            import re

            if not re.match(self.validation_regex, str(val)):
                return False

        return True

    def reset_to_default(self) -> None:
        """Reset setting to its default value."""
        if self.default_value is not None:
            self.value = self.default_value
            self.increment_version()

    def activate(self) -> None:
        self.is_active = True
        self.increment_version()

    def deactivate(self) -> None:
        self.is_active = False
        self.increment_version()


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ["SystemSettingTable"]
