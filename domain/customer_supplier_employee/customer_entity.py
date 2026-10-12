#!/usr/bin/env python3
"""
Module: customer_entity.py
Layer: Domain / Customer, Supplier, Employee
Responsibility: Customer entity dengan semua method entity dasar.

PERBAIKAN (2026-10-12):
- _audit_trail & _snapshots dari ClassVar -> field(default_factory=list)
  supaya setiap instance punya histori sendiri (tidak bocor antar customer).
- country disimpan sebagai kode ISO 3166-1 alpha-2 (mis. "ID"), bukan nama.
- update() toleran terhadap enum/string/int untuk customer_type, segment,
  status, payment_term.
- Semua method mutasi mengembalikan instance baru (immutable-style).
- CustomerEntityRepository DIPINDAH ke adapter terpisah (SQLAlchemy).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from typing import Any
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
        return self in (
            CustomerStatus.ACTIVE,
            CustomerStatus.BLOCKED,
            CustomerStatus.SUSPENDED,
        )

    def can_modify(self) -> bool:
        return self in (
            CustomerStatus.ACTIVE,
            CustomerStatus.DRAFT,
            CustomerStatus.SUSPENDED,
        )

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
# Helper Functions
# ============================================================================


def _to_enum(value: Any, enum_cls: type[Enum]) -> Any:
    """Konversi value (str/int/member) ke enum member."""
    if isinstance(value, enum_cls):
        return value
    return enum_cls(value)


def _validate_iso_country(code: str) -> str:
    """Validasi kode negara ISO 3166-1 alpha-2."""
    if not code or not isinstance(code, str):
        raise ValueError("Country code must be a non-empty string")
    cleaned = code.strip().upper()
    if len(cleaned) != 2 or not cleaned.isalpha():
        raise ValueError(
            f"Country code must be 2 letters (ISO 3166-1 alpha-2), got '{code}'"
        )
    return cleaned


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
    country: str = "ID"
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
    # Instance-level (bukan ClassVar!)
    _audit_trail: list[dict[str, Any]] = field(
        default_factory=list, repr=False, compare=False
    )
    _snapshots: list[dict[str, Any]] = field(
        default_factory=list, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        # Normalisasi enum jika diberikan sebagai value
        object.__setattr__(
            self, "customer_type", _to_enum(self.customer_type, CustomerType)
        )
        object.__setattr__(self, "segment", _to_enum(self.segment, CustomerSegment))
        object.__setattr__(self, "status", _to_enum(self.status, CustomerStatus))
        object.__setattr__(self, "payment_term", _to_enum(self.payment_term, PaymentTerm))
        object.__setattr__(self, "country", _validate_iso_country(self.country))
        self._validate()
        self._take_snapshot()

    def _validate(self) -> None:
        if not self.customer_code or len(self.customer_code.strip()) < 2:
            raise ValueError("Customer code must be at least 2 characters")
        if not self.customer_name or len(self.customer_name.strip()) < 2:
            raise ValueError("Customer name must be at least 2 characters")
        if self.outstanding_balance < 0:
            raise ValueError(
                f"Outstanding balance cannot be negative: {self.outstanding_balance}"
            )
        if self.total_purchases < 0:
            raise ValueError(
                f"Total purchases cannot be negative: {self.total_purchases}"
            )
        if self.risk_score < 0 or self.risk_score > 100:
            raise ValueError(f"Risk score must be 0-100, got {self.risk_score}")
        if self.tax_id:
            cleaned = re.sub(r"[^\d]", "", self.tax_id)
            if len(cleaned) != 15:
                raise ValueError(f"Tax ID must be 15 digits, got {len(cleaned)}")
        if self.email and not re.match(
            r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", self.email
        ):
            raise ValueError(f"Invalid email: {self.email}")
        if self.postal_code and not self.postal_code.isdigit():
            raise ValueError(f"Postal code must be digits: {self.postal_code}")
        if self.version < 1:
            raise ValueError(f"Version must be >= 1, got {self.version}")

        # Normalisasi Decimal
        object.__setattr__(
            self,
            "outstanding_balance",
            self.outstanding_balance.quantize(
                Decimal("0.01"), rounding=ROUND_HALF_EVEN
            ),
        )
        object.__setattr__(
            self,
            "total_purchases",
            self.total_purchases.quantize(
                Decimal("0.01"), rounding=ROUND_HALF_EVEN
            ),
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

    def _record_audit(
        self, action: str, performed_by: str, details: dict[str, Any]
    ) -> None:
        entry = {
            "action": action,
            "performed_by": performed_by,
            "timestamp": datetime.now(UTC).isoformat(),
            "version": self.version,
            "customer_id": str(self.customer_id),
            "details": details,
        }
        self._audit_trail.append(entry)
        if len(self._audit_trail) > 1000:
            self._audit_trail.pop(0)

    # ==================== ENTITY DASAR METHODS ====================

    def create(self, created_by: str) -> CustomerEntity:
        self._record_audit(
            "CREATE", created_by, {"code": self.customer_code, "name": self.customer_name}
        )
        return self

    def update(self, updated_by: str, **kwargs: Any) -> CustomerEntity:
        if not self.status.can_modify():
            raise ValueError(f"Cannot update customer in status {self.status.value}")
        new_customer = self._copy()
        for key, value in kwargs.items():
            if key in ("customer_id", "created_at", "created_by", "version"):
                continue
            if hasattr(new_customer, key):
                # Normalisasi enum
                if key == "customer_type":
                    value = _to_enum(value, CustomerType)
                elif key == "segment":
                    value = _to_enum(value, CustomerSegment)
                elif key == "status":
                    value = _to_enum(value, CustomerStatus)
                elif key == "payment_term":
                    value = _to_enum(value, PaymentTerm)
                elif key == "country":
                    value = _validate_iso_country(value)
                setattr(new_customer, key, value)
        new_customer.updated_at = datetime.now(UTC)
        new_customer.updated_by = updated_by
        new_customer.version = self.version + 1
        new_customer._validate()
        new_customer._record_audit("UPDATE", updated_by, {"changes": list(kwargs.keys())})
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
        new_customer.credit_hold = True
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
        new_customer.credit_hold = False
        new_customer.updated_at = datetime.now(UTC)
        new_customer.updated_by = unlocked_by
        new_customer.version = self.version + 1
        new_customer._record_audit("UNLOCK", unlocked_by, {})
        return new_customer

    def validate(self) -> dict[str, Any]:
        errors: list[str] = []
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
        result: dict[str, Any] = {
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
            customer_type=_to_enum(data["customer_type"], CustomerType),
            segment=_to_enum(data.get("segment", "regular"), CustomerSegment),
            status=_to_enum(data.get("status", "active"), CustomerStatus),
            payment_term=_to_enum(data.get("payment_term_days", 30), PaymentTerm),
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
            country=data.get("country", "ID"),
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
        new_customer = self._copy()
        new_customer.outstanding_balance = new_balance
        new_customer.total_purchases = new_total
        new_customer.last_purchase_date = new_last_purchase
        new_customer.last_payment_date = new_last_payment
        new_customer.updated_at = datetime.now(UTC)
        new_customer.version = self.version + 1
        return new_customer

    def record_payment(
        self, amount: Decimal, payment_date: date | None = None
    ) -> CustomerEntity:
        if amount <= 0:
            raise ValueError(f"Payment amount must be positive: {amount}")
        return self.update_balance(-amount, payment_date)

    def record_purchase(
        self, amount: Decimal, purchase_date: date | None = None
    ) -> CustomerEntity:
        if amount <= 0:
            raise ValueError(f"Purchase amount must be positive: {amount}")
        return self.update_balance(amount, purchase_date)

    def update_credit_limit(
        self, new_limit: CustomerCreditLimitVO, updated_by: str
    ) -> CustomerEntity:
        new_customer = self._copy()
        new_customer.credit_limit = new_limit
        new_customer.updated_at = datetime.now(UTC)
        new_customer.updated_by = updated_by
        new_customer.version = self.version + 1
        new_customer._record_audit(
            "CREDIT_LIMIT_CHANGED",
            updated_by,
            {"old": str(self.credit_limit.amount), "new": str(new_limit.amount)},
        )
        return new_customer

    def update_tax_status(
        self, new_tax_status: CustomerTaxStatusVO, updated_by: str
    ) -> CustomerEntity:
        new_customer = self._copy()
        new_customer.tax_status = new_tax_status
        new_customer.updated_at = datetime.now(UTC)
        new_customer.updated_by = updated_by
        new_customer.version = self.version + 1
        new_customer._record_audit("TAX_STATUS_CHANGED", updated_by, {})
        return new_customer

    def block(self, blocked_by: str, reason: str) -> CustomerEntity:
        if self.status == CustomerStatus.BLOCKED:
            return self
        if self.status == CustomerStatus.BLACKLISTED:
            raise ValueError("Cannot block blacklisted customer")
        new_customer = self._copy()
        new_customer.status = CustomerStatus.BLOCKED
        new_customer.credit_hold = True
        new_customer.notes = f"{self.notes}\nBlocked: {reason}"
        new_customer.updated_at = datetime.now(UTC)
        new_customer.updated_by = blocked_by
        new_customer.version = self.version + 1
        new_customer._record_audit("BLOCK", blocked_by, {"reason": reason})
        return new_customer

    def unblock(self, unblocked_by: str) -> CustomerEntity:
        if self.status != CustomerStatus.BLOCKED:
            raise ValueError("Customer is not blocked")
        new_customer = self._copy()
        new_customer.status = CustomerStatus.ACTIVE
        new_customer.credit_hold = False
        new_customer.updated_at = datetime.now(UTC)
        new_customer.updated_by = unblocked_by
        new_customer.version = self.version + 1
        new_customer._record_audit("UNBLOCK", unblocked_by, {})
        return new_customer

    def blacklist(self, blacklisted_by: str, reason: str) -> CustomerEntity:
        new_customer = self._copy()
        new_customer.status = CustomerStatus.BLACKLISTED
        new_customer.credit_hold = True
        new_customer.risk_score = 100
        new_customer.notes = f"{self.notes}\nBLACKLISTED: {reason}"
        new_customer.updated_at = datetime.now(UTC)
        new_customer.updated_by = blacklisted_by
        new_customer.version = self.version + 1
        new_customer._record_audit("BLACKLIST", blacklisted_by, {"reason": reason})
        return new_customer

    def update_credit_hold(
        self, credit_hold: bool, updated_by: str, reason: str | None = None
    ) -> CustomerEntity:
        if credit_hold == self.credit_hold:
            return self
        notes = self.notes
        if reason:
            notes = (
                f"{notes}\nCredit hold "
                f"{'applied' if credit_hold else 'released'}: {reason}"
            )
        new_customer = self._copy()
        new_customer.credit_hold = credit_hold
        new_customer.notes = notes
        new_customer.updated_at = datetime.now(UTC)
        new_customer.updated_by = updated_by
        new_customer.version = self.version + 1
        new_customer._record_audit(
            "CREDIT_HOLD_CHANGED", updated_by, {"credit_hold": credit_hold}
        )
        return new_customer

    def update_risk_score(self, new_score: int, updated_by: str) -> CustomerEntity:
        if new_score < 0 or new_score > 100:
            raise ValueError(f"Risk score must be 0-100, got {new_score}")
        new_customer = self._copy()
        new_customer.risk_score = new_score
        new_customer.updated_at = datetime.now(UTC)
        new_customer.updated_by = updated_by
        new_customer.version = self.version + 1
        new_customer._record_audit(
            "RISK_SCORE_CHANGED", updated_by, {"new_score": new_score}
        )
        return new_customer

    def _copy(self) -> CustomerEntity:
        """Salinan dengan audit trail/snapshot yang SAMA (dibagi, bukan dicopy)."""
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
            _audit_trail=self._audit_trail,
            _snapshots=self._snapshots,
        )


# ============================================================================
# Repository Interface (Protocol) — implementasi nyata di adapter SQLAlchemy
# ============================================================================


class CustomerEntityRepository:
    """
    Protocol/interface untuk CustomerEntityRepository.

    Implementasi nyata ada di:
        adapters/secondary_impl/sqlalchemy_customer_repository_impl.py
    """

    async def get_by_id(
        self, customer_id: UUID, legal_entity_id: UUID
    ) -> CustomerEntity | None:
        raise NotImplementedError

    async def get_by_code(
        self, customer_code: str, legal_entity_id: UUID
    ) -> CustomerEntity | None:
        raise NotImplementedError

    async def get_by_email(
        self, email: str, legal_entity_id: UUID
    ) -> CustomerEntity | None:
        raise NotImplementedError

    async def get_by_tax_id(
        self, tax_id: str, legal_entity_id: UUID
    ) -> CustomerEntity | None:
        raise NotImplementedError

    async def get_all(self, legal_entity_id: UUID) -> list[CustomerEntity]:
        raise NotImplementedError

    async def save(self, customer: CustomerEntity, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    async def update(self, customer: CustomerEntity, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    async def delete(self, customer_id: UUID, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    async def exists(self, customer_id: UUID, legal_entity_id: UUID) -> bool:
        raise NotImplementedError

    async def count(self, legal_entity_id: UUID) -> int:
        raise NotImplementedError

    async def list_all(
        self, legal_entity_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[CustomerEntity]:
        raise NotImplementedError

    async def paginate(
        self, legal_entity_id: UUID, page: int = 1, per_page: int = 20
    ) -> tuple[list[CustomerEntity], int]:
        raise NotImplementedError

    async def search(
        self,
        legal_entity_id: UUID,
        query: str,
        fields: list[str] | None = None,
    ) -> list[CustomerEntity]:
        raise NotImplementedError

    async def lock(
        self,
        customer_id: UUID,
        legal_entity_id: UUID,
        locked_by: str,
        reason: str,
    ) -> CustomerEntity:
        raise NotImplementedError

    async def unlock(
        self, customer_id: UUID, legal_entity_id: UUID, unlocked_by: str
    ) -> CustomerEntity:
        raise NotImplementedError


__all__ = [
    "CustomerEntity",
    "CustomerEntityRepository",
    "CustomerSegment",
    "CustomerStatus",
    "CustomerType",
    "PaymentTerm",
]
