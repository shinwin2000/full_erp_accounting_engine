"""
Sama seperti repro_audit_isolated.py, tapi menyertakan PERSIS hack
__init_subclass__ dari base_model.py asli. Jalankan: python repro_audit_with_hack.py
"""
from __future__ import annotations

import uuid
from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column


class Base(DeclarativeBase):
    __abstract__ = True
    type_annotation_map = {UUID: PGUUID(as_uuid=True)}
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    @classmethod
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if not cls.__dict__.get("__abstract__", False):
            try:
                reg = cls.registry._class_registry
                class_name = cls.__name__
                dict.__setitem__(reg, class_name, cls)
                if hasattr(reg, "_data") and isinstance(reg._data, dict):
                    reg._data[class_name] = cls
            except Exception:
                pass

    @declared_attr
    def __tablename__(cls) -> str:
        return cls.__name__.lower()


class AuditTable(Base):
    __tablename__ = "audit"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


print("BERHASIL: AuditTable ter-mapping tanpa error.")
print("Primary key:", [c.name for c in AuditTable.__table__.primary_key.columns])
