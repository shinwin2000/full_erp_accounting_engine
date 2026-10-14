#!/usr/bin/env python3
"""
Module: supplier_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Model SQLAlchemy untuk tabel supplier + 5 tabel anak.

Tabel utama:
    supplier                    (dari migrasi 0006 + 0047)

Tabel anak:
    supplier_attachments        (migrasi 0050)
    supplier_notes              (migrasi 0050)
    supplier_addresses          (migrasi 0051)
    supplier_contacts           (migrasi 0051)
    supplier_tags               (migrasi 0051)
    supplier_credit_history     (migrasi 0051, immutable)
    supplier_balance_history    (migrasi 0051, immutable)
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
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

if TYPE_CHECKING:
    from infrastructure.persistence_orm.ap_invoice_table import APInvoiceTable
    from infrastructure.persistence_orm.ap_payment_table import APPaymentTable
    from infrastructure.persistence_orm.goods_receipt_note_table import (
        GoodsReceiptNoteTable,
    )
    from infrastructure.persistence_orm.purchase_order_table import (
        PurchaseOrderTable,
    )


# ============================================================================
# TABEL UTAMA
# ============================================================================


class SupplierTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    """Model untuk tabel supplier."""

    __tablename__ = "supplier"
    __table_args__ = (
        UniqueConstraint(
            "supplier_code", "legal_entity_id", name="uq_supplier_code_legal_entity"
        ),
        UniqueConstraint("tax_id", name="uq_supplier_tax_id"),
        CheckConstraint(
            "supplier_code IS NOT NULL AND supplier_code != ''",
            name="ck_supplier_code",
        ),
        CheckConstraint(
            "supplier_name IS NOT NULL AND supplier_name != ''",
            name="ck_supplier_name",
        ),
        CheckConstraint(
            "supplier_type IN ('individual', 'company', 'government', 'non_profit')",
            name="ck_supplier_type",
        ),
        CheckConstraint(
            "status IN ('active', 'inactive', 'blocked', 'suspended', "
            "'blacklisted', 'draft')",
            name="ck_supplier_status",
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
        Index("idx_supplier_withholding", "withholding_category"),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Basic identification
    supplier_code: Mapped[str] = mapped_column(String(30), nullable=False)
    supplier_name: Mapped[str] = mapped_column(String(200), nullable=False)
    company_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    supplier_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="company"
    )

    # Tax and registration
    tax_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    tax_id_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    tax_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    tax_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pkp")
    registration_number: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Withholding tax (PPh 23/26)
    withholding_category: Mapped[str] = mapped_column(
        String(20), nullable=False, default="none"
    )
    withholding_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=0
    )
    has_npwp: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Contact information
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    province: Mapped[str | None] = mapped_column(String(100), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    country: Mapped[str] = mapped_column(String(2), nullable=False, default="ID")
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    mobile: Mapped[str | None] = mapped_column(String(20), nullable=True)
    fax: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    website: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Contact person
    contact_person: Mapped[str | None] = mapped_column(String(100), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Payment terms, credit and bank
    payment_term_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    discount_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=0
    )
    credit_limit: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, default=0
    )
    opening_balance: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, default=0
    )
    opening_balance_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    bank_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bank_account_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    bank_account_name: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Performance metrics
    lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    quality_rating: Mapped[Decimal] = mapped_column(
        Numeric(3, 2), nullable=True, default=0
    )
    on_time_delivery_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=True, default=0
    )

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
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Audit
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    # ========================================================================
    # RELATIONSHIPS
    # ========================================================================

    ap_invoices: Mapped[list["APInvoiceTable"]] = relationship(
        "APInvoiceTable",
        back_populates="supplier",
        cascade="all, delete-orphan",
        foreign_keys="[APInvoiceTable.vendor_id]",
    )

    ap_payments: Mapped[list["APPaymentTable"]] = relationship(
        "APPaymentTable",
        back_populates="supplier",
        cascade="all, delete-orphan",
        foreign_keys="[APPaymentTable.supplier_id]",
    )

    purchase_orders: Mapped[list["PurchaseOrderTable"]] = relationship(
        "PurchaseOrderTable",
        back_populates="supplier",
        cascade="all, delete-orphan",
        foreign_keys="[PurchaseOrderTable.supplier_id]",
    )

    goods_receipt_notes: Mapped[list["GoodsReceiptNoteTable"]] = relationship(
        "GoodsReceiptNoteTable",
        back_populates="supplier",
        cascade="all, delete-orphan",
        foreign_keys="[GoodsReceiptNoteTable.supplier_id]",
    )

    attachments: Mapped[list["SupplierAttachmentTable"]] = relationship(
        "SupplierAttachmentTable",
        back_populates="supplier",
        cascade="all, delete-orphan",
        order_by="SupplierAttachmentTable.created_at",
    )
    notes: Mapped[list["SupplierNoteTable"]] = relationship(
        "SupplierNoteTable",
        back_populates="supplier",
        cascade="all, delete-orphan",
        order_by="SupplierNoteTable.created_at.desc()",
    )
    addresses: Mapped[list["SupplierAddressTable"]] = relationship(
        "SupplierAddressTable",
        back_populates="supplier",
        cascade="all, delete-orphan",
        order_by="SupplierAddressTable.created_at",
    )
    contacts: Mapped[list["SupplierContactTable"]] = relationship(
        "SupplierContactTable",
        back_populates="supplier",
        cascade="all, delete-orphan",
        order_by="SupplierContactTable.created_at",
    )
    tags: Mapped[list["SupplierTagTable"]] = relationship(
        "SupplierTagTable",
        back_populates="supplier",
        cascade="all, delete-orphan",
    )
    credit_history: Mapped[list["SupplierCreditHistoryTable"]] = relationship(
        "SupplierCreditHistoryTable",
        back_populates="supplier",
        cascade="all, delete-orphan",
        order_by="SupplierCreditHistoryTable.created_at.desc()",
    )
    balance_history: Mapped[list["SupplierBalanceHistoryTable"]] = relationship(
        "SupplierBalanceHistoryTable",
        back_populates="supplier",
        cascade="all, delete-orphan",
        order_by="SupplierBalanceHistoryTable.created_at.desc()",
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

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "supplier_code": self.supplier_code,
            "supplier_name": self.supplier_name,
            "company_name": self.company_name,
            "supplier_type": self.supplier_type,
            "tax_id": self.tax_id,
            "tax_name": self.tax_name,
            "tax_status": self.tax_status,
            "registration_number": self.registration_number,
            "withholding_category": self.withholding_category,
            "withholding_rate": float(self.withholding_rate),
            "has_npwp": self.has_npwp,
            "effective_withholding_rate": float(self.effective_withholding_rate),
            "address": self.address,
            "city": self.city,
            "province": self.province,
            "postal_code": self.postal_code,
            "country": self.country,
            "phone": self.phone,
            "mobile": self.mobile,
            "fax": self.fax,
            "email": self.email,
            "website": self.website,
            "contact_person": self.contact_person,
            "contact_phone": self.contact_phone,
            "contact_email": self.contact_email,
            "payment_term_days": self.payment_term_days,
            "discount_percent": float(self.discount_percent),
            "credit_limit": float(self.credit_limit),
            "opening_balance": float(self.opening_balance),
            "opening_balance_date": self.opening_balance_date.isoformat()
            if self.opening_balance_date
            else None,
            "bank_name": self.bank_name,
            "bank_account_number": self.bank_account_number,
            "bank_account_name": self.bank_account_name,
            "lead_time_days": self.lead_time_days,
            "quality_rating": float(self.quality_rating) if self.quality_rating else 0,
            "on_time_delivery_rate": float(self.on_time_delivery_rate)
            if self.on_time_delivery_rate
            else 0,
            "category": self.category,
            "procurement_category": self.procurement_category,
            "status": self.status,
            "is_active": self.is_active,
            "blocked_reason": self.blocked_reason,
            "first_purchase_date": self.first_purchase_date.isoformat()
            if self.first_purchase_date
            else None,
            "last_purchase_date": self.last_purchase_date.isoformat()
            if self.last_purchase_date
            else None,
            "remarks": self.remarks,
            "extra_metadata": self.extra_metadata,
            "legal_entity_id": str(self.legal_entity_id),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "created_by": str(self.created_by) if self.created_by else None,
            "version": self.version,
        }


# ============================================================================
# TABEL ANAK
# ============================================================================


class SupplierAttachmentTable(Base, TimestampMixin, SoftDeleteMixin):
    """Dokumen pendukung: NPWP, SIUP, KTP, kontrak, foto, dll."""

    __tablename__ = "supplier_attachments"
    __table_args__ = (
        Index("idx_supplier_attachment_supplier_id", "supplier_id"),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("supplier.id", ondelete="CASCADE"),
        nullable=False,
    )
    document_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default="other"
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    supplier: Mapped["SupplierTable"] = relationship(
        "SupplierTable", back_populates="attachments"
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "supplier_id": str(self.supplier_id),
            "document_type": self.document_type,
            "file_name": self.file_name,
            "file_path": self.file_path,
            "file_size_bytes": self.file_size_bytes,
            "mime_type": self.mime_type,
            "notes": self.notes,
            "uploaded_by": str(self.uploaded_by) if self.uploaded_by else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class SupplierNoteTable(Base, TimestampMixin):
    """Catatan internal berhistori."""

    __tablename__ = "supplier_notes"
    __table_args__ = (
        Index("idx_supplier_note_supplier_id", "supplier_id"),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("supplier.id", ondelete="CASCADE"),
        nullable=False,
    )
    note: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    supplier: Mapped["SupplierTable"] = relationship(
        "SupplierTable", back_populates="notes"
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "supplier_id": str(self.supplier_id),
            "note": self.note,
            "created_by": str(self.created_by) if self.created_by else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class SupplierAddressTable(Base, TimestampMixin, SoftDeleteMixin):
    """Alamat billing/shipping/warehouse/lainnya, banyak per supplier."""

    __tablename__ = "supplier_addresses"
    __table_args__ = (
        CheckConstraint(
            "address_type IN ('billing', 'shipping', 'warehouse', 'other')",
            name="ck_supplier_address_type",
        ),
        Index("idx_supplier_address_supplier_id", "supplier_id"),
        Index("idx_supplier_address_type", "address_type"),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("supplier.id", ondelete="CASCADE"),
        nullable=False,
    )
    address_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="other"
    )
    label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    address_line: Mapped[str] = mapped_column(Text, nullable=False)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    province: Mapped[str | None] = mapped_column(String(100), nullable=True)
    district: Mapped[str | None] = mapped_column(String(100), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    country: Mapped[str] = mapped_column(String(2), nullable=False, default="ID")
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    supplier: Mapped["SupplierTable"] = relationship(
        "SupplierTable", back_populates="addresses"
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "supplier_id": str(self.supplier_id),
            "address_type": self.address_type,
            "label": self.label,
            "address_line": self.address_line,
            "city": self.city,
            "province": self.province,
            "district": self.district,
            "postal_code": self.postal_code,
            "country": self.country,
            "latitude": float(self.latitude) if self.latitude is not None else None,
            "longitude": float(self.longitude) if self.longitude is not None else None,
            "is_primary": self.is_primary,
        }


class SupplierContactTable(Base, TimestampMixin, SoftDeleteMixin):
    """Contact person / PIC. Satu supplier bisa punya banyak PIC."""

    __tablename__ = "supplier_contacts"
    __table_args__ = (
        Index("idx_supplier_contact_supplier_id", "supplier_id"),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("supplier.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    position: Mapped[str | None] = mapped_column(String(100), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    mobile: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    whatsapp: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    supplier: Mapped["SupplierTable"] = relationship(
        "SupplierTable", back_populates="contacts"
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "supplier_id": str(self.supplier_id),
            "name": self.name,
            "position": self.position,
            "phone": self.phone,
            "mobile": self.mobile,
            "email": self.email,
            "whatsapp": self.whatsapp,
            "is_primary": self.is_primary,
        }


class SupplierTagTable(Base, TimestampMixin):
    """Tag/label bebas: Retail, Distributor, VIP, Import, dll."""

    __tablename__ = "supplier_tags"
    __table_args__ = (
        UniqueConstraint("supplier_id", "tag", name="uq_supplier_tag"),
        Index("idx_supplier_tag_supplier_id", "supplier_id"),
        Index("idx_supplier_tag_value", "tag"),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("supplier.id", ondelete="CASCADE"),
        nullable=False,
    )
    tag: Mapped[str] = mapped_column(String(50), nullable=False)

    supplier: Mapped["SupplierTable"] = relationship(
        "SupplierTable", back_populates="tags"
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "supplier_id": str(self.supplier_id),
            "tag": self.tag,
        }


class SupplierCreditHistoryTable(Base, TimestampMixin):
    """Audit trail setiap perubahan credit_limit. Immutable (append-only)."""

    __is_audit_log__ = True

    __tablename__ = "supplier_credit_history"
    __table_args__ = (
        Index("idx_supplier_credit_history_supplier_id", "supplier_id"),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("supplier.id", ondelete="CASCADE"),
        nullable=False,
    )
    old_limit: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    new_limit: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    supplier: Mapped["SupplierTable"] = relationship(
        "SupplierTable", back_populates="credit_history"
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "supplier_id": str(self.supplier_id),
            "old_limit": float(self.old_limit),
            "new_limit": float(self.new_limit),
            "reason": self.reason,
            "changed_by": str(self.changed_by) if self.changed_by else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class SupplierBalanceHistoryTable(Base, TimestampMixin):
    """Audit trail setiap perubahan AP balance. Immutable (append-only)."""

    __is_audit_log__ = True

    __tablename__ = "supplier_balance_history"
    __table_args__ = (
        Index("idx_supplier_balance_history_supplier_id", "supplier_id"),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("supplier.id", ondelete="CASCADE"),
        nullable=False,
    )
    old_balance: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    new_balance: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    delta: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    supplier: Mapped["SupplierTable"] = relationship(
        "SupplierTable", back_populates="balance_history"
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "supplier_id": str(self.supplier_id),
            "old_balance": float(self.old_balance),
            "new_balance": float(self.new_balance),
            "delta": float(self.delta),
            "source": self.source,
            "reference": self.reference,
            "changed_by": str(self.changed_by) if self.changed_by else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


__all__ = [
    "SupplierAddressTable",
    "SupplierAttachmentTable",
    "SupplierBalanceHistoryTable",
    "SupplierContactTable",
    "SupplierCreditHistoryTable",
    "SupplierNoteTable",
    "SupplierTable",
    "SupplierTagTable",
]
