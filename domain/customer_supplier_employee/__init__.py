#!/usr/bin/env python3
from __future__ import annotations

"""
Package: domain.customer_supplier_employee

Customer, Supplier, Employee domain module.

Exports all public classes, enums, value objects, aggregates,
events, invariants, and repository protocols.
"""

from domain.customer_supplier_employee.customer_aggregate_root import (
    CustomerAggregate,
    CustomerAggregateError,
    CustomerAggregateRepository,
    CustomerNotFoundError,
    DuplicateCustomerCodeError,
    DuplicateEmailError,
    DuplicateTaxIdError,
    InvalidCustomerStatusTransitionError,
)
from domain.customer_supplier_employee.customer_credit_limit_vo import (
    CreditLimitReviewOutcome,
    CreditLimitStatus,
    CustomerCreditLimitVO,
)
from domain.customer_supplier_employee.customer_entity import (
    CustomerEntity,
    CustomerEntityRepository,
    CustomerSegment,
    CustomerStatus,
    CustomerType,
    PaymentTerm,
)
from domain.customer_supplier_employee.customer_tax_status_vo import (
    CustomerTaxStatusVO,
)
from domain.customer_supplier_employee.customer_tax_status_vo import (
    TaxRegistrationStatus as TaxStatus,
)
from domain.customer_supplier_employee.domain_events import (
    CustomerBalanceUpdated,
    CustomerBalanceUpdatedEvent,
    CustomerCreated,
    CustomerCreatedEvent,
    CustomerCreditLimitChanged,
    CustomerCreditLimitChangedEvent,
    CustomerStatusChanged,
    CustomerStatusChangedEvent,
    DomainEvent,
    DomainEventPublisher,
    DomainEventType,
    EmployeeBPJSUpdated,
    EmployeeBPJSUpdatedEvent,
    EmployeeCreated,
    EmployeeCreatedEvent,
    EmployeePTKPUpdated,
    EmployeePTKPUpdatedEvent,
    EmployeeResigned,
    EmployeeResignedEvent,
    SupplierCreated,
    SupplierCreatedEvent,
    SupplierPaymentTermsChanged,
    SupplierPaymentTermsChangedEvent,
    SupplierWithholdingCategoryChanged,
    SupplierWithholdingCategoryChangedEvent,
    deserialize_event,
    serialize_event,
)
from domain.customer_supplier_employee.employee_aggregate_root import (
    DuplicateEmployeeNumberError,
    EmployeeAggregate,
    EmployeeAggregateError,
    EmployeeAggregateRepository,
    EmployeeNotFoundError,
    InvalidEmployeeStatusTransitionError,
)
from domain.customer_supplier_employee.employee_bpjs_enrollment_vo import (
    BPJSEmploymentProgram,
    BPJSHealthClass,
    BPJSType,
    EmployeeBPJSEnrollmentVO,
)
from domain.customer_supplier_employee.employee_entity import (
    EmployeeEntity,
    EmployeeEntityRepository,
    EmployeeStatus,
    EmployeeType,
    Gender,
)
from domain.customer_supplier_employee.employee_ptkp_status_vo import (
    EmployeePTKPStatusVO,
    MaritalStatus,
    PTKPCategory,
)
from domain.customer_supplier_employee.invariants import (
    CustomerInvariants,
    EmployeeInvariants,
    InvariantResult,
    MasterDataInvariantEnforcer,
    SupplierInvariants,
)
from domain.customer_supplier_employee.supplier_aggregate_root import (
    DuplicateSupplierCodeError,
    DuplicateSupplierTaxIdError,
    InvalidPaymentTermsError,
    InvalidSupplierStatusTransitionError,
    SupplierAggregate,
    SupplierAggregateError,
    SupplierAggregateRepository,
    SupplierNotFoundError,
)
from domain.customer_supplier_employee.supplier_entity import (
    SupplierEntity,
    SupplierEntityRepository,
    SupplierStatus,
    SupplierType,
)
from domain.customer_supplier_employee.supplier_withholding_category_vo import (
    SupplierWithholdingCategoryVO,
    WithholdingArticle,
    WithholdingRate,
)

__all__ = [
    # Customer
    "CustomerStatus",
    "CustomerType",
    "CustomerSegment",
    "PaymentTerm",
    "CustomerEntity",
    "CustomerEntityRepository",
    "CustomerCreditLimitVO",
    "CreditLimitStatus",
    "CreditLimitReviewOutcome",
    "CustomerTaxStatusVO",
    "TaxStatus",
    "CustomerAggregate",
    "CustomerAggregateRepository",
    "CustomerAggregateError",
    "CustomerNotFoundError",
    "DuplicateCustomerCodeError",
    "DuplicateEmailError",
    "DuplicateTaxIdError",
    "InvalidCustomerStatusTransitionError",
    # Supplier
    "SupplierStatus",
    "SupplierType",
    "SupplierEntity",
    "SupplierEntityRepository",
    "SupplierWithholdingCategoryVO",
    "WithholdingArticle",
    "WithholdingRate",
    "SupplierAggregate",
    "SupplierAggregateRepository",
    "SupplierAggregateError",
    "SupplierNotFoundError",
    "DuplicateSupplierCodeError",
    "DuplicateSupplierTaxIdError",
    "InvalidSupplierStatusTransitionError",
    "InvalidPaymentTermsError",
    # Employee
    "EmployeeStatus",
    "EmployeeType",
    "Gender",
    "EmployeeEntity",
    "EmployeeEntityRepository",
    "EmployeePTKPStatusVO",
    "MaritalStatus",
    "PTKPCategory",
    "EmployeeBPJSEnrollmentVO",
    "BPJSType",
    "BPJSHealthClass",
    "BPJSEmploymentProgram",
    "EmployeeAggregate",
    "EmployeeAggregateRepository",
    "EmployeeAggregateError",
    "EmployeeNotFoundError",
    "DuplicateEmployeeNumberError",
    "InvalidEmployeeStatusTransitionError",
    # Domain Events
    "DomainEventType",
    "DomainEvent",
    "DomainEventPublisher",
    "CustomerCreatedEvent",
    "CustomerCreditLimitChangedEvent",
    "CustomerStatusChangedEvent",
    "CustomerBalanceUpdatedEvent",
    "SupplierCreatedEvent",
    "SupplierPaymentTermsChangedEvent",
    "SupplierWithholdingCategoryChangedEvent",
    "EmployeeCreatedEvent",
    "EmployeeResignedEvent",
    "EmployeePTKPUpdatedEvent",
    "EmployeeBPJSUpdatedEvent",
    "CustomerCreated",
    "CustomerCreditLimitChanged",
    "CustomerStatusChanged",
    "CustomerBalanceUpdated",
    "SupplierCreated",
    "SupplierPaymentTermsChanged",
    "SupplierWithholdingCategoryChanged",
    "EmployeeCreated",
    "EmployeeResigned",
    "EmployeePTKPUpdated",
    "EmployeeBPJSUpdated",
    "deserialize_event",
    "serialize_event",
    # Invariants
    "InvariantResult",
    "CustomerInvariants",
    "SupplierInvariants",
    "EmployeeInvariants",
    "MasterDataInvariantEnforcer",
]
