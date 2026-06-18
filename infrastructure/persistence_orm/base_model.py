#!/usr/bin/env python3
"""
Module: base_model.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan base class untuk semua model SQLAlchemy ORM.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

# ============================================================================
# BASE CLASS (only id and table name generator)
# ============================================================================

class Base(DeclarativeBase):
    """
    Base class untuk semua model SQLAlchemy ORM.
    Hanya menyediakan kolom id dan method __tablename__.
    Mixins lain (TimestampMixin, SoftDeleteMixin, dll) harus diwariskan secara eksplisit.
    """

    __abstract__ = True

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    @declared_attr
    def __tablename__(cls) -> str:
        """
        Generate table name from class name (snake_case).
        Contoh: LegalEntityTable -> legal_entity
        """
        name = cls.__name__
        if name.endswith("Table"):
            name = name[:-5]
        s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
        return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()

    def to_dict(self, exclude: set | None = None) -> dict[str, Any]:
        exclude = exclude or set()
        result = {}
        for column in self.__table__.columns:
            if column.name in exclude:
                continue
            value = getattr(self, column.name)
            if isinstance(value, datetime):
                value = value.isoformat()
            elif isinstance(value, UUID):
                value = str(value)
            result[column.name] = value
        return result

    def to_json(self, exclude: set | None = None) -> str:
        import json
        return json.dumps(self.to_dict(exclude), default=str)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Base:
        if "id" in data and isinstance(data["id"], str):
            data["id"] = uuid.UUID(data["id"])
        if "created_at" in data and isinstance(data["created_at"], str):
            data["created_at"] = datetime.fromisoformat(data["created_at"])
        if "updated_at" in data and isinstance(data["updated_at"], str):
            data["updated_at"] = datetime.fromisoformat(data["updated_at"])
        if "deleted_at" in data and data["deleted_at"] and isinstance(data["deleted_at"], str):
            data["deleted_at"] = datetime.fromisoformat(data["deleted_at"])
        return cls(**data)


# ============================================================================
# MIXINS
# ============================================================================

class UUIDMixin:
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def soft_delete(self) -> None:
        self.deleted_at = datetime.now(UTC)

    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class VersionMixin:
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    def increment_version(self) -> None:
        self.version += 1


class LegalEntityMixin:
    legal_entity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("legal_entity.id"), nullable=False, index=True
    )


class CreatedByMixin:
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
