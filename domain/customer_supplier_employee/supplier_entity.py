#!/usr/bin/env python3
"""
Module: supplier_entity.py

Layer: Domain / Customer, Supplier, Employee

Responsibility:
    Supplier entity representing a vendor that provides goods or services.
    Contains contact information, tax status, withholding category,
    payment terms, and purchase history.

Business rules:
    - Supplier code must be unique across legal entity.
    - Tax ID (NPWP) must be unique (if provided and validated).
    - Payment terms must be non-negative (reasonable max 180 days).
    - Withholding category determines tax calculation.
    - Outstanding balance cannot be negative.
    - Status transitions: ACTIVE → INACTIVE/BLOCKED/SUSPENDED, etc.
    - Version increments on every change (optimistic locking).

Dependencies:
    - Python standard library (uuid, datetime, decimal, logging, re)
    - domain.customer_supplier_employee.supplier_withholding_category_vo

Audit:
    Every state change should be logged; domain events should be emitted separately.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from domain.customer_supplier_employee.supplier_withholding_category_vo import (
    SupplierWithholdingCategoryVO,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class SupplierStatus(Enum):
    """Status of a supplier in the system."""

    ACTIVE = "active"  # Normal operational status
    INACTIVE = "inactive"  # Disabled, no new transactions
    BLOCKED = "blocked"  # Temporarily blocked
    SUSPENDED = "suspended"  # Suspended pending review
    BLACKLISTED = "blacklisted"  # Permanently banned
    DRAFT = "draft"  # Not yet activated

    def can_transact(self) -> bool:
        """Can we create purchase orders/invoices with this supplier?"""
        return self == SupplierStatus.ACTIVE

    def can_receive_payment(self) -> bool:
        """Can we record payments to this supplier?"""
        return self in (SupplierStatus.ACTIVE, SupplierStatus.BLOCKED, SupplierStatus.SUSPENDED)

    def can_modify(self) -> bool:
        """Can we modify supplier's master data?"""
        return self != SupplierStatus.BLACKLISTED

    def display_name(self) -> str:
        names = {
            SupplierStatus.ACTIVE: "Aktif",
            SupplierStatus.INACTIVE: "Tidak Aktif",
            SupplierStatus.BLOCKED: "Diblokir",
            SupplierStatus.SUSPENDED: "Ditangguhkan",
            SupplierStatus.BLACKLISTED: "Blacklist",
            SupplierStatus.DRAFT: "Draft",
        }
        return names.get(self, self.value)

    @classmethod
    def from_string(cls, value: str) -> SupplierStatus | None:
        for status in cls:
            if status.value == value.lower():
                return status
        return None


class SupplierType(Enum):
    """Type of supplier."""

    LOCAL = "local"  # Domestic
    FOREIGN = "foreign"  # Foreign
    GOVERNMENT = "government"  # Government institution
    INDIVIDUAL = "individual"  # Individual person
    MANUFACTURER = "manufacturer"
    DISTRIBUTOR = "distributor"
    SERVICE_PROVIDER = "service_provider"

    def display_name(self) -> str:
        names = {
            SupplierType.LOCAL: "Lokal",
            SupplierType.FOREIGN: "Luar Negeri",
            SupplierType.GOVERNMENT: "Instansi Pemerintah",
            SupplierType.INDIVIDUAL: "Perorangan",
            SupplierType.MANUFACTURER: "Pabrikan",
            SupplierType.DISTRIBUTOR: "Distributor",
            SupplierType.SERVICE_PROVIDER: "Penyedia Jasa",
        }
        return names.get(self, self.value)

    def requires_withholding(self) -> bool:
        """Does this supplier type require tax withholding?"""
        return self not in (SupplierType.GOVERNMENT, SupplierType.FOREIGN)  # Simplified

    @classmethod
    def from_string(cls, value: str) -> SupplierType | None:
        for typ in cls:
            if typ.value == value.lower():
                return typ
        return None


# ============================================================================
# Helper Functions
# ============================================================================


def _validate_email(email: str | None) -> str | None:
    if email is None:
        return None
    email_clean = email.strip().lower()
    if not email_clean:
        return None
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    if not re.match(pattern, email_clean):
        raise ValueError(f"Invalid email format: {email}")
    return email_clean


def _validate_phone(phone: str | None) -> str | None:
    if phone is None:
        return None
    phone_clean = re.sub(r"[\s\-\(\)]", "", phone)
    if not phone_clean:
        return None
    if not phone_clean.isdigit():
        raise ValueError(f"Phone number must contain only digits, got {phone}")
    if len(phone_clean) < 8 or len(phone_clean) > 15:
        raise ValueError(f"Phone number must be 8-15 digits, got {len(phone_clean)}")
    return phone_clean


def _validate_tax_id(tax_id: str | None) -> str | None:
    if tax_id is None:
        return None
    cleaned = re.sub(r"[^\d]", "", tax_id)
    if len(cleaned) != 15:
        raise ValueError(f"Tax ID must be 15 digits, got {len(cleaned)}")
    if not cleaned.isdigit():
        raise ValueError(f"Tax ID must contain only digits, got {tax_id}")
    return cleaned


def _validate_postal_code(code: str | None) -> str | None:
    if code is None:
        return None
    code_clean = code.strip()
    if not code_clean:
        return None
    if not code_clean.isdigit():
        raise ValueError(f"Postal code must contain only digits, got {code}")
    if len(code_clean) != 5:
        raise ValueError(f"Postal code must be 5 digits, got {len(code_clean)}")
    return code_clean


def _validate_payment_terms(days: int) -> None:
    if days < 0:
        raise ValueError(f"Payment terms days cannot be negative: {days}")
    if days > 360:
        raise ValueError(f"Payment terms days exceed maximum (360): {days}")


# ============================================================================
# Supplier Entity
# ============================================================================


@dataclass
class SupplierEntity:
    """
    Supplier entity representing a vendor.

    Attributes:
        supplier_id: Unique identifier
        legal_entity_id: Legal entity that manages this supplier
        supplier_code: Unique supplier code (e.g., 'SUP-001')
        supplier_name: Legal name of supplier
        supplier_type: Type of supplier
        status: Current status
        tax_id: NPWP (Tax ID)
        email: Email address
        phone: Phone number
        fax: Fax number
        contact_person: Primary contact person name
        address: Street address
        address2: Second address line
        city: City
        province: Province
        postal_code: Postal code
        country: Country (default 'Indonesia')
        bank_name: Bank name
        bank_account_number: Bank account number
        bank_account_name: Account holder name
        withholding_category: PPh withholding category
        payment_terms_days: Standard payment term in days
        outstanding_balance: Current payable balance
        total_purchases: Lifetime purchase amount
        last_purchase_date: Date of last purchase
        last_payment_date: Date of last payment
        notes: Internal notes
        created_at, updated_at, created_by, updated_by, version
    """

    # ========== Mandatory Fields ==========
    supplier_id: UUID
    legal_entity_id: UUID
    supplier_code: str
    supplier_name: str
    supplier_type: SupplierType

    # ========== Optional Fields with Defaults ==========
    status: SupplierStatus = SupplierStatus.ACTIVE
    tax_id: str | None = None
    email: str | None = None
    phone: str | None = None
    fax: str | None = None
    contact_person: str | None = None
    address: str | None = None
    address2: str | None = None
    city: str | None = None
    province: str | None = None
    postal_code: str | None = None
    country: str = "Indonesia"
    bank_name: str | None = None
    bank_account_number: str | None = None
    bank_account_name: str | None = None
    withholding_category: SupplierWithholdingCategoryVO = field(
        default_factory=SupplierWithholdingCategoryVO.create_none
    )
    payment_terms_days: int = 30
    outstanding_balance: Decimal = Decimal("0")
    total_purchases: Decimal = Decimal("0")
    last_purchase_date: date | None = None
    last_payment_date: date | None = None
    notes: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    updated_by: str = "system"
    version: int = 1

    def __post_init__(self) -> None:
        """Validate supplier data."""
        # Validate supplier code
        if not self.supplier_code or not isinstance(self.supplier_code, str):
            raise ValueError("Supplier code must be a non-empty string")
        code_clean = self.supplier_code.strip()
        if len(code_clean) < 2:
            raise ValueError("Supplier code must be at least 2 characters")
        if len(code_clean) > 30:
            raise ValueError("Supplier code must not exceed 30 characters")
        if not re.match(r"^[A-Za-z0-9\-_]+$", code_clean):
            raise ValueError(
                "Supplier code can only contain letters, numbers, hyphens, and underscores"
            )
        object.__setattr__(self, "supplier_code", code_clean)

        # Validate supplier name
        if not self.supplier_name or not isinstance(self.supplier_name, str):
            raise ValueError("Supplier name must be a non-empty string")
        name_clean = self.supplier_name.strip()
        if len(name_clean) < 2:
            raise ValueError("Supplier name must be at least 2 characters")
        if len(name_clean) > 200:
            raise ValueError("Supplier name must not exceed 200 characters")
        object.__setattr__(self, "supplier_name", name_clean)

        # Validate supplier_type
        if not isinstance(self.supplier_type, SupplierType):
            raise ValueError(f"Invalid supplier_type: {self.supplier_type}")

        # Validate status
        if not isinstance(self.status, SupplierStatus):
            raise ValueError(f"Invalid status: {self.status}")

        # Validate tax_id
        if self.tax_id:
            object.__setattr__(self, "tax_id", _validate_tax_id(self.tax_id))

        # Validate email
        if self.email:
            object.__setattr__(self, "email", _validate_email(self.email))

        # Validate phone
        if self.phone:
            object.__setattr__(self, "phone", _validate_phone(self.phone))
        if self.fax:
            object.__setattr__(self, "fax", _validate_phone(self.fax))

        # Validate postal_code
        if self.postal_code:
            object.__setattr__(self, "postal_code", _validate_postal_code(self.postal_code))

        # Validate payment_terms
        _validate_payment_terms(self.payment_terms_days)

        # Validate outstanding balance
        if self.outstanding_balance < 0:
            raise ValueError(f"Outstanding balance cannot be negative: {self.outstanding_balance}")
        if not isinstance(self.outstanding_balance, Decimal):
            object.__setattr__(self, "outstanding_balance", Decimal(str(self.outstanding_balance)))

        # Validate total purchases
        if self.total_purchases < 0:
            raise ValueError(f"Total purchases cannot be negative: {self.total_purchases}")
        if not isinstance(self.total_purchases, Decimal):
            object.__setattr__(self, "total_purchases", Decimal(str(self.total_purchases)))

        # Validate dates UTC
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))
        if self.updated_at.tzinfo is None:
            object.__setattr__(self, "updated_at", self.updated_at.replace(tzinfo=UTC))
        if self.last_purchase_date and isinstance(self.last_purchase_date, datetime):
            object.__setattr__(
                self,
                "last_purchase_date",
                self.last_purchase_date.date()
                if hasattr(self.last_purchase_date, "date")
                else self.last_purchase_date,
            )
        if self.last_payment_date and isinstance(self.last_payment_date, datetime):
            object.__setattr__(
                self,
                "last_payment_date",
                self.last_payment_date.date()
                if hasattr(self.last_payment_date, "date")
                else self.last_payment_date,
            )

        # Validate version
        if self.version < 1:
            raise ValueError("Version must be >= 1")

    # ------------------------------------------------------------------------
    # Factory Methods
    # ------------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        legal_entity_id: UUID,
        supplier_code: str,
        supplier_name: str,
        supplier_type: SupplierType,
        created_by: str = "system",
        supplier_id: UUID | None = None,
        **kwargs,
    ) -> SupplierEntity:
        """Create a new supplier with defaults."""
        now = datetime.now(UTC)
        return cls(
            supplier_id=supplier_id or uuid4(),
            legal_entity_id=legal_entity_id,
            supplier_code=supplier_code,
            supplier_name=supplier_name,
            supplier_type=supplier_type,
            created_at=now,
            updated_at=now,
            created_by=created_by,
            updated_by=created_by,
            version=1,
            **kwargs,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SupplierEntity:
        """Reconstruct supplier from dictionary."""
        supplier_type = SupplierType.from_string(data["supplier_type"])
        if supplier_type is None:
            raise ValueError(f"Invalid supplier_type: {data['supplier_type']}")
        status = SupplierStatus.from_string(data.get("status", "active"))
        if status is None:
            status = SupplierStatus.ACTIVE

        withholding_category = data.get("withholding_category")
        if isinstance(withholding_category, dict):
            withholding_category = SupplierWithholdingCategoryVO.from_dict(withholding_category)
        elif withholding_category is None:
            withholding_category = SupplierWithholdingCategoryVO.create_none()

        return cls(
            supplier_id=UUID(data["supplier_id"])
            if isinstance(data["supplier_id"], str)
            else data["supplier_id"],
            legal_entity_id=UUID(data["legal_entity_id"])
            if isinstance(data["legal_entity_id"], str)
            else data["legal_entity_id"],
            supplier_code=data["supplier_code"],
            supplier_name=data["supplier_name"],
            supplier_type=supplier_type,
            status=status,
            tax_id=data.get("tax_id"),
            email=data.get("email"),
            phone=data.get("phone"),
            fax=data.get("fax"),
            contact_person=data.get("contact_person"),
            address=data.get("address"),
            address2=data.get("address2"),
            city=data.get("city"),
            province=data.get("province"),
            postal_code=data.get("postal_code"),
            country=data.get("country", "Indonesia"),
            bank_name=data.get("bank_name"),
            bank_account_number=data.get("bank_account_number"),
            bank_account_name=data.get("bank_account_name"),
            withholding_category=withholding_category,
            payment_terms_days=data.get("payment_terms_days", 30),
            outstanding_balance=Decimal(str(data.get("outstanding_balance", 0))),
            total_purchases=Decimal(str(data.get("total_purchases", 0))),
            last_purchase_date=date.fromisoformat(data["last_purchase_date"])
            if data.get("last_purchase_date")
            else None,
            last_payment_date=date.fromisoformat(data["last_payment_date"])
            if data.get("last_payment_date")
            else None,
            notes=data.get("notes", ""),
            created_at=datetime.fromisoformat(data["created_at"])
            if data.get("created_at")
            else datetime.now(UTC),
            updated_at=datetime.fromisoformat(data["updated_at"])
            if data.get("updated_at")
            else datetime.now(UTC),
            created_by=data.get("created_by", "system"),
            updated_by=data.get("updated_by", "system"),
            version=data.get("version", 1),
        )

    # ------------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------------

    @property
    def is_active(self) -> bool:
        return self.status == SupplierStatus.ACTIVE

    @property
    def can_transact(self) -> bool:
        return self.status.can_transact()

    @property
    def can_receive_payment(self) -> bool:
        return self.status.can_receive_payment()

    @property
    def full_address(self) -> str | None:
        parts = [
            self.address,
            self.address2,
            self.city,
            self.province,
            self.postal_code,
            self.country,
        ]
        parts = [p for p in parts if p]
        return ", ".join(parts) if parts else None

    @property
    def should_withhold_tax(self) -> bool:
        return self.withholding_category.should_withhold

    # ------------------------------------------------------------------------
    # Business Logic
    # ------------------------------------------------------------------------

    def update_balance(
        self, amount: Decimal, transaction_date: date | None = None
    ) -> SupplierEntity:
        """Update outstanding balance (positive for purchase, negative for payment)."""
        new_balance = self.outstanding_balance + amount
        if new_balance < 0:
            new_balance = Decimal("0")
            logger.warning(
                f"Balance would become negative for supplier {self.supplier_code}, clamping to 0"
            )

        new_total_purchases = self.total_purchases
        new_last_purchase = self.last_purchase_date
        new_last_payment = self.last_payment_date
        tx_date = transaction_date or date.today()

        if amount > 0:
            new_total_purchases = self.total_purchases + amount
            new_last_purchase = tx_date
        elif amount < 0:
            new_last_payment = tx_date

        return SupplierEntity(
            supplier_id=self.supplier_id,
            legal_entity_id=self.legal_entity_id,
            supplier_code=self.supplier_code,
            supplier_name=self.supplier_name,
            supplier_type=self.supplier_type,
            status=self.status,
            tax_id=self.tax_id,
            email=self.email,
            phone=self.phone,
            fax=self.fax,
            contact_person=self.contact_person,
            address=self.address,
            address2=self.address2,
            city=self.city,
            province=self.province,
            postal_code=self.postal_code,
            country=self.country,
            bank_name=self.bank_name,
            bank_account_number=self.bank_account_number,
            bank_account_name=self.bank_account_name,
            withholding_category=self.withholding_category,
            payment_terms_days=self.payment_terms_days,
            outstanding_balance=new_balance,
            total_purchases=new_total_purchases,
            last_purchase_date=new_last_purchase,
            last_payment_date=new_last_payment,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            updated_by=self.updated_by,
            version=self.version + 1,
        )

    def record_purchase(self, amount: Decimal, purchase_date: date | None = None) -> SupplierEntity:
        """Record a purchase from this supplier."""
        if amount <= 0:
            raise ValueError(f"Purchase amount must be positive: {amount}")
        return self.update_balance(amount, purchase_date)

    def record_payment(self, amount: Decimal, payment_date: date | None = None) -> SupplierEntity:
        """Record a payment to this supplier."""
        if amount <= 0:
            raise ValueError(f"Payment amount must be positive: {amount}")
        return self.update_balance(-amount, payment_date)

    def update_payment_terms(self, new_terms_days: int, updated_by: str) -> SupplierEntity:
        """Update payment terms."""
        _validate_payment_terms(new_terms_days)
        return SupplierEntity(
            supplier_id=self.supplier_id,
            legal_entity_id=self.legal_entity_id,
            supplier_code=self.supplier_code,
            supplier_name=self.supplier_name,
            supplier_type=self.supplier_type,
            status=self.status,
            tax_id=self.tax_id,
            email=self.email,
            phone=self.phone,
            fax=self.fax,
            contact_person=self.contact_person,
            address=self.address,
            address2=self.address2,
            city=self.city,
            province=self.province,
            postal_code=self.postal_code,
            country=self.country,
            bank_name=self.bank_name,
            bank_account_number=self.bank_account_number,
            bank_account_name=self.bank_account_name,
            withholding_category=self.withholding_category,
            payment_terms_days=new_terms_days,
            outstanding_balance=self.outstanding_balance,
            total_purchases=self.total_purchases,
            last_purchase_date=self.last_purchase_date,
            last_payment_date=self.last_payment_date,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            updated_by=updated_by,
            version=self.version + 1,
        )

    def update_withholding_category(
        self,
        new_category: SupplierWithholdingCategoryVO,
        updated_by: str,
    ) -> SupplierEntity:
        """Update withholding category."""
        return SupplierEntity(
            supplier_id=self.supplier_id,
            legal_entity_id=self.legal_entity_id,
            supplier_code=self.supplier_code,
            supplier_name=self.supplier_name,
            supplier_type=self.supplier_type,
            status=self.status,
            tax_id=self.tax_id,
            email=self.email,
            phone=self.phone,
            fax=self.fax,
            contact_person=self.contact_person,
            address=self.address,
            address2=self.address2,
            city=self.city,
            province=self.province,
            postal_code=self.postal_code,
            country=self.country,
            bank_name=self.bank_name,
            bank_account_number=self.bank_account_number,
            bank_account_name=self.bank_account_name,
            withholding_category=new_category,
            payment_terms_days=self.payment_terms_days,
            outstanding_balance=self.outstanding_balance,
            total_purchases=self.total_purchases,
            last_purchase_date=self.last_purchase_date,
            last_payment_date=self.last_payment_date,
            notes=f"{self.notes} | Withholding category updated by {updated_by}",
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            updated_by=updated_by,
            version=self.version + 1,
        )

    # ------------------------------------------------------------------------
    # Status Change Methods
    # ------------------------------------------------------------------------

    def activate(self, activated_by: str) -> SupplierEntity:
        """Activate a deactivated supplier."""
        if self.status == SupplierStatus.ACTIVE:
            return self
        if self.status == SupplierStatus.BLACKLISTED:
            raise ValueError("Cannot activate a blacklisted supplier")
        return SupplierEntity(
            supplier_id=self.supplier_id,
            legal_entity_id=self.legal_entity_id,
            supplier_code=self.supplier_code,
            supplier_name=self.supplier_name,
            supplier_type=self.supplier_type,
            status=SupplierStatus.ACTIVE,
            tax_id=self.tax_id,
            email=self.email,
            phone=self.phone,
            fax=self.fax,
            contact_person=self.contact_person,
            address=self.address,
            address2=self.address2,
            city=self.city,
            province=self.province,
            postal_code=self.postal_code,
            country=self.country,
            bank_name=self.bank_name,
            bank_account_number=self.bank_account_number,
            bank_account_name=self.bank_account_name,
            withholding_category=self.withholding_category,
            payment_terms_days=self.payment_terms_days,
            outstanding_balance=self.outstanding_balance,
            total_purchases=self.total_purchases,
            last_purchase_date=self.last_purchase_date,
            last_payment_date=self.last_payment_date,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            updated_by=activated_by,
            version=self.version + 1,
        )

    def deactivate(self, deactivated_by: str) -> SupplierEntity:
        """Deactivate supplier (soft delete)."""
        if self.status == SupplierStatus.INACTIVE:
            return self
        return SupplierEntity(
            supplier_id=self.supplier_id,
            legal_entity_id=self.legal_entity_id,
            supplier_code=self.supplier_code,
            supplier_name=self.supplier_name,
            supplier_type=self.supplier_type,
            status=SupplierStatus.INACTIVE,
            tax_id=self.tax_id,
            email=self.email,
            phone=self.phone,
            fax=self.fax,
            contact_person=self.contact_person,
            address=self.address,
            address2=self.address2,
            city=self.city,
            province=self.province,
            postal_code=self.postal_code,
            country=self.country,
            bank_name=self.bank_name,
            bank_account_number=self.bank_account_number,
            bank_account_name=self.bank_account_name,
            withholding_category=self.withholding_category,
            payment_terms_days=self.payment_terms_days,
            outstanding_balance=self.outstanding_balance,
            total_purchases=self.total_purchases,
            last_purchase_date=self.last_purchase_date,
            last_payment_date=self.last_payment_date,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            updated_by=deactivated_by,
            version=self.version + 1,
        )

    def block(self, blocked_by: str, reason: str) -> SupplierEntity:
        """Block supplier temporarily."""
        if self.status == SupplierStatus.BLOCKED:
            return self
        if self.status == SupplierStatus.BLACKLISTED:
            raise ValueError("Cannot block a blacklisted supplier")
        return SupplierEntity(
            supplier_id=self.supplier_id,
            legal_entity_id=self.legal_entity_id,
            supplier_code=self.supplier_code,
            supplier_name=self.supplier_name,
            supplier_type=self.supplier_type,
            status=SupplierStatus.BLOCKED,
            tax_id=self.tax_id,
            email=self.email,
            phone=self.phone,
            fax=self.fax,
            contact_person=self.contact_person,
            address=self.address,
            address2=self.address2,
            city=self.city,
            province=self.province,
            postal_code=self.postal_code,
            country=self.country,
            bank_name=self.bank_name,
            bank_account_number=self.bank_account_number,
            bank_account_name=self.bank_account_name,
            withholding_category=self.withholding_category,
            payment_terms_days=self.payment_terms_days,
            outstanding_balance=self.outstanding_balance,
            total_purchases=self.total_purchases,
            last_purchase_date=self.last_purchase_date,
            last_payment_date=self.last_payment_date,
            notes=f"{self.notes}\nBlocked: {reason} by {blocked_by}",
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            updated_by=blocked_by,
            version=self.version + 1,
        )

    def unblock(self, unblocked_by: str) -> SupplierEntity:
        """Unblock a supplier."""
        if self.status != SupplierStatus.BLOCKED:
            raise ValueError(f"Supplier is not blocked (status: {self.status.value})")
        return SupplierEntity(
            supplier_id=self.supplier_id,
            legal_entity_id=self.legal_entity_id,
            supplier_code=self.supplier_code,
            supplier_name=self.supplier_name,
            supplier_type=self.supplier_type,
            status=SupplierStatus.ACTIVE,
            tax_id=self.tax_id,
            email=self.email,
            phone=self.phone,
            fax=self.fax,
            contact_person=self.contact_person,
            address=self.address,
            address2=self.address2,
            city=self.city,
            province=self.province,
            postal_code=self.postal_code,
            country=self.country,
            bank_name=self.bank_name,
            bank_account_number=self.bank_account_number,
            bank_account_name=self.bank_account_name,
            withholding_category=self.withholding_category,
            payment_terms_days=self.payment_terms_days,
            outstanding_balance=self.outstanding_balance,
            total_purchases=self.total_purchases,
            last_purchase_date=self.last_purchase_date,
            last_payment_date=self.last_payment_date,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            updated_by=unblocked_by,
            version=self.version + 1,
        )

    def suspend(self, suspended_by: str, reason: str) -> SupplierEntity:
        """Suspend supplier temporarily."""
        if self.status == SupplierStatus.SUSPENDED:
            return self
        return SupplierEntity(
            supplier_id=self.supplier_id,
            legal_entity_id=self.legal_entity_id,
            supplier_code=self.supplier_code,
            supplier_name=self.supplier_name,
            supplier_type=self.supplier_type,
            status=SupplierStatus.SUSPENDED,
            tax_id=self.tax_id,
            email=self.email,
            phone=self.phone,
            fax=self.fax,
            contact_person=self.contact_person,
            address=self.address,
            address2=self.address2,
            city=self.city,
            province=self.province,
            postal_code=self.postal_code,
            country=self.country,
            bank_name=self.bank_name,
            bank_account_number=self.bank_account_number,
            bank_account_name=self.bank_account_name,
            withholding_category=self.withholding_category,
            payment_terms_days=self.payment_terms_days,
            outstanding_balance=self.outstanding_balance,
            total_purchases=self.total_purchases,
            last_purchase_date=self.last_purchase_date,
            last_payment_date=self.last_payment_date,
            notes=f"{self.notes}\nSuspended: {reason} by {suspended_by}",
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            updated_by=suspended_by,
            version=self.version + 1,
        )

    def blacklist(self, blacklisted_by: str, reason: str) -> SupplierEntity:
        """Permanently blacklist supplier."""
        if self.status == SupplierStatus.BLACKLISTED:
            return self
        return SupplierEntity(
            supplier_id=self.supplier_id,
            legal_entity_id=self.legal_entity_id,
            supplier_code=self.supplier_code,
            supplier_name=self.supplier_name,
            supplier_type=self.supplier_type,
            status=SupplierStatus.BLACKLISTED,
            tax_id=self.tax_id,
            email=self.email,
            phone=self.phone,
            fax=self.fax,
            contact_person=self.contact_person,
            address=self.address,
            address2=self.address2,
            city=self.city,
            province=self.province,
            postal_code=self.postal_code,
            country=self.country,
            bank_name=self.bank_name,
            bank_account_number=self.bank_account_number,
            bank_account_name=self.bank_account_name,
            withholding_category=self.withholding_category,
            payment_terms_days=self.payment_terms_days,
            outstanding_balance=self.outstanding_balance,
            total_purchases=self.total_purchases,
            last_purchase_date=self.last_purchase_date,
            last_payment_date=self.last_payment_date,
            notes=f"{self.notes}\nBLACKLISTED: {reason} by {blacklisted_by}",
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            updated_by=blacklisted_by,
            version=self.version + 1,
        )

    # ------------------------------------------------------------------------
    # Validation Helper
    # ------------------------------------------------------------------------

    def validate_can_modify(self, user_role: str = "user") -> tuple[bool, str]:
        if self.status == SupplierStatus.BLACKLISTED:
            return False, "Cannot modify blacklisted supplier"
        return True, ""

    # ------------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------------

    def to_dict(self, include_withholding_details: bool = True) -> dict[str, Any]:
        result = {
            "supplier_id": str(self.supplier_id),
            "legal_entity_id": str(self.legal_entity_id),
            "supplier_code": self.supplier_code,
            "supplier_name": self.supplier_name,
            "supplier_type": self.supplier_type.value,
            "supplier_type_display": self.supplier_type.display_name(),
            "status": self.status.value,
            "status_display": self.status.display_name(),
            "tax_id": self.tax_id,
            "email": self.email,
            "phone": self.phone,
            "fax": self.fax,
            "contact_person": self.contact_person,
            "address": self.address,
            "address2": self.address2,
            "city": self.city,
            "province": self.province,
            "postal_code": self.postal_code,
            "country": self.country,
            "bank_name": self.bank_name,
            "bank_account_number": self.bank_account_number,
            "bank_account_name": self.bank_account_name,
            "payment_terms_days": self.payment_terms_days,
            "outstanding_balance": str(self.outstanding_balance),
            "total_purchases": str(self.total_purchases),
            "last_purchase_date": self.last_purchase_date.isoformat()
            if self.last_purchase_date
            else None,
            "last_payment_date": self.last_payment_date.isoformat()
            if self.last_payment_date
            else None,
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version": self.version,
            "is_active": self.is_active,
            "can_transact": self.can_transact,
            "should_withhold_tax": self.should_withhold_tax,
        }
        if include_withholding_details:
            result["withholding_category"] = self.withholding_category.to_dict()
        return result

    def to_db_record(self) -> dict[str, Any]:
        wc = self.withholding_category
        return {
            "supplier_id": self.supplier_id,
            "legal_entity_id": self.legal_entity_id,
            "supplier_code": self.supplier_code,
            "supplier_name": self.supplier_name,
            "supplier_type": self.supplier_type.value,
            "status": self.status.value,
            "tax_id": self.tax_id,
            "email": self.email,
            "phone": self.phone,
            "fax": self.fax,
            "contact_person": self.contact_person,
            "address": self.address,
            "address2": self.address2,
            "city": self.city,
            "province": self.province,
            "postal_code": self.postal_code,
            "country": self.country,
            "bank_name": self.bank_name,
            "bank_account_number": self.bank_account_number,
            "bank_account_name": self.bank_account_name,
            "withholding_article": wc.article.value,
            "withholding_rate": wc.rate,
            "withholding_is_final": wc.is_final,
            "withholding_effective_date": wc.effective_date,
            "withholding_notes": wc.notes,
            "payment_terms_days": self.payment_terms_days,
            "outstanding_balance": self.outstanding_balance,
            "total_purchases": self.total_purchases,
            "last_purchase_date": self.last_purchase_date,
            "last_payment_date": self.last_payment_date,
            "notes": self.notes,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "version": self.version,
        }

    # ------------------------------------------------------------------------
    # Dunder Methods
    # ------------------------------------------------------------------------

    def __str__(self) -> str:
        return f"{self.supplier_code} - {self.supplier_name}"

    def __repr__(self) -> str:
        return f"SupplierEntity({self.supplier_code}, status={self.status.value})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SupplierEntity):
            return False
        return self.supplier_id == other.supplier_id

    def __hash__(self) -> int:
        return hash(self.supplier_id)


# ============================================================================
# Repository Protocol
# ============================================================================


class SupplierEntityRepository:
    """Repository protocol for SupplierEntity."""

    async def get_by_id(self, supplier_id: UUID, legal_entity_id: UUID) -> SupplierEntity | None:
        raise NotImplementedError

    async def get_by_code(self, supplier_code: str, legal_entity_id: UUID) -> SupplierEntity | None:
        raise NotImplementedError

    async def get_by_tax_id(self, tax_id: str, legal_entity_id: UUID) -> SupplierEntity | None:
        raise NotImplementedError

    async def list_by_status(
        self, status: SupplierStatus, legal_entity_id: UUID, limit: int = 100
    ) -> list[SupplierEntity]:
        raise NotImplementedError

    async def list_by_type(
        self, supplier_type: SupplierType, legal_entity_id: UUID, limit: int = 100
    ) -> list[SupplierEntity]:
        raise NotImplementedError

    async def save(self, supplier: SupplierEntity, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    async def delete(self, supplier_id: UUID, legal_entity_id: UUID) -> None:
        raise NotImplementedError


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "SupplierEntity",
    "SupplierEntityRepository",
    "SupplierStatus",
    "SupplierType",
]
