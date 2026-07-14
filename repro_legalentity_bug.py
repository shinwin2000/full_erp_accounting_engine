"""
Uji hipotesis: LegalEntityMixin (dengan ForeignKey didefinisikan langsung,
bukan lewat @declared_attr) menyebabkan crash saat dipakai oleh LEBIH DARI SATU
class dalam proses yang sama -- persis seperti saat pytest collect banyak file model.

Jalankan: python repro_legalentity_bug.py
"""
from __future__ import annotations

import uuid
from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column


class Base(DeclarativeBase):
    __abstract__ = True
    type_annotation_map = {UUID: PGUUID(as_uuid=True)}
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    @declared_attr
    def __tablename__(cls) -> str:
        return cls.__name__.lower()


# ---- VERSI BUGGY (persis seperti base_model.py asli) ----
class LegalEntityMixinBuggy:
    legal_entity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("legal_entity.id"), nullable=False, index=True
    )


print("=== TES 1: satu class dengan LegalEntityMixin buggy ===")
class FirstTable(Base, LegalEntityMixinBuggy):
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

print("BERHASIL untuk class pertama.")

print("=== TES 2: class KEDUA dengan mixin buggy YANG SAMA (ini yang mensimulasikan pytest collect banyak file) ===")
try:
    class SecondTable(Base, LegalEntityMixinBuggy):
        note: Mapped[str] = mapped_column(default="x")
    print("BERHASIL untuk class kedua juga (hipotesis SALAH, mixin bukan penyebabnya).")
except Exception as e:
    print(f"GAGAL persis seperti di pytest! Error: {type(e).__name__}: {e}")
