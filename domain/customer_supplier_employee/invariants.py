#!/usr/bin/env python3
"""
Module: invariants.py
Layer: 6 - Domain / Customer, Supplier, Employee
Responsibility: Aturan: NPWP unik per entitas, nama wajib diisi, dll.
               Mendefinisikan semua invariant yang harus dipenuhi oleh
               Customer, Supplier, Employee aggregates. Memastikan bahwa
               data master selalu dalam keadaan valid secara bisnis.

Dependencies:
- standard library (logging, decimal, datetime, re)
- domain.customer_supplier_employee.customer_entity (CustomerEntity)
- domain.customer_supplier_employee.supplier_entity (SupplierEntity)
- domain.customer_supplier_employee.employee_entity (EmployeeEntity)

Audit: Setiap pelanggaran invariant dictat.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from decimal import Decimal

from domain.customer_supplier_employee.customer_entity import CustomerStatus

logger = logging.getLogger(__name__)


# === 1. INVARIANT VALIDATION RESULT ===


class InvariantResult:
    """Hasil validasi invariant."""

    def __init__(self, is_valid: bool = True, errors: list[str] | None = None):
        self.is_valid = is_valid
        self.errors = errors or []

    def add_error(self, error: str) -> None:
        self.errors.append(error)
        self.is_valid = False

    def merge(self, other: InvariantResult) -> InvariantResult:
        if not other.is_valid:
            self.is_valid = False
            self.errors.extend(other.errors)
        return self

    def __bool__(self) -> bool:
        return self.is_valid


# === 2. CUSTOMER INVARIANTS ===


class CustomerInvariants:
    """
    Kumpulan invariant untuk Customer aggregate.
    """

    @staticmethod
    def validate_customer_code_unique(
        customer_code: str,
        existing_codes: set[str],
    ) -> InvariantResult:
        result = InvariantResult(True)
        if customer_code in existing_codes:
            result.add_error(f"Customer code '{customer_code}' already exists")
        return result

    @staticmethod
    def validate_email_unique(email: str, existing_emails: set[str]) -> InvariantResult:
        result = InvariantResult(True)
        if email and email in existing_emails:
            result.add_error(f"Email '{email}' already exists")
        return result

    @staticmethod
    def validate_credit_limit(credit_limit: Decimal) -> InvariantResult:
        result = InvariantResult(True)
        if credit_limit < 0:
            result.add_error(f"Credit limit cannot be negative: {credit_limit}")
        return result

    @staticmethod
    def validate_customer_status_transition(
        current_status: CustomerStatus,
        new_status: CustomerStatus,
    ) -> InvariantResult:
        result = InvariantResult(True)
        if (
            current_status == CustomerStatus.BLACKLISTED
            and new_status != CustomerStatus.BLACKLISTED
        ):
            result.add_error("Cannot change status of blacklisted customer")
        return result


# === 3. SUPPLIER INVARIANTS ===


class SupplierInvariants:
    """
    Kumpulan invariant untuk Supplier aggregate.
    """

    @staticmethod
    def validate_supplier_code_unique(
        supplier_code: str,
        existing_codes: set[str],
    ) -> InvariantResult:
        result = InvariantResult(True)
        if supplier_code in existing_codes:
            result.add_error(f"Supplier code '{supplier_code}' already exists")
        return result

    @staticmethod
    def validate_tax_id_unique(tax_id: str, existing_tax_ids: set[str]) -> InvariantResult:
        result = InvariantResult(True)
        if tax_id and tax_id in existing_tax_ids:
            result.add_error(f"Tax ID '{tax_id}' already exists")
        return result

    @staticmethod
    def validate_payment_terms(payment_terms_days: int) -> InvariantResult:
        result = InvariantResult(True)
        if payment_terms_days < 0:
            result.add_error(f"Payment terms days cannot be negative: {payment_terms_days}")
        if payment_terms_days > 180:
            logger.warning(f"Payment terms {payment_terms_days} days is unusually long")
        return result


# === 4. EMPLOYEE INVARIANTS ===


class EmployeeInvariants:
    """
    Kumpulan invariant untuk Employee aggregate.
    """

    @staticmethod
    def validate_employee_number_unique(
        employee_number: str,
        existing_numbers: set[str],
    ) -> InvariantResult:
        result = InvariantResult(True)
        if employee_number in existing_numbers:
            result.add_error(f"Employee number '{employee_number}' already exists")
        return result

    @staticmethod
    def validate_birth_date(birth_date: datetime | None, join_date: datetime) -> InvariantResult:
        result = InvariantResult(True)
        if birth_date:
            min_age_date = join_date - timedelta(days=18 * 365)
            if birth_date > min_age_date:
                result.add_error("Employee must be at least 18 years old at join date")
        return result

    @staticmethod
    def validate_resign_date(join_date: datetime, resign_date: datetime | None) -> InvariantResult:
        result = InvariantResult(True)
        if resign_date and resign_date <= join_date:
            result.add_error("Resign date must be after join date")
        return result

    @staticmethod
    def validate_basic_salary(
        salary: Decimal, minimum_wage: Decimal = Decimal("4500000")
    ) -> InvariantResult:
        result = InvariantResult(True)
        if salary < minimum_wage:
            result.add_error(f"Basic salary {salary} is below minimum wage {minimum_wage}")
        if salary <= 0:
            result.add_error(f"Basic salary must be positive: {salary}")
        return result


# === 5. MASTER DATA INVARIANT ENFORCER ===


class MasterDataInvariantEnforcer:
    """
    Enforcer untuk semua invariant Customer, Supplier, Employee.
    """

    def __init__(
        self,
        customer_code_checker: Callable[[], set[str]],
        supplier_code_checker: Callable[[], set[str]],
        employee_number_checker: Callable[[], set[str]],
        email_checker: Callable[[], set[str]],
        tax_id_checker: Callable[[], set[str]],
    ):
        self._customer_code_checker = customer_code_checker
        self._supplier_code_checker = supplier_code_checker
        self._employee_number_checker = employee_number_checker
        self._email_checker = email_checker
        self._tax_id_checker = tax_id_checker
        self._customer_invariants = CustomerInvariants()
        self._supplier_invariants = SupplierInvariants()
        self._employee_invariants = EmployeeInvariants()

    async def enforce_customer_create(
        self,
        customer_code: str,
        email: str | None,
        credit_limit: Decimal,
    ) -> InvariantResult:
        result = InvariantResult(True)
        existing_codes = self._customer_code_checker()  # synchronous, no await
        result.merge(
            self._customer_invariants.validate_customer_code_unique(customer_code, existing_codes)
        )

        if email:
            existing_emails = self._email_checker()  # synchronous, no await
            result.merge(self._customer_invariants.validate_email_unique(email, existing_emails))

        result.merge(self._customer_invariants.validate_credit_limit(credit_limit))
        return result

    async def enforce_supplier_create(
        self,
        supplier_code: str,
        tax_id: str | None,
        payment_terms_days: int,
    ) -> InvariantResult:
        result = InvariantResult(True)
        existing_codes = self._supplier_code_checker()  # synchronous, no await
        result.merge(
            self._supplier_invariants.validate_supplier_code_unique(supplier_code, existing_codes)
        )

        if tax_id:
            existing_tax_ids = self._tax_id_checker()  # synchronous, no await
            result.merge(self._supplier_invariants.validate_tax_id_unique(tax_id, existing_tax_ids))

        result.merge(self._supplier_invariants.validate_payment_terms(payment_terms_days))
        return result

    async def enforce_employee_create(
        self,
        employee_number: str,
        email: str | None,
        tax_id: str | None,
        birth_date: datetime | None,
        join_date: datetime,
        basic_salary: Decimal,
    ) -> InvariantResult:
        result = InvariantResult(True)

        existing_numbers = self._employee_number_checker()  # synchronous, no await
        result.merge(
            self._employee_invariants.validate_employee_number_unique(
                employee_number, existing_numbers
            )
        )

        if email:
            existing_emails = self._email_checker()  # synchronous, no await
            result.merge(self._customer_invariants.validate_email_unique(email, existing_emails))

        if tax_id:
            existing_tax_ids = self._tax_id_checker()  # synchronous, no await
            result.merge(self._supplier_invariants.validate_tax_id_unique(tax_id, existing_tax_ids))

        result.merge(self._employee_invariants.validate_birth_date(birth_date, join_date))
        result.merge(self._employee_invariants.validate_basic_salary(basic_salary))

        return result


# === 6. EXPORTS ===

__all__ = [
    "CustomerInvariants",
    "EmployeeInvariants",
    "InvariantResult",
    "MasterDataInvariantEnforcer",
    "SupplierInvariants",
]
