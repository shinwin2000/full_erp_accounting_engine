#!/usr/bin/env python3
"""
Module: budget_revision_history_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Riwayat versi/revisi budget -- satu baris ditulis setiap kali
budget dibuat atau diperbarui (create/update/status transition/revise).

LATAR BELAKANG:
    Sebelumnya endpoint `GET /budget/budget/versions/{budget_code}` yang
    dipanggil tab "Versi Budget" di frontend TIDAK PERNAH ADA di backend
    (404 selalu). Selain itu, tidak ada mekanisme apapun yang menyimpan
    histori perubahan budget secara persisten -- `_log_audit()` di
    repository cuma menyimpan ke list in-memory yang hilang begitu request
    selesai, dan decorator `@audit` di service_budget.py ternyata cuma
    dummy (`return func`, tidak melakukan apa-apa).

    Tabel baru ini murni ADDITIF (tidak mengubah tabel `budget` yang sudah
    ada) -- setiap create/update budget menulis satu snapshot ringkas ke
    sini, supaya riwayat versi bisa benar-benar ditelusuri.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import DateTime, Index, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence_orm.base_model import Base, TimestampMixin


class BudgetRevisionHistoryTable(Base, TimestampMixin):
    """Satu baris = satu snapshot budget pada satu titik waktu."""

    __tablename__ = "budget_revision_history"
    __table_args__ = (
        Index("idx_budget_revision_history_budget_id", "budget_id"),
        Index(
            "idx_budget_revision_history_code_entity",
            "budget_code",
            "legal_entity_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    budget_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    legal_entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    budget_code: Mapped[str] = mapped_column(String(50), nullable=False)

    # Snapshot ringkas -- cukup untuk ditampilkan sebagai satu baris riwayat,
    # tidak menduplikasi seluruh baris anggaran (lines) budget itu sendiri.
    version_label: Mapped[str] = mapped_column(String(20), nullable=False)
    version_number: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    effective_date: Mapped[date] = mapped_column(nullable=False)

    # Jenis perubahan yang memicu snapshot ini, mis. "CREATE", "UPDATE",
    # "SUBMIT", "APPROVE", "REJECT", "REVISE", dst.
    change_type: Mapped[str] = mapped_column(String(30), nullable=False)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
