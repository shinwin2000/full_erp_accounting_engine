#!/usr/bin/env python3
"""
Module: base_model.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Base class untuk semua model SQLAlchemy ORM
               + Soft Delete Auto-Filter + Audit Immutability Protection
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, event, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Query,
    Session,
    declared_attr,
    mapped_column,
)
from sqlalchemy.sql.elements import BinaryExpression

# ============================================================================
# EVENT LISTENER: SOFT DELETE AUTO-FILTER (Default Scope)
# ============================================================================

@event.listens_for(Query, 'before_compile', retval=True)
def apply_soft_delete_filter(query):
    """
    Menambahkan filter deleted_at IS NULL ke semua query yang melibatkan
    model yang memiliki kolom 'deleted_at', kecuali jika session menyetel
    flag 'include_deleted' = True.
    """
    if query.session and query.session.info.get('include_deleted', False):
        return query

    for entity in query.column_descriptions:
        if 'entity' in entity:
            entity_class = entity['entity']
            if hasattr(entity_class, 'deleted_at'):
                filter_cond = entity_class.deleted_at.is_(None)
                # Cek apakah sudah ada filter serupa (sederhana)
                if not any(isinstance(elem, BinaryExpression) and hasattr(elem, 'left') and elem.left is entity_class.deleted_at for elem in query._where_criteria):
                    return query.filter(filter_cond)
    return query


# ============================================================================
# EVENT LISTENER: AUDIT IMMUTABILITY (Cegah UPDATE/DELETE)
# ============================================================================

@event.listens_for(Session, 'before_flush')
def prevent_audit_modification(session, flush_context, instances):
    """
    Mencegah update atau delete pada model yang memiliki flag __is_audit_log__ = True.
    """
    for obj in session.dirty:
        if hasattr(obj, '__is_audit_log__') and obj.__is_audit_log__:
            raise RuntimeError(f"Audit log is immutable: cannot update {obj.__class__.__name__} (id={obj.id})")
    for obj in session.deleted:
        if hasattr(obj, '__is_audit_log__') and obj.__is_audit_log__:
            raise RuntimeError(f"Audit log is immutable: cannot delete {obj.__class__.__name__} (id={obj.id})")


# ============================================================================
# BASE CLASS
# ============================================================================

class Base(DeclarativeBase):
    __abstract__ = True

    type_annotation_map = {
        UUID: PGUUID(as_uuid=True)
    }

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    @declared_attr
    def __tablename__(cls) -> str:
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
            if value is None:
                result[column.name] = None
            elif isinstance(value, datetime):
                result[column.name] = value.isoformat()
            elif isinstance(value, UUID) or isinstance(value, Decimal):
                result[column.name] = str(value)
            else:
                result[column.name] = value
        return result

    def to_json(self, exclude: set | None = None) -> str:
        return json.dumps(self.to_dict(exclude), default=str)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Any:
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

    @classmethod
    def not_deleted(cls):
        return cls.deleted_at.is_(None)

    @classmethod
    def get_query(cls, session):
        return session.query(cls).filter(cls.deleted_at.is_(None))


class VersionMixin:
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    @declared_attr
    def __mapper_args__(cls) -> dict[str, Any]:
        return {"version_id_col": cls.version}

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
