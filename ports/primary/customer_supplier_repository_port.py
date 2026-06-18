#!/usr/bin/env python3
"""
Module: customer_supplier_repository_port.py
Layer: Ports (Primary)
Responsibility: Implementasi in-memory repository untuk master Customer dan Supplier.
               Mendukung full CRUD, pencarian, pengelompokan, limit kredit, tax status,
               blacklist, audit trail, import/export CSV, dan statistik.
Audit: Setiap perubahan data customer/supplier tercatat.
"""

from __future__ import annotations

import asyncio
import csv
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


class CustomerCategory(Enum):
    """Kategori customer."""

    REGULAR = "regular"
    PREMIUM = "premium"
    WHOLESALE = "wholesale"
    RETAIL = "retail"
    GOVERNMENT = "government"
    INTERNATIONAL = "international"
    INTERNAL = "internal"


class SupplierCategory(Enum):
    """Kategori supplier."""

    LOCAL = "local"
    IMPORT = "import"
    SOLE = "sole_distributor"
    MANUFACTURER = "manufacturer"
    SERVICE = "service"
    INDIVIDUAL = "individual"
    GOVERNMENT = "government"


class TaxStatus(Enum):
    """Status perpajakan."""

    PKP = "pkp"  # Pengusaha Kena Pajak
    NON_PKP = "non_pkp"
    SPECIAL = "special"  # Wajib Pajak dengan perlakuan khusus


class PaymentTerm(Enum):
    """Termin pembayaran default."""

    COD = "cod"
    NET7 = "net7"
    NET14 = "net14"
    NET30 = "net30"
    NET60 = "net60"
    EOM = "eom"  # End of month
    N20 = "n20"
    N30 = "n30"


class CustomerStatus(Enum):
    """Status customer."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    BLACKLISTED = "blacklisted"
    SUSPENDED = "suspended"


class SupplierStatus(Enum):
    """Status supplier."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    BLACKLISTED = "blacklisted"
    SUSPENDED = "suspended"


@dataclass
class Customer:
    """
    Aggregate Root Customer.
    """

    id: UUID
    customer_code: str
    customer_name: str
    legal_entity_id: UUID
    category: CustomerCategory
    tax_id_npwp: str | None
    tax_status: TaxStatus
    email: str | None
    phone: str | None
    mobile_phone: str | None
    address: str | None
    city: str | None
    postal_code: str | None
    country: str = "Indonesia"
    currency_code: str = "IDR"
    credit_limit: Decimal = Decimal(0)
    used_credit: Decimal = Decimal(0)
    available_credit: Decimal = Decimal(0)
    payment_term: PaymentTerm = PaymentTerm.NET30
    bank_name: str | None = None
    bank_account_number: str | None = None
    bank_account_name: str | None = None
    is_active: bool = True
    status: CustomerStatus = CustomerStatus.ACTIVE
    blacklist_reason: str | None = None
    notes: str | None = None
    parent_customer_id: UUID | None = None  # Untuk grup customer
    contact_person: str | None = None
    contact_person_phone: str | None = None
    website: str | None = None
    registration_date: date = field(default_factory=date.today)
    last_order_date: date | None = None
    total_orders: int = 0
    total_amount_spent: Decimal = Decimal(0)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID = field(default_factory=lambda: UUID(int=0))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_by: UUID = field(default_factory=lambda: UUID(int=0))
    version: int = 1
    deleted_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "customer_code": self.customer_code,
            "customer_name": self.customer_name,
            "legal_entity_id": str(self.legal_entity_id),
            "category": self.category.value,
            "tax_id_npwp": self.tax_id_npwp,
            "tax_status": self.tax_status.value,
            "email": self.email,
            "phone": self.phone,
            "mobile_phone": self.mobile_phone,
            "address": self.address,
            "city": self.city,
            "postal_code": self.postal_code,
            "country": self.country,
            "currency_code": self.currency_code,
            "credit_limit": float(self.credit_limit),
            "used_credit": float(self.used_credit),
            "available_credit": float(self.available_credit),
            "payment_term": self.payment_term.value,
            "bank_name": self.bank_name,
            "bank_account_number": self.bank_account_number,
            "bank_account_name": self.bank_account_name,
            "is_active": self.is_active,
            "status": self.status.value,
            "blacklist_reason": self.blacklist_reason,
            "notes": self.notes,
            "parent_customer_id": str(self.parent_customer_id) if self.parent_customer_id else None,
            "contact_person": self.contact_person,
            "contact_person_phone": self.contact_person_phone,
            "website": self.website,
            "registration_date": self.registration_date.isoformat(),
            "last_order_date": self.last_order_date.isoformat() if self.last_order_date else None,
            "total_orders": self.total_orders,
            "total_amount_spent": float(self.total_amount_spent),
            "created_at": self.created_at.isoformat(),
            "created_by": str(self.created_by),
            "updated_at": self.updated_at.isoformat(),
            "updated_by": str(self.updated_by),
            "version": self.version,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
        }


@dataclass
class Supplier:
    """
    Aggregate Root Supplier.
    """

    id: UUID
    supplier_code: str
    supplier_name: str
    legal_entity_id: UUID
    category: SupplierCategory
    tax_id_npwp: str | None
    tax_status: TaxStatus
    email: str | None
    phone: str | None
    fax: str | None
    address: str | None
    city: str | None
    postal_code: str | None
    country: str = "Indonesia"
    currency_code: str = "IDR"
    payment_term: PaymentTerm = PaymentTerm.NET30
    bank_name: str | None = None
    bank_account_number: str | None = None
    bank_account_name: str | None = None
    is_active: bool = True
    status: SupplierStatus = SupplierStatus.ACTIVE
    blacklist_reason: str | None = None
    notes: str | None = None
    parent_supplier_id: UUID | None = None
    contact_person: str | None = None
    contact_person_phone: str | None = None
    website: str | None = None
    registration_date: date = field(default_factory=date.today)
    lead_time_days: int = 0  # Delivery lead time in days
    minimum_order: Decimal = Decimal(0)
    total_purchases: Decimal = Decimal(0)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID = field(default_factory=lambda: UUID(int=0))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_by: UUID = field(default_factory=lambda: UUID(int=0))
    version: int = 1
    deleted_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "supplier_code": self.supplier_code,
            "supplier_name": self.supplier_name,
            "legal_entity_id": str(self.legal_entity_id),
            "category": self.category.value,
            "tax_id_npwp": self.tax_id_npwp,
            "tax_status": self.tax_status.value,
            "email": self.email,
            "phone": self.phone,
            "fax": self.fax,
            "address": self.address,
            "city": self.city,
            "postal_code": self.postal_code,
            "country": self.country,
            "currency_code": self.currency_code,
            "payment_term": self.payment_term.value,
            "bank_name": self.bank_name,
            "bank_account_number": self.bank_account_number,
            "bank_account_name": self.bank_account_name,
            "is_active": self.is_active,
            "status": self.status.value,
            "blacklist_reason": self.blacklist_reason,
            "notes": self.notes,
            "parent_supplier_id": str(self.parent_supplier_id) if self.parent_supplier_id else None,
            "contact_person": self.contact_person,
            "contact_person_phone": self.contact_person_phone,
            "website": self.website,
            "registration_date": self.registration_date.isoformat(),
            "lead_time_days": self.lead_time_days,
            "minimum_order": float(self.minimum_order),
            "total_purchases": float(self.total_purchases),
            "created_at": self.created_at.isoformat(),
            "created_by": str(self.created_by),
            "updated_at": self.updated_at.isoformat(),
            "updated_by": str(self.updated_by),
            "version": self.version,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
        }


class CustomerRepositoryPort:
    """
    In-memory repository untuk Customer.
    """

    def __init__(self):
        self._storage: dict[UUID, Customer] = {}
        self._code_index: dict[tuple[str, UUID], Customer] = {}  # (customer_code, legal_entity_id)
        self._category_index: dict[tuple[CustomerCategory, UUID], list[UUID]] = {}
        self._active_index: dict[UUID, list[UUID]] = {}
        self._audit_log: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()

    async def _log_audit(
        self, action: str, customer_id: UUID, user_id: UUID, details: dict[str, Any]
    ):
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "action": action,
            "customer_id": str(customer_id),
            "user_id": str(user_id),
            "details": details,
        }
        self._audit_log.append(entry)
        logger.info(f"CUSTOMER AUDIT: {action} on {customer_id} by {user_id}")

    async def _update_indices(self, customer: Customer, is_insert: bool = True):
        code_key = (customer.customer_code, customer.legal_entity_id)
        if is_insert:
            self._code_index[code_key] = customer
        else:
            self._code_index[code_key] = customer
        # Category index
        cat_key = (customer.category, customer.legal_entity_id)
        if cat_key not in self._category_index:
            self._category_index[cat_key] = []
        if customer.id not in self._category_index[cat_key]:
            self._category_index[cat_key].append(customer.id)
        # Active index
        if customer.is_active and customer.deleted_at is None:
            if customer.legal_entity_id not in self._active_index:
                self._active_index[customer.legal_entity_id] = []
            if customer.id not in self._active_index[customer.legal_entity_id]:
                self._active_index[customer.legal_entity_id].append(customer.id)

    async def _remove_from_indices(self, customer: Customer):
        code_key = (customer.customer_code, customer.legal_entity_id)
        if code_key in self._code_index:
            del self._code_index[code_key]
        cat_key = (customer.category, customer.legal_entity_id)
        if cat_key in self._category_index and customer.id in self._category_index[cat_key]:
            self._category_index[cat_key].remove(customer.id)
        if (
            customer.legal_entity_id in self._active_index
            and customer.id in self._active_index[customer.legal_entity_id]
        ):
            self._active_index[customer.legal_entity_id].remove(customer.id)

    async def add(self, customer: Customer) -> None:
        if customer.id in self._storage:
            raise ValueError(f"Customer {customer.id} already exists")
        code_key = (customer.customer_code, customer.legal_entity_id)
        if code_key in self._code_index:
            raise ValueError(
                f"Customer code {customer.customer_code} already exists for this legal entity"
            )
        customer.created_at = datetime.now(UTC)
        customer.updated_at = customer.created_at
        customer.version = 1
        async with self._lock:
            self._storage[customer.id] = customer
            await self._update_indices(customer, is_insert=True)
        await self._log_audit(
            "ADD",
            customer.id,
            customer.created_by,
            {
                "customer_code": customer.customer_code,
                "customer_name": customer.customer_name,
            },
        )

    async def get_by_id(self, customer_id: UUID) -> Customer | None:
        customer = self._storage.get(customer_id)
        if customer and customer.deleted_at is not None:
            return None
        return customer

    async def get_by_code(self, customer_code: str, legal_entity_id: UUID) -> Customer | None:
        customer = self._code_index.get((customer_code, legal_entity_id))
        if customer and customer.deleted_at is not None:
            return None
        return customer

    async def update(self, customer: Customer) -> None:
        if customer.id not in self._storage:
            raise ValueError(f"Customer {customer.id} not found")
        old = self._storage[customer.id]
        if old.deleted_at is not None:
            raise ValueError("Cannot update deleted customer")
        # Update code index if changed
        old_key = (old.customer_code, old.legal_entity_id)
        new_key = (customer.customer_code, customer.legal_entity_id)
        if old_key != new_key:
            if new_key in self._code_index and self._code_index[new_key].id != customer.id:
                raise ValueError(f"Customer code {customer.customer_code} already exists")
            await self._remove_from_indices(old)
            await self._update_indices(customer, is_insert=True)
        else:
            await self._update_indices(customer, is_insert=False)
        customer.updated_at = datetime.now(UTC)
        customer.version = old.version + 1
        customer.created_at = old.created_at
        customer.created_by = old.created_by
        self._storage[customer.id] = customer
        await self._log_audit(
            "UPDATE",
            customer.id,
            customer.updated_by,
            {
                "changes": "multiple",
            },
        )

    async def delete(self, customer_id: UUID, user_id: UUID, permanent: bool = False) -> bool:
        customer = self._storage.get(customer_id)
        if not customer:
            return False
        if permanent:
            await self._remove_from_indices(customer)
            del self._storage[customer_id]
            await self._log_audit("DELETE_PERMANENT", customer_id, user_id, {})
        else:
            customer.deleted_at = datetime.now(UTC)
            customer.is_active = False
            customer.status = CustomerStatus.INACTIVE
            customer.updated_by = user_id
            customer.updated_at = customer.deleted_at
            customer.version += 1
            await self._remove_from_indices(customer)
            await self._log_audit("DELETE_SOFT", customer_id, user_id, {})
        return True

    async def restore(self, customer_id: UUID, user_id: UUID) -> bool:
        customer = self._storage.get(customer_id)
        if not customer or customer.deleted_at is None:
            return False
        customer.deleted_at = None
        customer.is_active = True
        customer.status = CustomerStatus.ACTIVE
        customer.updated_by = user_id
        customer.updated_at = datetime.now(UTC)
        customer.version += 1
        await self._update_indices(customer, is_insert=True)
        await self._log_audit("RESTORE", customer_id, user_id, {})
        return True

    async def find_by_name_contains(
        self, name_fragment: str, legal_entity_id: UUID, limit: int = 20
    ) -> list[Customer]:
        fragment_lower = name_fragment.lower()
        result = []
        for cust in self._storage.values():
            if cust.legal_entity_id == legal_entity_id and cust.deleted_at is None:
                if (
                    fragment_lower in cust.customer_name.lower()
                    or fragment_lower in cust.customer_code.lower()
                ):
                    result.append(cust)
        return sorted(result, key=lambda x: x.customer_name)[:limit]

    async def find_by_category(
        self, category: CustomerCategory, legal_entity_id: UUID
    ) -> list[Customer]:
        cat_key = (category, legal_entity_id)
        ids = self._category_index.get(cat_key, [])
        return [
            self._storage[cid]
            for cid in ids
            if cid in self._storage and self._storage[cid].deleted_at is None
        ]

    async def find_active(self, legal_entity_id: UUID) -> list[Customer]:
        ids = self._active_index.get(legal_entity_id, [])
        return [self._storage[cid] for cid in ids if cid in self._storage]

    async def update_credit_usage(
        self, customer_id: UUID, order_amount: Decimal, is_addition: bool = True
    ) -> None:
        customer = await self.get_by_id(customer_id)
        if not customer:
            raise ValueError("Customer not found")
        if is_addition:
            customer.used_credit += order_amount
        else:
            customer.used_credit -= order_amount
        if customer.used_credit < 0:
            customer.used_credit = Decimal(0)
        customer.available_credit = customer.credit_limit - customer.used_credit
        customer.updated_at = datetime.now(UTC)
        customer.version += 1
        await self.update(customer)

    async def blacklist(self, customer_id: UUID, reason: str, user_id: UUID) -> bool:
        customer = await self.get_by_id(customer_id)
        if not customer:
            return False
        customer.status = CustomerStatus.BLACKLISTED
        customer.is_active = False
        customer.blacklist_reason = reason
        customer.updated_by = user_id
        customer.updated_at = datetime.now(UTC)
        customer.version += 1
        await self.update(customer)
        await self._log_audit("BLACKLIST", customer_id, user_id, {"reason": reason})
        return True

    async def add_order(self, customer_id: UUID, order_amount: Decimal) -> None:
        customer = await self.get_by_id(customer_id)
        if not customer:
            raise ValueError("Customer not found")
        customer.total_orders += 1
        customer.total_amount_spent += order_amount
        customer.last_order_date = date.today()
        customer.updated_at = datetime.now(UTC)
        customer.version += 1
        await self.update(customer)

    async def export_to_csv(self, legal_entity_id: UUID) -> str:
        customers = [
            c
            for c in self._storage.values()
            if c.legal_entity_id == legal_entity_id and c.deleted_at is None
        ]
        import io

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "customer_code",
                "customer_name",
                "category",
                "tax_id",
                "email",
                "phone",
                "city",
                "credit_limit",
                "used_credit",
                "status",
            ]
        )
        for c in customers:
            writer.writerow(
                [
                    c.customer_code,
                    c.customer_name,
                    c.category.value,
                    c.tax_id_npwp or "",
                    c.email or "",
                    c.phone or "",
                    c.city or "",
                    float(c.credit_limit),
                    float(c.used_credit),
                    c.status.value,
                ]
            )
        return output.getvalue()

    async def get_statistics(self, legal_entity_id: UUID) -> dict[str, Any]:
        customers = [
            c
            for c in self._storage.values()
            if c.legal_entity_id == legal_entity_id and c.deleted_at is None
        ]
        total = len(customers)
        active = sum(1 for c in customers if c.is_active)
        total_credit = sum(c.credit_limit for c in customers)
        total_used = sum(c.used_credit for c in customers)
        return {
            "total_customers": total,
            "active_customers": active,
            "inactive_customers": total - active,
            "blacklisted": sum(1 for c in customers if c.status == CustomerStatus.BLACKLISTED),
            "total_credit_limit": float(total_credit),
            "total_used_credit": float(total_used),
            "available_credit": float(total_credit - total_used),
            "by_category": {
                cat.value: sum(1 for c in customers if c.category == cat)
                for cat in CustomerCategory
            },
        }

    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        return self._audit_log[offset : offset + limit]

    async def health_check(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "total_customers": len(self._storage),
            "total_active_index": sum(len(lst) for lst in self._active_index.values()),
            "audit_log_size": len(self._audit_log),
        }


class SupplierRepositoryPort:
    """
    In-memory repository untuk Supplier.
    """

    def __init__(self):
        self._storage: dict[UUID, Supplier] = {}
        self._code_index: dict[tuple[str, UUID], Supplier] = {}
        self._category_index: dict[tuple[SupplierCategory, UUID], list[UUID]] = {}
        self._active_index: dict[UUID, list[UUID]] = {}
        self._audit_log: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()

    async def _log_audit(
        self, action: str, supplier_id: UUID, user_id: UUID, details: dict[str, Any]
    ):
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "action": action,
            "supplier_id": str(supplier_id),
            "user_id": str(user_id),
            "details": details,
        }
        self._audit_log.append(entry)
        logger.info(f"SUPPLIER AUDIT: {action} on {supplier_id} by {user_id}")

    async def _update_indices(self, supplier: Supplier, is_insert: bool = True):
        code_key = (supplier.supplier_code, supplier.legal_entity_id)
        if is_insert:
            self._code_index[code_key] = supplier
        else:
            self._code_index[code_key] = supplier
        cat_key = (supplier.category, supplier.legal_entity_id)
        if cat_key not in self._category_index:
            self._category_index[cat_key] = []
        if supplier.id not in self._category_index[cat_key]:
            self._category_index[cat_key].append(supplier.id)
        if supplier.is_active and supplier.deleted_at is None:
            if supplier.legal_entity_id not in self._active_index:
                self._active_index[supplier.legal_entity_id] = []
            if supplier.id not in self._active_index[supplier.legal_entity_id]:
                self._active_index[supplier.legal_entity_id].append(supplier.id)

    async def _remove_from_indices(self, supplier: Supplier):
        code_key = (supplier.supplier_code, supplier.legal_entity_id)
        if code_key in self._code_index:
            del self._code_index[code_key]
        cat_key = (supplier.category, supplier.legal_entity_id)
        if cat_key in self._category_index and supplier.id in self._category_index[cat_key]:
            self._category_index[cat_key].remove(supplier.id)
        if (
            supplier.legal_entity_id in self._active_index
            and supplier.id in self._active_index[supplier.legal_entity_id]
        ):
            self._active_index[supplier.legal_entity_id].remove(supplier.id)

    async def add(self, supplier: Supplier) -> None:
        if supplier.id in self._storage:
            raise ValueError(f"Supplier {supplier.id} already exists")
        code_key = (supplier.supplier_code, supplier.legal_entity_id)
        if code_key in self._code_index:
            raise ValueError(f"Supplier code {supplier.supplier_code} already exists")
        supplier.created_at = datetime.now(UTC)
        supplier.updated_at = supplier.created_at
        supplier.version = 1
        async with self._lock:
            self._storage[supplier.id] = supplier
            await self._update_indices(supplier, is_insert=True)
        await self._log_audit(
            "ADD",
            supplier.id,
            supplier.created_by,
            {
                "supplier_code": supplier.supplier_code,
                "supplier_name": supplier.supplier_name,
            },
        )

    async def get_by_id(self, supplier_id: UUID) -> Supplier | None:
        supplier = self._storage.get(supplier_id)
        if supplier and supplier.deleted_at is not None:
            return None
        return supplier

    async def get_by_code(self, supplier_code: str, legal_entity_id: UUID) -> Supplier | None:
        supplier = self._code_index.get((supplier_code, legal_entity_id))
        if supplier and supplier.deleted_at is not None:
            return None
        return supplier

    async def update(self, supplier: Supplier) -> None:
        if supplier.id not in self._storage:
            raise ValueError(f"Supplier {supplier.id} not found")
        old = self._storage[supplier.id]
        if old.deleted_at is not None:
            raise ValueError("Cannot update deleted supplier")
        old_key = (old.supplier_code, old.legal_entity_id)
        new_key = (supplier.supplier_code, supplier.legal_entity_id)
        if old_key != new_key:
            if new_key in self._code_index and self._code_index[new_key].id != supplier.id:
                raise ValueError(f"Supplier code {supplier.supplier_code} already exists")
            await self._remove_from_indices(old)
            await self._update_indices(supplier, is_insert=True)
        else:
            await self._update_indices(supplier, is_insert=False)
        supplier.updated_at = datetime.now(UTC)
        supplier.version = old.version + 1
        supplier.created_at = old.created_at
        supplier.created_by = old.created_by
        self._storage[supplier.id] = supplier
        await self._log_audit("UPDATE", supplier.id, supplier.updated_by, {})

    async def delete(self, supplier_id: UUID, user_id: UUID, permanent: bool = False) -> bool:
        supplier = self._storage.get(supplier_id)
        if not supplier:
            return False
        if permanent:
            await self._remove_from_indices(supplier)
            del self._storage[supplier_id]
            await self._log_audit("DELETE_PERMANENT", supplier_id, user_id, {})
        else:
            supplier.deleted_at = datetime.now(UTC)
            supplier.is_active = False
            supplier.status = SupplierStatus.INACTIVE
            supplier.updated_by = user_id
            supplier.updated_at = supplier.deleted_at
            supplier.version += 1
            await self._remove_from_indices(supplier)
            await self._log_audit("DELETE_SOFT", supplier_id, user_id, {})
        return True

    async def find_by_name_contains(
        self, name_fragment: str, legal_entity_id: UUID, limit: int = 20
    ) -> list[Supplier]:
        fragment_lower = name_fragment.lower()
        result = []
        for sup in self._storage.values():
            if sup.legal_entity_id == legal_entity_id and sup.deleted_at is None:
                if (
                    fragment_lower in sup.supplier_name.lower()
                    or fragment_lower in sup.supplier_code.lower()
                ):
                    result.append(sup)
        return sorted(result, key=lambda x: x.supplier_name)[:limit]

    async def find_active_for_po(self, legal_entity_id: UUID) -> list[Supplier]:
        """Supplier aktif yang bisa dipilih untuk Purchase Order."""
        ids = self._active_index.get(legal_entity_id, [])
        return [self._storage[sid] for sid in ids if sid in self._storage]

    async def find_by_category(
        self, category: SupplierCategory, legal_entity_id: UUID
    ) -> list[Supplier]:
        cat_key = (category, legal_entity_id)
        ids = self._category_index.get(cat_key, [])
        return [
            self._storage[sid]
            for sid in ids
            if sid in self._storage and self._storage[sid].deleted_at is None
        ]

    async def add_purchase(self, supplier_id: UUID, amount: Decimal) -> None:
        supplier = await self.get_by_id(supplier_id)
        if not supplier:
            raise ValueError("Supplier not found")
        supplier.total_purchases += amount
        supplier.updated_at = datetime.now(UTC)
        supplier.version += 1
        await self.update(supplier)

    async def blacklist(self, supplier_id: UUID, reason: str, user_id: UUID) -> bool:
        supplier = await self.get_by_id(supplier_id)
        if not supplier:
            return False
        supplier.status = SupplierStatus.BLACKLISTED
        supplier.is_active = False
        supplier.blacklist_reason = reason
        supplier.updated_by = user_id
        supplier.updated_at = datetime.now(UTC)
        supplier.version += 1
        await self.update(supplier)
        await self._log_audit("BLACKLIST", supplier_id, user_id, {"reason": reason})
        return True

    async def export_to_csv(self, legal_entity_id: UUID) -> str:
        suppliers = [
            s
            for s in self._storage.values()
            if s.legal_entity_id == legal_entity_id and s.deleted_at is None
        ]
        import io

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "supplier_code",
                "supplier_name",
                "category",
                "tax_id",
                "email",
                "phone",
                "city",
                "lead_time_days",
                "status",
            ]
        )
        for s in suppliers:
            writer.writerow(
                [
                    s.supplier_code,
                    s.supplier_name,
                    s.category.value,
                    s.tax_id_npwp or "",
                    s.email or "",
                    s.phone or "",
                    s.city or "",
                    s.lead_time_days,
                    s.status.value,
                ]
            )
        return output.getvalue()

    async def get_statistics(self, legal_entity_id: UUID) -> dict[str, Any]:
        suppliers = [
            s
            for s in self._storage.values()
            if s.legal_entity_id == legal_entity_id and s.deleted_at is None
        ]
        total = len(suppliers)
        active = sum(1 for s in suppliers if s.is_active)
        return {
            "total_suppliers": total,
            "active_suppliers": active,
            "inactive_suppliers": total - active,
            "blacklisted": sum(1 for s in suppliers if s.status == SupplierStatus.BLACKLISTED),
            "by_category": {
                cat.value: sum(1 for s in suppliers if s.category == cat)
                for cat in SupplierCategory
            },
        }

    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        return self._audit_log[offset : offset + limit]

    async def health_check(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "total_suppliers": len(self._storage),
            "total_active_index": sum(len(lst) for lst in self._active_index.values()),
            "audit_log_size": len(self._audit_log),
        }
