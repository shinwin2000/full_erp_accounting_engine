"""
Repro TERISOLASI: cuma Base + AuditTable, tanpa 94 file model lain.
Jalankan: python repro_audit_isolated.py
Kalau ini SUKSES (tidak error) -> Hipotesis B benar (masalahnya kontaminasi
    dari file/class lain di test session, bukan audit_table.py itu sendiri).
Kalau ini GAGAL dengan error yang SAMA -> Hipotesis A benar (murni bug
    interaksi Base.id vs AuditTable.id / cara Base didefinisikan).
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Integer, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column


# ---- SALIN PERSIS dari base_model.py (versi disederhanakan, minus hack registry) ----
class Base(DeclarativeBase):
    __abstract__ = True
    type_annotation_map = {UUID: PGUUID(as_uuid=True)}
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    @declared_attr
    def __tablename__(cls) -> str:
        return cls.__name__.lower()


# ---- SALIN PERSIS dari audit_table.py ----
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
print("Kolom table 'audit':", [c.name for c in AuditTable.__table__.columns])
print("Primary key:", [c.name for c in AuditTable.__table__.primary_key.columns])
