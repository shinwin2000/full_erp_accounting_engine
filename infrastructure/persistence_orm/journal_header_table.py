#!/usr/bin/env python3
"""
Module: journal_header_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel journal_header.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import (
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)

if TYPE_CHECKING:
    from infrastructure.persistence_orm.journal_line_table import JournalLineTable
    from infrastructure.persistence_orm.ledger_entry_table import LedgerEntryTable
    from infrastructure.persistence_orm.legal_entity_table import LegalEntityTable


class JournalHeaderTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin):
    __tablename__ = "journal_header"
    __table_args__ = (
        UniqueConstraint(
            "voucher_number", "legal_entity_id",
            name="uq_journal_header_voucher_legal_entity"
        ),
        CheckConstraint(
            "voucher_number IS NOT NULL AND voucher_number != ''",
            name="ck_journal_header_voucher"
        ),
        CheckConstraint(
            "description IS NOT NULL AND description != ''",
            name="ck_journal_header_description"
        ),
        CheckConstraint(
            "status IN ('draft', 'submitted', 'approved', 'posted', 'reversed', 'cancelled')",
            name="ck_journal_header_status",
        ),
        CheckConstraint("total_debit >= 0", name="ck_journal_header_debit_nonneg"),
        CheckConstraint("total_credit >= 0", name="ck_journal_header_credit_nonneg"),
        Index("idx_journal_header_voucher", "voucher_number"),
        Index("idx_journal_header_date", "journal_date"),
        Index("idx_journal_header_status", "status"),
        Index("idx_journal_header_legal_entity", "legal_entity_id"),
        Index("idx_journal_header_period", "period_id"),
        Index("idx_journal_header_source", "source_type", "source_id"),
        Index("idx_journal_header_created_by", "created_by"),
        Index("idx_journal_header_approved_by", "approved_by"),
        Index("idx_journal_header_posted_by", "posted_by"),
        {"extend_existing": True},
    )

    # Journal identification
    voucher_number: Mapped[str] = mapped_column(String(50), nullable=False)
    journal_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)

    # Financial totals
    total_debit: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    total_credit: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")

    # Status and workflow
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")

    # Approval (4-eyes principle)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Posting
    posted_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Reversal information
    reversed_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reversed_journal_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("journal_header.id", name="fk_journal_header_reversed_journal"),
        nullable=True,
        index=True,
    )
    original_journal_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("journal_header.id", name="fk_journal_header_original_journal"),
        nullable=True,
        index=True,
    )

    # Reference and source
    reference_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False, default="manual")
    source_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    # Period association (foreign key only – relationship removed to avoid mapper conflict)
    period_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("fiscal_period.id"), nullable=True
    )

    # Audit
    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    # ========================================================================
    # OVERRIDE legal_entity_id dari LegalEntityMixin agar menggunakan schema public
    # ========================================================================
    legal_entity_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("legal_entity.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ========================================================================
    # RELATIONSHIPS
    # ========================================================================

    # Legal Entity
    legal_entity: Mapped[LegalEntityTable] = relationship(
        "LegalEntityTable",
        back_populates="journals",
        foreign_keys=[legal_entity_id],
    )

    # Journal lines (one-to-many)
    lines: Mapped[list[JournalLineTable]] = relationship(
        "JournalLineTable",
        back_populates="journal",
        cascade="all, delete-orphan",
        order_by="JournalLineTable.line_number",
    )

    # Ledger entries (one-to-many, after posting)
    ledger_entries: Mapped[list[LedgerEntryTable]] = relationship(
        "LedgerEntryTable", back_populates="journal"
    )

    # Self-reference for reversal
    reversed_journal: Mapped[JournalHeaderTable | None] = relationship(
        "JournalHeaderTable",
        remote_side="JournalHeaderTable.id",
        foreign_keys=[reversed_journal_id],
        uselist=False,
    )
    original_journal: Mapped[JournalHeaderTable | None] = relationship(
        "JournalHeaderTable",
        remote_side="JournalHeaderTable.id",
        foreign_keys=[original_journal_id],
        uselist=False,
    )

    # PERIOD RELATIONSHIP REMOVED – hanya foreign key period_id yang tersisa.
    # Jika navigasi diperlukan di masa depan, tambahkan relasi dengan back_populates
    # setelah FiscalPeriodTable memiliki relasi 'journals'.

    # ========================================================================
    # PROPERTIES
    # ========================================================================

    @property
    def is_balanced(self) -> bool:
        return abs(self.total_debit - self.total_credit) < Decimal("0.01")

    @property
    def is_draft(self) -> bool:
        return self.status == "draft"

    @property
    def is_submitted(self) -> bool:
        return self.status == "submitted"

    @property
    def is_approved(self) -> bool:
        return self.status == "approved"

    @property
    def is_posted(self) -> bool:
        return self.status == "posted"

    @property
    def is_reversed(self) -> bool:
        return self.status == "reversed"

    @property
    def is_cancelled(self) -> bool:
        return self.status == "cancelled"

    @property
    def can_be_modified(self) -> bool:
        return self.status in ("draft", "submitted")

    @property
    def can_be_approved(self) -> bool:
        return self.status == "submitted"

    @property
    def can_be_posted(self) -> bool:
        return self.status == "approved" and self.is_balanced

    @property
    def can_be_reversed(self) -> bool:
        return self.status == "posted" and self.reversed_journal_id is None

    # ========================================================================
    # METHODS
    # ========================================================================

    def submit(self, submitted_by: uuid.UUID) -> None:
        if self.status != "draft":
            raise ValueError(f"Cannot submit journal with status {self.status}")
        self.status = "submitted"
        self.increment_version()

    def approve(self, approved_by: uuid.UUID) -> None:
        if self.status != "submitted":
            raise ValueError(f"Cannot approve journal with status {self.status}")
        self.status = "approved"
        self.approved_by = approved_by
        self.approved_at = datetime.utcnow()
        self.increment_version()

    def reject(self, rejected_by: uuid.UUID, reason: str | None = None) -> None:
        if self.status != "submitted":
            raise ValueError(f"Cannot reject journal with status {self.status}")
        self.status = "draft"
        self.increment_version()

    def post(self, posted_by: uuid.UUID) -> None:
        if self.status != "approved":
            raise ValueError(f"Cannot post journal with status {self.status}")
        if not self.is_balanced:
            raise ValueError("Cannot post unbalanced journal")
        self.status = "posted"
        self.posted_by = posted_by
        self.posted_at = datetime.utcnow()
        self.increment_version()

    def reverse(self, reversed_by: uuid.UUID, reversal_journal_id: uuid.UUID) -> None:
        if self.status != "posted":
            raise ValueError(f"Cannot reverse journal with status {self.status}")
        self.status = "reversed"
        self.reversed_by = reversed_by
        self.reversed_at = datetime.utcnow()
        self.reversed_journal_id = reversal_journal_id
        self.increment_version()

    def cancel(self, cancelled_by: uuid.UUID) -> None:
        if self.status not in ("draft", "submitted"):
            raise ValueError(f"Cannot cancel journal with status {self.status}")
        self.status = "cancelled"
        self.increment_version()


JournalHeaderReadModel = JournalHeaderTable

__all__ = ["JournalHeaderReadModel", "JournalHeaderTable"]
