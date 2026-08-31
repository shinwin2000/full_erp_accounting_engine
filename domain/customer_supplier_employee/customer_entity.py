#!/usr/bin/env python3
"""
Module: customer_entity.py
Layer: Domain / Customer, Supplier, Employee
Responsibility: Customer entity dengan semua method entity dasar.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from typing import Any, ClassVar
from uuid import UUID, uuid4

from domain.customer_supplier_employee.customer_credit_limit_vo import (
    CustomerCreditLimitVO,
)
from domain.customer_supplier_employee.customer_tax_status_vo import (
    CustomerTaxStatusVO,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class CustomerStatus(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    BLOCKED = "blocked"
    BLACKLISTED = "blacklisted"
    DRAFT = "draft"
    SUSPENDED = "suspended"

    def can_transact(self) -> bool:
        return self == CustomerStatus.ACTIVE

    def can_receive_payment(self) -> bool:
        return self in (CustomerStatus.ACTIVE, CustomerStatus.BLOCKED, CustomerStatus.SUSPENDED)

    def can_modify(self) -> bool:
        """Indicates if customer data can be modified in this status."""
        return self in (CustomerStatus.ACTIVE, CustomerStatus.DRAFT, CustomerStatus.SUSPENDED)

    def display_name(self) -> str:
        names = {
            CustomerStatus.ACTIVE: "Aktif",
            CustomerStatus.INACTIVE: "Tidak Aktif",
            CustomerStatus.BLOCKED: "Diblokir",
            CustomerStatus.BLACKLISTED: "Blacklist",
            CustomerStatus.DRAFT: "Draft",
            CustomerStatus.SUSPENDED: "Ditangguhkan",
        }
        return names.get(self, self.value)


class CustomerType(Enum):
    INDIVIDUAL = "individual"
    COMPANY = "company"
    GOVERNMENT = "government"
    NON_PROFIT = "non_profit"
    FOREIGN = "foreign"

    def display_name(self) -> str:
        names = {
            CustomerType.INDIVIDUAL: "Perorangan",
            CustomerType.COMPANY: "Perusahaan",
            CustomerType.GOVERNMENT: "Instansi Pemerintah",
            CustomerType.NON_PROFIT: "Non-profit",
            CustomerType.FOREIGN: "Luar Negeri",
        }
        return names.get(self, self.value)


class CustomerSegment(Enum):
    RETAIL = "retail"
    WHOLESALE = "wholesale"
    CORPORATE = "corporate"
    GOVERNMENT = "government"
    PREMIUM = "premium"
    REGULAR = "regular"

    def display_name(self) -> str:
        names = {
            CustomerSegment.RETAIL: "Ritel",
            CustomerSegment.WHOLESALE: "Grosir",
            CustomerSegment.CORPORATE: "Korporasi",
            CustomerSegment.GOVERNMENT: "Pemerintah",
            CustomerSegment.PREMIUM: "Premium",
            CustomerSegment.REGULAR: "Reguler",
        }
        return names.get(self, self.value)


class PaymentTerm(Enum):
    CASH = 0
    NET_7 = 7
    NET_14 = 14
    NET_30 = 30
    NET_45 = 45
    NET_60 = 60
    NET_90 = 90

    def display_name(self) -> str:
        return "Cash" if self == PaymentTerm.CASH else f"{self.value} Hari"


# ============================================================================
# Customer Entity
# ============================================================================


@dataclass
class CustomerEntity:
    customer_id: UUID
    legal_entity_id: UUID
    customer_code: str
    customer_name: str
    customer_type: CustomerType
    segment: CustomerSegment = CustomerSegment.REGULAR
    status: CustomerStatus = CustomerStatus.ACTIVE
    payment_term: PaymentTerm = PaymentTerm.NET_30
    tax_id: str | None = None
    tax_status: CustomerTaxStatusVO = field(default_factory=CustomerTaxStatusVO)
    email: str | None = None
    phone: str | None = None
    mobile: str | None = None
    fax: str | None = None
    contact_person: str | None = None
    address: str | None = None
    address2: str | None = None
    city: str | None = None
    province: str | None = None
    postal_code: str | None = None
    country: str = "Indonesia"
    website: str | None = None
    credit_limit: CustomerCreditLimitVO = field(
        default_factory=lambda: CustomerCreditLimitVO(Decimal("0"), "IDR")
    )
    outstanding_balance: Decimal = Decimal("0")
    total_purchases: Decimal = Decimal("0")
    last_purchase_date: date | None = None
    last_payment_date: date | None = None
    credit_hold: bool = False
    risk_score: int = 0
    notes: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    updated_by: str = "system"
    version: int = 1

    _audit_trail: ClassVar[list[dict[str, Any]]] = []
    _snapshots: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        self._take_snapshot()

    def _validate(self) -> None:
        if not self.customer_code or len(self.customer_code.strip()) < 2:
            raise ValueError("Customer code must be at least 2 characters")
        if not self.customer_name or len(self.customer_name.strip()) < 2:
            raise ValueError("Customer name must be at least 2 characters")
        if self.outstanding_balance < 0:
            raise ValueError(f"Outstanding balance cannot be negative: {self.outstanding_balance}")
        if self.total_purchases < 0:
            raise ValueError(f"Total purchases cannot be negative: {self.total_purchases}")
        if self.risk_score < 0 or self.risk_score > 100:
            raise ValueError(f"Risk score must be 0-100, got {self.risk_score}")
        if self.tax_id:
            cleaned = re.sub(r"[^\d]", "", self.tax_id)
            if len(cleaned) != 15:
                raise ValueError(f"Tax ID must be 15 digits, got {len(cleaned)}")
        # Combined nested if for email validation (SIM102 fix)
        if self.email and not re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", self.email):
            raise ValueError(f"Invalid email: {self.email}")
        if self.postal_code and not self.postal_code.isdigit():
            raise ValueError(f"Postal code must be digits: {self.postal_code}")
        self.outstanding_balance = self.outstanding_balance.quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )
        self.total_purchases = self.total_purchases.quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self.version,
            "customer_id": str(self.customer_id),
            "code": self.customer_code,
            "name": self.customer_name,
            "status": self.status.value,
            "balance": str(self.outstanding_balance),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self._snapshots.append(snapshot)
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        entry = {
            "action": action,
            "performed_by": performed_by,
            "timestamp": datetime.now(UTC).isoformat(),
            "version": self.version,
            "customer_id": str(self.customer_id),
            "details": details,
        }
        self._audit_trail.append(entry)

    # ==================== ENTITY DASAR METHODS ====================

    def create(self, created_by: str) -> CustomerEntity:
        self._record_audit(
            "CREATE", created_by, {"code": self.customer_code, "name": self.customer_name}
        )
        return self

    def update(self, updated_by: str, **kwargs) -> CustomerEntity:
        if not self.status.can_modify():
            raise ValueError(f"Cannot update customer in status {self.status.value}")
        data = self.to_dict()
        for key, value in kwargs.items():
            if key not in ("customer_id", "created_at", "created_by", "version"):
                data[key] = value
        new_customer = self.from_dict(data)
        new_customer.updated_at = datetime.now(UTC)
        new_customer.updated_by = updated_by
        new_customer.version = self.version + 1
        new_customer._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_customer

    def delete(self, deleted_by: str, reason: str | None = None) -> CustomerEntity:
        if self.status == CustomerStatus.BLACKLISTED:
            raise ValueError("Cannot delete blacklisted customer")
        new_customer = self._copy()
        new_customer.status = CustomerStatus.INACTIVE
        new_customer.updated_at = datetime.now(UTC)
        new_customer.updated_by = deleted_by
        new_customer.version = self.version + 1
        new_customer._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_customer

    def restore(self, restored_by: str) -> CustomerEntity:
        if self.status != CustomerStatus.INACTIVE:
            raise ValueError(f"Cannot restore customer in status {self.status.value}")
        new_customer = self._copy()
        new_customer.status = CustomerStatus.ACTIVE
        new_customer.updated_at = datetime.now(UTC)
        new_customer.updated_by = restored_by
        new_customer.version = self.version + 1
        new_customer._record_audit("RESTORE", restored_by, {})
        return new_customer

    def activate(self, activated_by: str) -> CustomerEntity:
        if self.status == CustomerStatus.ACTIVE:
            return self
        if self.status == CustomerStatus.BLACKLISTED:
            raise ValueError("Cannot activate blacklisted customer")
        new_customer = self._copy()
        new_customer.status = CustomerStatus.ACTIVE
        new_customer.updated_at = datetime.now(UTC)
        new_customer.updated_by = activated_by
        new_customer.version = self.version + 1
        new_customer._record_audit("ACTIVATE", activated_by, {})
        return new_customer

    def deactivate(self, deactivated_by: str) -> CustomerEntity:
        if self.status == CustomerStatus.INACTIVE:
            return self
        new_customer = self._copy()
        new_customer.status = CustomerStatus.INACTIVE
        new_customer.updated_at = datetime.now(UTC)
        new_customer.updated_by = deactivated_by
        new_customer.version = self.version + 1
        new_customer._record_audit("DEACTIVATE", deactivated_by, {})
        return new_customer

    def lock(self, locked_by: str, reason: str) -> CustomerEntity:
        if self.status != CustomerStatus.ACTIVE:
            raise ValueError(f"Cannot lock customer in status {self.status.value}")
        new_customer = self._copy()
        new_customer.status = CustomerStatus.BLOCKED
        new_customer.updated_at = datetime.now(UTC)
        new_customer.updated_by = locked_by
        new_customer.version = self.version + 1
        new_customer._record_audit("LOCK", locked_by, {"reason": reason})
        return new_customer

    def unlock(self, unlocked_by: str) -> CustomerEntity:
        if self.status != CustomerStatus.BLOCKED:
            raise ValueError(f"Cannot unlock customer in status {self.status.value}")
        new_customer = self._copy()
        new_customer.status = CustomerStatus.ACTIVE
        new_customer.updated_at = datetime.now(UTC)
        new_customer.updated_by = unlocked_by
        new_customer.version = self.version + 1
        new_customer._record_audit("UNLOCK", unlocked_by, {})
        return new_customer

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except ValueError as e:
            errors.append(str(e))
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "customer_id": str(self.customer_id),
            "version": self.version,
        }

    def to_dict(self, include_tax_status: bool = True) -> dict[str, Any]:
        result = {
            "customer_id": str(self.customer_id),
            "legal_entity_id": str(self.legal_entity_id),
            "customer_code": self.customer_code,
            "customer_name": self.customer_name,
            "customer_type": self.customer_type.value,
            "segment": self.segment.value,
            "status": self.status.value,
            "payment_term_days": self.payment_term.value,
            "tax_id": self.tax_id,
            "email": self.email,
            "phone": self.phone,
            "mobile": self.mobile,
            "fax": self.fax,
            "contact_person": self.contact_person,
            "address": self.address,
            "address2": self.address2,
            "city": self.city,
            "province": self.province,
            "postal_code": self.postal_code,
            "country": self.country,
            "website": self.website,
            "credit_limit": self.credit_limit.to_dict(),
            "outstanding_balance": str(self.outstanding_balance),
            "total_purchases": str(self.total_purchases),
            "last_purchase_date": self.last_purchase_date.isoformat()
            if self.last_purchase_date
            else None,
            "last_payment_date": self.last_payment_date.isoformat()
            if self.last_payment_date
            else None,
            "credit_hold": self.credit_hold,
            "risk_score": self.risk_score,
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "version": self.version,
        }
        if include_tax_status:
            result["tax_status"] = self.tax_status.to_dict()
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CustomerEntity:
        tax_status = data.get("tax_status")
        if isinstance(tax_status, dict):
            tax_status = CustomerTaxStatusVO.from_dict(tax_status)
        elif tax_status is None:
            tax_status = CustomerTaxStatusVO()
        credit_limit = data.get("credit_limit")
        if isinstance(credit_limit, dict):
            credit_limit = CustomerCreditLimitVO.from_dict(credit_limit)
        elif credit_limit is None:
            credit_limit = CustomerCreditLimitVO(Decimal("0"), "IDR")
        return cls(
            customer_id=UUID(data["customer_id"]),
            legal_entity_id=UUID(data["legal_entity_id"]),
            customer_code=data["customer_code"],
            customer_name=data["customer_name"],
            customer_type=CustomerType(data["customer_type"]),
            segment=CustomerSegment(data.get("segment", "regular")),
            status=CustomerStatus(data.get("status", "active")),
            payment_term=PaymentTerm(data.get("payment_term_days", 30)),
            tax_id=data.get("tax_id"),
            tax_status=tax_status,
            email=data.get("email"),
            phone=data.get("phone"),
            mobile=data.get("mobile"),
            fax=data.get("fax"),
            contact_person=data.get("contact_person"),
            address=data.get("address"),
            address2=data.get("address2"),
            city=data.get("city"),
            province=data.get("province"),
            postal_code=data.get("postal_code"),
            country=data.get("country", "Indonesia"),
            website=data.get("website"),
            credit_limit=credit_limit,
            outstanding_balance=Decimal(data.get("outstanding_balance", "0")),
            total_purchases=Decimal(data.get("total_purchases", "0")),
            last_purchase_date=date.fromisoformat(data["last_purchase_date"])
            if data.get("last_purchase_date")
            else None,
            last_payment_date=date.fromisoformat(data["last_payment_date"])
            if data.get("last_payment_date")
            else None,
            credit_hold=data.get("credit_hold", False),
            risk_score=data.get("risk_score", 0),
            notes=data.get("notes", ""),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            created_by=data.get("created_by", "system"),
            updated_by=data.get("updated_by", "system"),
            version=data.get("version", 1),
        )

    def clone(self, new_code: str | None = None) -> CustomerEntity:
        new_id = uuid4()
        new_code_str = new_code or f"{self.customer_code}_COPY"
        cloned = CustomerEntity(
            customer_id=new_id,
            legal_entity_id=self.legal_entity_id,
            customer_code=new_code_str,
            customer_name=f"{self.customer_name} (COPY)",
            customer_type=self.customer_type,
            segment=self.segment,
            status=CustomerStatus.DRAFT,
            payment_term=self.payment_term,
            tax_id=self.tax_id,
            tax_status=self.tax_status,
            email=self.email,
            phone=self.phone,
            mobile=self.mobile,
            fax=self.fax,
            contact_person=self.contact_person,
            address=self.address,
            address2=self.address2,
            city=self.city,
            province=self.province,
            postal_code=self.postal_code,
            country=self.country,
            website=self.website,
            credit_limit=CustomerCreditLimitVO(Decimal("0"), "IDR"),
            outstanding_balance=Decimal(0),
            total_purchases=Decimal(0),
            last_purchase_date=None,
            last_payment_date=None,
            credit_hold=False,
            risk_score=0,
            notes=f"Cloned from {self.customer_code}",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            updated_by=self.created_by,
            version=1,
        )
        cloned._record_audit("CLONE", self.created_by, {"source": str(self.customer_id)})
        return cloned

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "customer_id": str(self.customer_id),
            "code": self.customer_code,
            "name": self.customer_name,
            "status": self.status.value,
            "balance": str(self.outstanding_balance),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> CustomerEntity:
        new_customer = self._copy()
        new_customer.updated_at = datetime.now(UTC)
        new_customer.updated_by = touched_by
        new_customer.version = self.version + 1
        new_customer._record_audit("TOUCH", touched_by, {})
        return new_customer

    # ==================== BUSINESS LOGIC ====================

    def is_active(self) -> bool:
        return self.status == CustomerStatus.ACTIVE

    def can_transact(self) -> bool:
        return self.status.can_transact() and not self.credit_hold

    def can_receive_payment(self) -> bool:
        return self.status.can_receive_payment()

    def is_exceeding_credit_limit(self, as_of: datetime | None = None) -> bool:
        return self.credit_limit.is_exceeded(self.outstanding_balance, as_of)

    def remaining_credit(self, as_of: datetime | None = None) -> Decimal:
        return self.credit_limit.remaining(self.outstanding_balance, as_of)

    def credit_utilization_percentage(self, as_of: datetime | None = None) -> Decimal:
        return self.credit_limit.utilization_percentage(self.outstanding_balance, as_of)

    def can_invoice(
        self, amount: Decimal, as_of: datetime | None = None
    ) -> tuple[bool, str | None]:
        if amount <= 0:
            return False, "Invoice amount must be positive"
        if not self.can_transact():
            return False, f"Customer status is {self.status.display_name()}"
        if self.credit_hold:
            return False, "Customer is on credit hold"
        return self.credit_limit.can_invoice(amount, self.outstanding_balance, as_of)

    def update_balance(
        self, amount: Decimal, transaction_date: date | None = None
    ) -> CustomerEntity:
        new_balance = self.outstanding_balance + amount
        if new_balance < 0:
            new_balance = Decimal("0")
            logger.warning(f"Balance clamped to 0 for {self.customer_code}")
        new_total = self.total_purchases + amount if amount > 0 else self.total_purchases
        new_last_purchase = (
            transaction_date if amount > 0 and transaction_date else self.last_purchase_date
        )
        new_last_payment = (
            transaction_date if amount < 0 and transaction_date else self.last_payment_date
        )
        return CustomerEntity(
            customer_id=self.customer_id,
            legal_entity_id=self.legal_entity_id,
            customer_code=self.customer_code,
            customer_name=self.customer_name,
            customer_type=self.customer_type,
            segment=self.segment,
            status=self.status,
            payment_term=self.payment_term,
            tax_id=self.tax_id,
            tax_status=self.tax_status,
            email=self.email,
            phone=self.phone,
            mobile=self.mobile,
            fax=self.fax,
            contact_person=self.contact_person,
            address=self.address,
            address2=self.address2,
            city=self.city,
            province=self.province,
            postal_code=self.postal_code,
            country=self.country,
            website=self.website,
            credit_limit=self.credit_limit,
            outstanding_balance=new_balance,
            total_purchases=new_total,
            last_purchase_date=new_last_purchase,
            last_payment_date=new_last_payment,
            credit_hold=self.credit_hold,
            risk_score=self.risk_score,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            updated_by=self.updated_by,
            version=self.version + 1,
        )

    def record_payment(self, amount: Decimal, payment_date: date | None = None) -> CustomerEntity:
        if amount <= 0:
            raise ValueError(f"Payment amount must be positive: {amount}")
        return self.update_balance(-amount, payment_date)

    def record_purchase(self, amount: Decimal, purchase_date: date | None = None) -> CustomerEntity:
        if amount <= 0:
            raise ValueError(f"Purchase amount must be positive: {amount}")
        return self.update_balance(amount, purchase_date)

    def update_credit_limit(
        self, new_limit: CustomerCreditLimitVO, updated_by: str
    ) -> CustomerEntity:
        return CustomerEntity(
            **{
                **self.__dict__,
                "credit_limit": new_limit,
                "updated_at": datetime.now(UTC),
                "updated_by": updated_by,
                "version": self.version + 1,
            }
        )

    def update_tax_status(
        self, new_tax_status: CustomerTaxStatusVO, updated_by: str
    ) -> CustomerEntity:
        return CustomerEntity(
            **{
                **self.__dict__,
                "tax_status": new_tax_status,
                "updated_at": datetime.now(UTC),
                "updated_by": updated_by,
                "version": self.version + 1,
            }
        )

    def block(self, blocked_by: str, reason: str) -> CustomerEntity:
        if self.status == CustomerStatus.BLOCKED:
            return self
        if self.status == CustomerStatus.BLACKLISTED:
            raise ValueError("Cannot block blacklisted customer")
        return CustomerEntity(
            **{
                **self.__dict__,
                "status": CustomerStatus.BLOCKED,
                "credit_hold": True,
                "notes": f"{self.notes}\nBlocked: {reason}",
                "updated_at": datetime.now(UTC),
                "updated_by": blocked_by,
                "version": self.version + 1,
            }
        )

    def unblock(self, unblocked_by: str) -> CustomerEntity:
        if self.status != CustomerStatus.BLOCKED:
            raise ValueError("Customer is not blocked")
        return CustomerEntity(
            **{
                **self.__dict__,
                "status": CustomerStatus.ACTIVE,
                "credit_hold": False,
                "updated_at": datetime.now(UTC),
                "updated_by": unblocked_by,
                "version": self.version + 1,
            }
        )

    def blacklist(self, blacklisted_by: str, reason: str) -> CustomerEntity:
        return CustomerEntity(
            **{
                **self.__dict__,
                "status": CustomerStatus.BLACKLISTED,
                "credit_hold": True,
                "risk_score": 100,
                "notes": f"{self.notes}\nBLACKLISTED: {reason}",
                "updated_at": datetime.now(UTC),
                "updated_by": blacklisted_by,
                "version": self.version + 1,
            }
        )

    def update_credit_hold(
        self, credit_hold: bool, updated_by: str, reason: str | None = None
    ) -> CustomerEntity:
        if credit_hold == self.credit_hold:
            return self
        notes = self.notes
        if reason:
            notes = f"{notes}\nCredit hold {'applied' if credit_hold else 'released'}: {reason}"
        return CustomerEntity(
            **{
                **self.__dict__,
                "credit_hold": credit_hold,
                "notes": notes,
                "updated_at": datetime.now(UTC),
                "updated_by": updated_by,
                "version": self.version + 1,
            }
        )

    def update_risk_score(self, new_score: int, updated_by: str) -> CustomerEntity:
        if new_score < 0 or new_score > 100:
            raise ValueError(f"Risk score must be 0-100, got {new_score}")
        return CustomerEntity(
            **{
                **self.__dict__,
                "risk_score": new_score,
                "updated_at": datetime.now(UTC),
                "updated_by": updated_by,
                "version": self.version + 1,
            }
        )

    def _copy(self) -> CustomerEntity:
        return CustomerEntity(
            customer_id=self.customer_id,
            legal_entity_id=self.legal_entity_id,
            customer_code=self.customer_code,
            customer_name=self.customer_name,
            customer_type=self.customer_type,
            segment=self.segment,
            status=self.status,
            payment_term=self.payment_term,
            tax_id=self.tax_id,
            tax_status=self.tax_status,
            email=self.email,
            phone=self.phone,
            mobile=self.mobile,
            fax=self.fax,
            contact_person=self.contact_person,
            address=self.address,
            address2=self.address2,
            city=self.city,
            province=self.province,
            postal_code=self.postal_code,
            country=self.country,
            website=self.website,
            credit_limit=self.credit_limit,
            outstanding_balance=self.outstanding_balance,
            total_purchases=self.total_purchases,
            last_purchase_date=self.last_purchase_date,
            last_payment_date=self.last_payment_date,
            credit_hold=self.credit_hold,
            risk_score=self.risk_score,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=self.updated_at,
            created_by=self.created_by,
            updated_by=self.updated_by,
            version=self.version,
        )


# ============================================================================
# Repository Interface (Real Implementation)
# ============================================================================


class CustomerEntityRepository:
    _storage: ClassVar[dict[UUID, dict[UUID, CustomerEntity]]] = {}

    @classmethod
    def _get_storage(cls, legal_entity_id: UUID) -> dict[UUID, CustomerEntity]:
        if legal_entity_id not in cls._storage:
            cls._storage[legal_entity_id] = {}
        return cls._storage[legal_entity_id]

    @classmethod
    async def get_by_id(cls, customer_id: UUID, legal_entity_id: UUID) -> CustomerEntity | None:
        storage = cls._get_storage(legal_entity_id)
        return storage.get(customer_id)

    @classmethod
    async def get_by_code(cls, customer_code: str, legal_entity_id: UUID) -> CustomerEntity | None:
        storage = cls._get_storage(legal_entity_id)
        for cust in storage.values():
            if cust.customer_code == customer_code:
                return cust
        return None

    @classmethod
    async def get_by_email(cls, email: str, legal_entity_id: UUID) -> CustomerEntity | None:
        storage = cls._get_storage(legal_entity_id)
        for cust in storage.values():
            if cust.email == email:
                return cust
        return None

    @classmethod
    async def get_by_tax_id(cls, tax_id: str, legal_entity_id: UUID) -> CustomerEntity | None:
        storage = cls._get_storage(legal_entity_id)
        for cust in storage.values():
            if cust.tax_id == tax_id:
                return cust
        return None

    @classmethod
    async def get_all(cls, legal_entity_id: UUID) -> list[CustomerEntity]:
        storage = cls._get_storage(legal_entity_id)
        return list(storage.values())

    @classmethod
    async def save(cls, customer: CustomerEntity, legal_entity_id: UUID) -> None:
        storage = cls._get_storage(legal_entity_id)
        storage[customer.customer_id] = customer

    @classmethod
    async def update(cls, customer: CustomerEntity, legal_entity_id: UUID) -> None:
        await cls.save(customer, legal_entity_id)

    @classmethod
    async def delete(cls, customer_id: UUID, legal_entity_id: UUID) -> None:
        storage = cls._get_storage(legal_entity_id)
        storage.pop(customer_id, None)

    @classmethod
    async def exists(cls, customer_id: UUID, legal_entity_id: UUID) -> bool:
        storage = cls._get_storage(legal_entity_id)
        return customer_id in storage

    @classmethod
    async def count(cls, legal_entity_id: UUID) -> int:
        storage = cls._get_storage(legal_entity_id)
        return len(storage)

    @classmethod
    async def list_all(
        cls, legal_entity_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[CustomerEntity]:
        customers = await cls.get_all(legal_entity_id)
        return customers[offset : offset + limit]

    @classmethod
    async def paginate(
        cls, legal_entity_id: UUID, page: int = 1, per_page: int = 20
    ) -> tuple[list[CustomerEntity], int]:
        customers = await cls.get_all(legal_entity_id)
        total = len(customers)
        start = (page - 1) * per_page
        end = start + per_page
        return customers[start:end], total

    @classmethod
    async def search(
        cls, legal_entity_id: UUID, query: str, fields: list[str] | None = None
    ) -> list[CustomerEntity]:
        if fields is None:
            fields = ["customer_code", "customer_name", "email"]
        customers = await cls.get_all(legal_entity_id)
        query_lower = query.lower()
        results = []
        for cust in customers:
            for field_name in fields:
                value = getattr(cust, field_name, "")
                if value and query_lower in str(value).lower():
                    results.append(cust)
                    break
        return results

    @classmethod
    async def lock(
        cls, customer_id: UUID, legal_entity_id: UUID, locked_by: str, reason: str
    ) -> CustomerEntity:
        cust = await cls.get_by_id(customer_id, legal_entity_id)
        if not cust:
            raise ValueError(f"Customer {customer_id} not found")
        locked = cust.lock(locked_by, reason)
        await cls.save(locked, legal_entity_id)
        return locked

    @classmethod
    async def unlock(
        cls, customer_id: UUID, legal_entity_id: UUID, unlocked_by: str
    ) -> CustomerEntity:
        cust = await cls.get_by_id(customer_id, legal_entity_id)
        if not cust:
            raise ValueError(f"Customer {customer_id} not found")
        unlocked = cust.unlock(unlocked_by)
        await cls.save(unlocked, legal_entity_id)
        return unlocked


__all__ = [
    "CustomerEntity",
    "CustomerEntityRepository",
    "CustomerSegment",
    "CustomerStatus",
    "CustomerType",
    "PaymentTerm",
]
