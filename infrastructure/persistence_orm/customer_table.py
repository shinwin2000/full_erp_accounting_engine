#!/usr/bin/env python3
"""
Module: customer_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel customer.
               Tabel ini menyimpan data master customer/pelanggan, termasuk
               informasi kontak, limit kredit, status pajak, dan metadata.
               Digunakan oleh subledger AR, sales, dan collection.
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

    # Basic identification
    customer_code: Mapped[str] = mapped_column(String(30), nullable=False)
    customer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    customer_type: Mapped[str] = mapped_column(String(20), nullable=False, default="company")

    # Tax and registration
    tax_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    tax_id_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    tax_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pkp")
    registration_number: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Contact information
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    shipping_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    country: Mapped[str] = mapped_column(String(2), nullable=False, default="ID")
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    website: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Contact person
    contact_person: Mapped[str | None] = mapped_column(String(100), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Credit and payment terms
    credit_limit: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    used_credit: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    payment_term_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    discount_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=0)

    # Grouping and classification
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    price_group: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sales_person_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Banking
    bank_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bank_account_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    bank_account_name: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Status
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Date fields
    first_purchase_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_purchase_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    credit_check_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Additional metadata
    extra_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Audit
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # ========================================================================
    # RELATIONSHIPS
    # ========================================================================

    # AR Invoices
    ar_invoices: Mapped[list["ARInvoiceTable"]] = relationship(
        "ARInvoiceTable",
        back_populates="customer",
        cascade="all, delete-orphan",
    )

    # Sales Orders
    sales_orders: Mapped[list["SalesOrderTable"]] = relationship(
        "SalesOrderTable",
        back_populates="customer",
        cascade="all, delete-orphan",
    )

    # Retainer Contracts
    retainer_contracts: Mapped[list["RetainerContractTable"]] = relationship(
        "RetainerContractTable",
        back_populates="customer",
        cascade="all, delete-orphan",
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
        return self.status == "active" and self.is_active

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
            "customer_type": self.customer_type,
            "tax_id": self.tax_id,
            "tax_status": self.tax_status,
            "address": self.address,
            "city": self.city,
            "country": self.country,
            "phone": self.phone,
            "email": self.email,
            "contact_person": self.contact_person,
            "credit_limit": float(self.credit_limit),
            "used_credit": float(self.used_credit),
            "available_credit": float(self.available_credit),
            "payment_term_days": self.payment_term_days,
            "status": self.status,
            "is_active": self.is_active,
            "extra_metadata": self.extra_metadata,
            "legal_entity_id": str(self.legal_entity_id),
            "version": self.version,
        }


__all__ = ["CustomerTable"]