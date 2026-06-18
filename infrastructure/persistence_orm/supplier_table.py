#!/usr/bin/env python3
"""
Module: supplier_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel supplier.
               Tabel ini menyimpan data master supplier/vendor, termasuk
               informasi kontak, syarat pembayaran, status pajak, dan
               withholding tax category. Digunakan oleh subledger AP,
               procurement, dan payment.
Dependencies:
- sqlalchemy.orm (Mapped, mapped_column, relationship)
- sqlalchemy.dialects.postgresql (UUID, JSONB)
- infrastructure.persistence_orm.base_model (Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin)
Audit: Setiap perubahan data supplier dicatat di event store.
       Kategori withholding tax digunakan untuk perhitungan PPh 23/26.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import (
    Base,
    LegalEntityMixin,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)


class SupplierTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    """
    Model untuk tabel supplier.
    """

    __tablename__ = "supplier"
    __table_args__ = (
        UniqueConstraint("supplier_code", "legal_entity_id", name="uq_supplier_code_legal_entity"),
        UniqueConstraint("tax_id", name="uq_supplier_tax_id"),
        CheckConstraint(
            "supplier_code IS NOT NULL AND supplier_code != ''", name="ck_supplier_code"
        ),
        CheckConstraint(
            "supplier_name IS NOT NULL AND supplier_name != ''", name="ck_supplier_name"
        ),
        CheckConstraint(
            "supplier_type IN ('individual', 'company', 'government', 'non_profit')",
            name="ck_supplier_type",
        ),
        CheckConstraint(
            "status IN ('active', 'inactive', 'blocked', 'suspended')", name="ck_supplier_status"
        ),
        CheckConstraint(
            "withholding_category IN ('none', 'pph23', 'pph26', 'both')",
            name="ck_supplier_withholding",
        ),
        Index("idx_supplier_supplier_code", "supplier_code"),
        Index("idx_supplier_name", "supplier_name"),
        Index("idx_supplier_tax_id", "tax_id"),
        Index("idx_supplier_status", "status"),
        Index("idx_supplier_legal_entity", "legal_entity_id"),
        Index("idx_supplier_category", "category"),
        Index("idx_supplier_withholding", "withholding_category")
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Basic identification
    supplier_code: Mapped[str] = mapped_column(String(30), nullable=False)
    supplier_name: Mapped[str] = mapped_column(String(200), nullable=False)
    supplier_type: Mapped[str] = mapped_column(String(20), nullable=False, default="company")

    # Tax and registration
    tax_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    tax_id_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    tax_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pkp")
    registration_number: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Withholding tax (PPh 23/26)
    withholding_category: Mapped[str] = mapped_column(String(20), nullable=False, default="none")
    withholding_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    has_npwp: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Contact information
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    country: Mapped[str] = mapped_column(String(2), nullable=False, default="ID")
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    fax: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    website: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Contact person
    contact_person: Mapped[str | None] = mapped_column(String(100), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Payment terms and bank
    payment_term_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    discount_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    bank_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bank_account_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    bank_account_name: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Performance metrics
    lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    quality_rating: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=True, default=0)
    on_time_delivery_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=True, default=0)

    # Grouping and classification
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    procurement_category: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Status
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Date fields
    first_purchase_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_purchase_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_audit_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Additional metadata
    extra_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Audit
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # ========================================================================
    # RELATIONSHIPS
    # ========================================================================

    ap_invoices: Mapped[list[APInvoiceTable]] = relationship(
        "APInvoiceTable", back_populates="supplier"
    )
    ap_payments: Mapped[list[APPaymentTable]] = relationship(
        "APPaymentTable", back_populates="supplier"
    )
    purchase_orders: Mapped[list[PurchaseOrderTable]] = relationship(
        "PurchaseOrderTable", back_populates="supplier"
    )

    # ========================================================================
    # PROPERTIES
    # ========================================================================

    @property
    def effective_withholding_rate(self) -> Decimal:
        if self.withholding_category in ("pph23", "both"):
            return Decimal("2.0") if self.has_npwp else Decimal("4.0")
        elif self.withholding_category == "pph26":
            return Decimal("20.0")
        return Decimal("0")

    @property
    def is_active_supplier(self) -> bool:
        return self.status == "active" and self.is_active

    @property
    def is_blocked(self) -> bool:
        return self.status == "blocked"

    # ========================================================================
    # METHODS
    # ========================================================================

    def activate(self) -> None:
        self.status = "active"
        self.is_active = True
        self.blocked_reason = None
        self.increment_version()

    def deactivate(self) -> None:
        self.status = "inactive"
        self.is_active = False
        self.increment_version()

    def block(self, reason: str) -> None:
        self.status = "blocked"
        self.blocked_reason = reason
        self.increment_version()

    def record_purchase(self, purchase_date: date) -> None:
        self.last_purchase_date = purchase_date
        if self.first_purchase_date is None:
            self.first_purchase_date = purchase_date
        self.increment_version()

    def update_quality_rating(self, new_rating: Decimal) -> None:
        self.quality_rating = new_rating
        self.increment_version()

    def update_on_time_delivery(self, rate_percent: Decimal) -> None:
        self.on_time_delivery_rate = rate_percent
        self.increment_version()

    def can_create_po(self) -> bool:
        return self.is_active_supplier

    goods_receipt_notes: Mapped[list[GoodsReceiptNoteTable]] = relationship(
        "GoodsReceiptNoteTable", back_populates="supplier", cascade="all, delete-orphan"
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "supplier_code": self.supplier_code,
            "supplier_name": self.supplier_name,
            "supplier_type": self.supplier_type,
            "tax_id": self.tax_id,
            "tax_status": self.tax_status,
            "withholding_category": self.withholding_category,
            "withholding_rate": float(self.withholding_rate),
            "has_npwp": self.has_npwp,
            "effective_withholding_rate": float(self.effective_withholding_rate),
            "address": self.address,
            "city": self.city,
            "country": self.country,
            "phone": self.phone,
            "email": self.email,
            "contact_person": self.contact_person,
            "payment_term_days": self.payment_term_days,
            "discount_percent": float(self.discount_percent),
            "bank_name": self.bank_name,
            "bank_account_number": self.bank_account_number,
            "lead_time_days": self.lead_time_days,
            "quality_rating": float(self.quality_rating) if self.quality_rating else 0,
            "on_time_delivery_rate": float(self.on_time_delivery_rate)
            if self.on_time_delivery_rate
            else 0,
            "category": self.category,
            "status": self.status,
            "is_active": self.is_active,
            "extra_metadata": self.extra_metadata,
            "legal_entity_id": str(self.legal_entity_id),
            "version": self.version,
        }


__all__ = ["SupplierTable"]
