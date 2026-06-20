#!/usr/bin/env python3
"""
Module: base_model.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan base class untuk semua model SQLAlchemy ORM
                dengan pengerasan tingkat enterprise (Sovereign-Grade Security).
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

# ============================================================================
# BASE CLASS (With Runtime Type Mapping & Security Hardening)
# ============================================================================

class Base(DeclarativeBase):
    """
    Base class tingkat tinggi untuk semua model SQLAlchemy ORM.
    Menyediakan automasi pemetaan tipe global, generator nama tabel aman,
    serta fungsionalitas serialisasi yang kebal terhadap kebocoran tipe data.
    """

    __abstract__ = True

    # Memaksa SQLAlchemy memetakan Mapped[UUID] ke PGUUID PostgreSQL secara otomatis di semua tabel.
    type_annotation_map = {
        UUID: PGUUID(as_uuid=True)
    }

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    @classmethod
    def __init_subclass__(cls, **kwargs):
        """
        🎯 INTERSEPTOR LIFECYCLE: Menyuntikkan pengaman langsung saat kelas dievaluasi.
        Memotong pembentukan token konflik jika kelas di-import ulang dari path berbeda.
        """
        super().__init_subclass__(**kwargs)
        if not cls.__dict__.get("__abstract__", False):
            try:
                reg = cls.registry._class_registry
                class_name = cls.__name__
                # Paksa penulisan langsung ke root dictionary tingkat rendah Python
                # bypass ini menghancurkan token '_multiple_resolved' dari SQLAlchemy
                dict.__setitem__(reg, class_name, cls)
                if hasattr(reg, "_data") and isinstance(reg._data, dict):
                    reg._data[class_name] = cls
            except Exception:
                pass

    @declared_attr
    def __tablename__(cls) -> str:
        """
        Membuat nama tabel secara otomatis dengan format snake_case dari nama Class.
        Contoh: ManufacturingWorkOrderTable -> manufacturing_work_order
        """
        name = cls.__name__
        if name.endswith("Table"):
            name = name[:-5]
        s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
        return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()

    def to_dict(self, exclude: set | None = None) -> dict[str, Any]:
        """
        Mengonversi baris database menjadi Python dictionary secara aman.
        Mendukung konversi Decimal secara presisi untuk kebutuhan audit kepatuhan finansial.
        """
        exclude = exclude or set()
        result = {}
        for column in self.__table__.columns:
            if column.name in exclude:
                continue
            value = getattr(self, column.name)
            
            if value is None:
                result[column.name] = None
            elif isinstance(value, datetime):
                result[column.name] = value.isoformat()
            elif isinstance(value, UUID):
                result[column.name] = str(value)
            elif isinstance(value, Decimal):
                result[column.name] = str(value)
            else:
                result[column.name] = value
        return result

    def to_json(self, exclude: set | None = None) -> str:
        """Serialisasi aman ke JSON."""
        return json.dumps(self.to_dict(exclude), default=str)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Any:
        """
        Instansiasi model secara aman (Anti Mass-Assignment Vulnerability).
        Hanya menerima key yang terdaftar sah pada kolom database dan melakukan
        casting tipe data primitif secara ketat sebelum masuk ke engine ORM.
        """
        clean_data = {}
        mapper_columns = cls.__mapper__.columns
        
        for key, value in data.items():
            if key in mapper_columns:
                col_type = mapper_columns[key].type
                if value is not None:
                    if isinstance(col_type, PGUUID) or "UUID" in str(col_type):
                        if isinstance(value, str):
                            value = uuid.UUID(value)
                    elif isinstance(col_type, DateTime) or "DateTime" in str(col_type):
                        if isinstance(value, str):
                            value = datetime.fromisoformat(value)
                    elif "Numeric" in str(col_type) or "Decimal" in str(col_type):
                        if isinstance(value, (str, float, int)):
                            value = Decimal(str(value))
                clean_data[key] = value
                
        return cls(**clean_data)


# ============================================================================
# HARDENED MIXINS (Re-usable Enterprise Components)
# ============================================================================

class UUIDMixin:
    """Mixin untuk entitas yang membutuhkan ID berbasis UUIDv4 mandiri."""
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    """Mixin untuk pencatatan jejak forensik waktu pembuatan dan modifikasi data."""
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SoftDeleteMixin:
    """Mixin untuk retensi data aman tanpa benar-benar menghapus baris fisik dari storage."""
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def soft_delete(self) -> None:
        self.deleted_at = datetime.now(UTC)

    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class VersionMixin:
    """
    Mixin Pengendali Konkurensi Optimistik (Optimistic Concurrency Control).
    Mengunci baris secara atomik untuk mencegah 'race condition' atau bentrokan update data ledger.
    """
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    @declared_attr
    def __mapper_args__(cls) -> dict[str, Any]:
        return {"version_id_col": cls.version}

    def increment_version(self) -> None:
        self.version += 1


class LegalEntityMixin:
    """Mixin Multi-Tenant berbasis Entitas Hukum Resmi."""
    legal_entity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("legal_entity.id"), nullable=False, index=True
    )


class CreatedByMixin:
    """Mixin Akuntabilitas untuk melacak ID Operator eksekutor transaksi."""
    created_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=True)


__all__ = [
    "Base",
    "CreatedByMixin",
    "LegalEntityMixin",
    "SoftDeleteMixin",
    "TimestampMixin",
    "UUIDMixin",
    "VersionMixin",
]