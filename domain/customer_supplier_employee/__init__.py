#!/usr/bin/env python3
from __future__ import annotations

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

"""
Package: domain.customer_supplier_employee

Customer, Supplier, Employee domain module.

Exports all public classes, enums, value objects, aggregates,
events, invariants, and repository protocols.
"""

__all__ = [
    "BPJSEmploymentProgram",
    "BPJSHealthClass",
    "BPJSType",
    "CreditLimitReviewOutcome",
    "CreditLimitStatus",
    "CustomerAggregate",
    "CustomerAggregateError",
    "CustomerAggregateRepository",
    "CustomerBalanceUpdated",
    "CustomerBalanceUpdatedEvent",
    "CustomerCreated",
    "CustomerCreatedEvent",
    "CustomerCreditLimitChanged",
    "CustomerCreditLimitChangedEvent",
    "CustomerCreditLimitVO",
    "CustomerEntity",
    "CustomerEntityRepository",
    "CustomerInvariants",
    "CustomerNotFoundError",
    "CustomerSegment",
    "CustomerStatus",
    "CustomerStatusChanged",
    "CustomerStatusChangedEvent",
    "CustomerTaxStatusVO",
    "CustomerType",
    "DomainEvent",
    "DomainEventPublisher",
    "DomainEventType",
    "DuplicateCustomerCodeError",
    "DuplicateEmailError",
    "DuplicateEmployeeNumberError",
    "DuplicateSupplierCodeError",
    "DuplicateSupplierTaxIdError",
    "DuplicateTaxIdError",
    "EmployeeAggregate",
    "EmployeeAggregateError",
    "EmployeeAggregateRepository",
    "EmployeeBPJSEnrollmentVO",
    "EmployeeBPJSUpdated",
    "EmployeeBPJSUpdatedEvent",
    "EmployeeCreated",
    "EmployeeCreatedEvent",
    "EmployeeEntity",
    "EmployeeEntityRepository",
    "EmployeeInvariants",
    "EmployeeNotFoundError",
    "EmployeePTKPStatusVO",
    "EmployeePTKPUpdated",
    "EmployeePTKPUpdatedEvent",
    "EmployeeResigned",
    "EmployeeResignedEvent",
    "EmployeeStatus",
    "EmployeeType",
    "Gender",
    "InvalidCustomerStatusTransitionError",
    "InvalidEmployeeStatusTransitionError",
    "InvalidPaymentTermsError",
    "InvalidSupplierStatusTransitionError",
    "InvariantResult",
    "MaritalStatus",
    "MasterDataInvariantEnforcer",
    "PTKPCategory",
    "PaymentTerm",
    "SupplierAggregate",
    "SupplierAggregateError",
    "SupplierAggregateRepository",
    "SupplierCreated",
    "SupplierCreatedEvent",
    "SupplierEntity",
    "SupplierEntityRepository",
    "SupplierInvariants",
    "SupplierNotFoundError",
    "SupplierPaymentTermsChanged",
    "SupplierPaymentTermsChangedEvent",
    "SupplierStatus",
    "SupplierType",
    "SupplierWithholdingCategoryChanged",
    "SupplierWithholdingCategoryChangedEvent",
    "SupplierWithholdingCategoryVO",
    "TaxStatus",
    "WithholdingArticle",
    "WithholdingRate",
    "deserialize_event",
    "serialize_event",
]
