#!/usr/bin/env python3
"""
Module: customer_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Model SQLAlchemy untuk modul Customer skala ERP produksi.

    REFACTOR (lihat migrations/versions/0047_customer_master_data_full_refactor.py):
    Sebelumnya tabel `customer` cuma dipakai sekadar CRUD flat. Sekarang
    dipecah mengikuti normalisasi database ala ERP production supaya siap
    dipakai modul Penjualan, AR, Invoice, Pembayaran, Retur, Delivery Order,
    Laporan, dan General Ledger:

        customer                   - data utama (identitas, pajak, finance, status)
        customer_addresses         - banyak alamat per customer (billing/shipping/warehouse/other)
        customer_contacts          - banyak contact person (PIC) per customer
        customer_attachments       - dokumen pendukung (NPWP/SIUP/KTP/kontrak/foto)
        customer_notes             - catatan internal (histori, bukan 1 field bebas)
        customer_tags              - label/kategori bebas (Retail, VIP, Export, dst)
        customer_credit_history    - riwayat perubahan credit_limit (audit trail)
        customer_balance_history   - riwayat perubahan saldo piutang (audit trail)

    Semua tabel anak berelasi ke `customer` lewat customer_id (FK CASCADE),
    supaya query, backend (FastAPI), dan frontend (PySide6) sinkron 1:1.
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
    from infrastructure.persistence_orm.ar_invoice_table import ARInvoiceTable
    from infrastructure.persistence_orm.retainer_contract_table import RetainerContractTable
    from infrastructure.persistence_orm.sales_order_table import SalesOrderTable


# ============================================================================
# 1. CUSTOMER - Data Utama
# ============================================================================


class CustomerTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    __tablename__ = "customer"
    __table_args__ = (
        UniqueConstraint("customer_code", "legal_entity_id", name="uq_customer_code_legal_entity"),
        UniqueConstraint("tax_id", name="uq_customer_tax_id"),
        CheckConstraint(
            "customer_code IS NOT NULL AND customer_code != ''", name="ck_customer_code"
        ),
        CheckConstraint(
            "customer_name IS NOT NULL AND customer_name != ''", name="ck_customer_name"
        ),
        CheckConstraint(
            "customer_type IN ('individual', 'company', 'government', 'non_profit')",
            name="ck_customer_type",
        ),
        CheckConstraint(
            "status IN ('active', 'inactive', 'blocked', 'suspended')", name="ck_customer_status"
        ),
        Index("idx_customer_customer_code", "customer_code"),
        Index("idx_customer_name", "customer_name"),
        Index("idx_customer_tax_id", "tax_id"),
        Index("idx_customer_status", "status"),
        Index("idx_customer_legal_entity", "legal_entity_id"),
        Index("idx_customer_category", "category"),
        Index("idx_customer_sales_person", "sales_person_id"),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # ---- 1. Data Utama Customer -------------------------------------------
    customer_code: Mapped[str] = mapped_column(String(30), nullable=False)
    customer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    company_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    customer_type: Mapped[str] = mapped_column(String(20), nullable=False, default="company")

    # Tax and registration
    tax_id: Mapped[str | None] = mapped_column(String(20), nullable=True)  # NPWP
    tax_id_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    tax_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pkp")
    is_taxable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    registration_number: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # ---- 2. Alamat (kolom cepat/default; alamat lengkap di customer_addresses)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    shipping_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    province: Mapped[str | None] = mapped_column(String(100), nullable=True)
    district: Mapped[str | None] = mapped_column(String(100), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    country: Mapped[str] = mapped_column(String(2), nullable=False, default="ID")
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)

    # Contact information
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    mobile: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    website: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Contact person (ringkas; daftar lengkap PIC di customer_contacts)
    contact_person: Mapped[str | None] = mapped_column(String(100), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # ---- 3. Data Keuangan ---------------------------------------------------
    credit_limit: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    used_credit: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    opening_balance: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    current_balance: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")
    payment_term_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    discount_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=0)

    # Grouping and classification
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    price_group: Mapped[str | None] = mapped_column(String(50), nullable=True)  # price_level
    sales_person_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Banking
    bank_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bank_account_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    bank_account_name: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # ---- 4. Status ------------------------------------------------------------
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_blacklist: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Date fields
    first_purchase_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_purchase_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    credit_check_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Additional metadata
    extra_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Audit
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # ========================================================================
    # RELATIONSHIPS
    # ========================================================================

    ar_invoices: Mapped[list[ARInvoiceTable]] = relationship(
        "ARInvoiceTable", back_populates="customer", cascade="all, delete-orphan",
    )
    sales_orders: Mapped[list[SalesOrderTable]] = relationship(
        "SalesOrderTable", back_populates="customer", cascade="all, delete-orphan",
    )
    retainer_contracts: Mapped[list[RetainerContractTable]] = relationship(
        "RetainerContractTable", back_populates="customer", cascade="all, delete-orphan",
    )

    addresses: Mapped[list[CustomerAddressTable]] = relationship(
        "CustomerAddressTable", back_populates="customer",
        cascade="all, delete-orphan", order_by="CustomerAddressTable.created_at",
    )
    contacts: Mapped[list[CustomerContactTable]] = relationship(
        "CustomerContactTable", back_populates="customer",
        cascade="all, delete-orphan", order_by="CustomerContactTable.created_at",
    )
    attachments: Mapped[list[CustomerAttachmentTable]] = relationship(
        "CustomerAttachmentTable", back_populates="customer",
        cascade="all, delete-orphan", order_by="CustomerAttachmentTable.created_at",
    )
    notes: Mapped[list[CustomerNoteTable]] = relationship(
        "CustomerNoteTable", back_populates="customer",
        cascade="all, delete-orphan", order_by="CustomerNoteTable.created_at.desc()",
    )
    tags: Mapped[list[CustomerTagTable]] = relationship(
        "CustomerTagTable", back_populates="customer", cascade="all, delete-orphan",
    )
    credit_history: Mapped[list[CustomerCreditHistoryTable]] = relationship(
        "CustomerCreditHistoryTable", back_populates="customer",
        cascade="all, delete-orphan", order_by="CustomerCreditHistoryTable.created_at.desc()",
    )
    balance_history: Mapped[list[CustomerBalanceHistoryTable]] = relationship(
        "CustomerBalanceHistoryTable", back_populates="customer",
        cascade="all, delete-orphan", order_by="CustomerBalanceHistoryTable.created_at.desc()",
    )

    # ========================================================================
    # PROPERTIES
    # ========================================================================

    @property
    def available_credit(self) -> Decimal:
        return max(Decimal(0), self.credit_limit - self.used_credit)

    @property
    def is_credit_exceeded(self) -> bool:
        return self.used_credit > self.credit_limit

    @property
    def is_blocked(self) -> bool:
        return self.status == "blocked"

    @property
    def is_active_customer(self) -> bool:
        return self.status == "active" and self.is_active and not self.is_blacklist

    @property
    def credit_utilization_percent(self) -> Decimal:
        if self.credit_limit == 0:
            return Decimal(0)
        return (self.used_credit / self.credit_limit) * Decimal(100)

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

    def update_credit_usage(self, amount: Decimal) -> None:
        self.used_credit += amount
        self.increment_version()

    def reset_credit_usage(self) -> None:
        self.used_credit = Decimal(0)
        self.increment_version()

    def record_purchase(self, purchase_date: date, amount: Decimal) -> None:
        self.last_purchase_date = purchase_date
        if self.first_purchase_date is None:
            self.first_purchase_date = purchase_date
        self.update_credit_usage(amount)
        self.increment_version()

    def can_create_invoice(self, invoice_amount: Decimal) -> bool:
        if not self.is_active_customer:
            return False
        if self.credit_limit > 0:
            return (self.used_credit + invoice_amount) <= self.credit_limit
        return True

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "customer_code": self.customer_code,
            "customer_name": self.customer_name,
            "company_name": self.company_name,
            "customer_type": self.customer_type,
            "tax_id": self.tax_id,
            "tax_status": self.tax_status,
            "is_taxable": self.is_taxable,
            "address": self.address,
            "city": self.city,
            "province": self.province,
            "district": self.district,
            "country": self.country,
            "phone": self.phone,
            "mobile": self.mobile,
            "email": self.email,
            "contact_person": self.contact_person,
            "credit_limit": float(self.credit_limit),
            "used_credit": float(self.used_credit),
            "available_credit": float(self.available_credit),
            "opening_balance": float(self.opening_balance),
            "current_balance": float(self.current_balance),
            "currency": self.currency,
            "payment_term_days": self.payment_term_days,
            "price_group": self.price_group,
            "status": self.status,
            "is_active": self.is_active,
            "is_blacklist": self.is_blacklist,
            "extra_metadata": self.extra_metadata,
            "legal_entity_id": str(self.legal_entity_id),
            "version": self.version,
        }


# ============================================================================
# 2. CUSTOMER ADDRESSES - banyak alamat per customer
# ============================================================================


class CustomerAddressTable(Base, TimestampMixin, SoftDeleteMixin):
    """Alamat billing / shipping / warehouse / lainnya, banyak per customer."""

    __tablename__ = "customer_addresses"
    __table_args__ = (
        CheckConstraint(
            "address_type IN ('billing', 'shipping', 'warehouse', 'other')",
            name="ck_customer_address_type",
        ),
        Index("idx_customer_address_customer_id", "customer_id"),
        Index("idx_customer_address_type", "address_type"),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer.id", ondelete="CASCADE"), nullable=False
    )

    address_type: Mapped[str] = mapped_column(String(20), nullable=False, default="other")
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

    customer: Mapped[CustomerTable] = relationship("CustomerTable", back_populates="addresses")

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "customer_id": str(self.customer_id),
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


# ============================================================================
# 3. CUSTOMER CONTACTS - banyak PIC per customer
# ============================================================================


class CustomerContactTable(Base, TimestampMixin, SoftDeleteMixin):
    """Contact person / PIC. Satu customer bisa punya banyak PIC."""

    __tablename__ = "customer_contacts"
    __table_args__ = (
        Index("idx_customer_contact_customer_id", "customer_id"),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer.id", ondelete="CASCADE"), nullable=False
    )

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    position: Mapped[str | None] = mapped_column(String(100), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    mobile: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    whatsapp: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    customer: Mapped[CustomerTable] = relationship("CustomerTable", back_populates="contacts")

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "customer_id": str(self.customer_id),
            "name": self.name,
            "position": self.position,
            "phone": self.phone,
            "mobile": self.mobile,
            "email": self.email,
            "whatsapp": self.whatsapp,
            "is_primary": self.is_primary,
        }


# ============================================================================
# 4. CUSTOMER ATTACHMENTS - dokumen pendukung
# ============================================================================


class CustomerAttachmentTable(Base, TimestampMixin, SoftDeleteMixin):
    """Dokumen pendukung: NPWP, SIUP, KTP, kontrak, foto, dll."""

    __tablename__ = "customer_attachments"
    __table_args__ = (
        Index("idx_customer_attachment_customer_id", "customer_id"),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer.id", ondelete="CASCADE"), nullable=False
    )

    document_type: Mapped[str] = mapped_column(String(30), nullable=False, default="other")
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    customer: Mapped[CustomerTable] = relationship("CustomerTable", back_populates="attachments")

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "customer_id": str(self.customer_id),
            "document_type": self.document_type,
            "file_name": self.file_name,
            "file_path": self.file_path,
            "file_size_bytes": self.file_size_bytes,
            "mime_type": self.mime_type,
            "notes": self.notes,
            "uploaded_by": str(self.uploaded_by) if self.uploaded_by else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ============================================================================
# 5. CUSTOMER NOTES - catatan internal
# ============================================================================


class CustomerNoteTable(Base, TimestampMixin):
    """Catatan internal berhistori (bukan satu field bebas yang tertimpa)."""

    __tablename__ = "customer_notes"
    __table_args__ = (
        Index("idx_customer_note_customer_id", "customer_id"),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer.id", ondelete="CASCADE"), nullable=False
    )

    note: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    customer: Mapped[CustomerTable] = relationship("CustomerTable", back_populates="notes")

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "customer_id": str(self.customer_id),
            "note": self.note,
            "created_by": str(self.created_by) if self.created_by else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ============================================================================
# 6. CUSTOMER TAGS - label/kategori bebas
# ============================================================================


class CustomerTagTable(Base, TimestampMixin):
    """Tag/label bebas: Retail, Distributor, VIP, Export, dst."""

    __tablename__ = "customer_tags"
    __table_args__ = (
        UniqueConstraint("customer_id", "tag", name="uq_customer_tag"),
        Index("idx_customer_tag_customer_id", "customer_id"),
        Index("idx_customer_tag_value", "tag"),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer.id", ondelete="CASCADE"), nullable=False
    )
    tag: Mapped[str] = mapped_column(String(50), nullable=False)

    customer: Mapped[CustomerTable] = relationship("CustomerTable", back_populates="tags")

    def to_dict(self) -> dict:
        return {"id": str(self.id), "customer_id": str(self.customer_id), "tag": self.tag}


# ============================================================================
# 7. CUSTOMER CREDIT HISTORY - riwayat perubahan limit kredit
# ============================================================================


class CustomerCreditHistoryTable(Base, TimestampMixin):
    """Audit trail setiap perubahan credit_limit. Immutable (append-only)."""

    __is_audit_log__ = True

    __tablename__ = "customer_credit_history"
    __table_args__ = (
        Index("idx_customer_credit_history_customer_id", "customer_id"),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer.id", ondelete="CASCADE"), nullable=False
    )

    old_limit: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    new_limit: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    customer: Mapped[CustomerTable] = relationship("CustomerTable", back_populates="credit_history")

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "customer_id": str(self.customer_id),
            "old_limit": float(self.old_limit),
            "new_limit": float(self.new_limit),
            "reason": self.reason,
            "changed_by": str(self.changed_by) if self.changed_by else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ============================================================================
# 8. CUSTOMER BALANCE HISTORY - riwayat perubahan saldo piutang
# ============================================================================


class CustomerBalanceHistoryTable(Base, TimestampMixin):
    """Audit trail setiap perubahan saldo piutang. Immutable (append-only)."""

    __is_audit_log__ = True

    __tablename__ = "customer_balance_history"
    __table_args__ = (
        Index("idx_customer_balance_history_customer_id", "customer_id"),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer.id", ondelete="CASCADE"), nullable=False
    )

    old_balance: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    new_balance: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    delta: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    source: Mapped[str | None] = mapped_column(String(50), nullable=True)  # invoice/payment/return/manual
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    customer: Mapped[CustomerTable] = relationship("CustomerTable", back_populates="balance_history")

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "customer_id": str(self.customer_id),
            "old_balance": float(self.old_balance),
            "new_balance": float(self.new_balance),
            "delta": float(self.delta),
            "source": self.source,
            "reference": self.reference,
            "changed_by": str(self.changed_by) if self.changed_by else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


__all__ = [
    "CustomerAddressTable",
    "CustomerAttachmentTable",
    "CustomerBalanceHistoryTable",
    "CustomerContactTable",
    "CustomerCreditHistoryTable",
    "CustomerNoteTable",
    "CustomerTable",
    "CustomerTagTable",
]
