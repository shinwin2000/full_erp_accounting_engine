# domain/payroll/__init__.py
"""Package: domain.payroll - Payroll domain layer.

Exports all public components for payroll bounded context.
"""

from domain.payroll.aggregate_root import PayrollAggregate, PayrollRepository
from domain.payroll.domain_events import (
    DomainEvent,
    DomainEventPublisher,
    DomainEventType,
    EmployeeStructureUpdatedEvent,
    PayrollRunApprovedEvent,
    PayrollRunCalculatedEvent,
    PayrollRunCancelledEvent,
    PayrollRunCreated,
    PayrollRunCreatedEvent,
    PayrollRunPaidEvent,
    PayrollRunPosted,
    PayrollRunPostedEvent,
    PayrollRunProcessed,
    PayslipGenerated,
    PayslipGeneratedEvent,
    PayslipSentToEmployee,
    PayslipSentToEmployeeEvent,
    SalaryComponentAddedEvent,
)
from domain.payroll.employee_salary_structure_vo import (
    EmployeeSalaryStructure,
    EmployeeSalaryStructureVO,
    SalaryComponentType,
)
from domain.payroll.employee_salary_structure_vo import SalaryComponent as SalaryComponentAlias
from domain.payroll.invariants import (
    InvariantResult,
    PayrollInvariantEnforcer,
    PayrollInvariants,
    PayrollInvariantsValidator,
)
from domain.payroll.payroll_run_entity import (
    PayrollEmployeeResult,
    PayrollFrequency,
    PayrollPeriod,
    PayrollRun,
    PayrollRunEntity,
    PayrollRunRepository,
    PayrollRunStatus,
)
from domain.payroll.payslip_projection import Payslip, PayslipProjection, PayslipRepository
from domain.payroll.salary_component_entity import (
    ComponentFrequency,
    ComponentType,
    SalaryComponent,
    SalaryComponentEntity,
    SalaryComponentRepository,
)
from domain.payroll.tax_withholding_engine import TaxWithholdingEngine

__all__ = [
    # Aggregate
    "PayrollAggregate",
    "PayrollRepository",
    # Payroll Run
    "PayrollRunEntity",
    "PayrollRunStatus",
    "PayrollPeriod",
    "PayrollFrequency",
    "PayrollEmployeeResult",
    "PayrollRunRepository",
    "PayrollRun",
    # Salary Component
    "SalaryComponentEntity",
    "ComponentType",
    "ComponentFrequency",
    "SalaryComponent",
    "SalaryComponentRepository",
    # Employee Salary Structure
    "EmployeeSalaryStructureVO",
    "EmployeeSalaryStructure",
    "SalaryComponentAlias",
    "SalaryComponentType",
    # Tax Engine
    "TaxWithholdingEngine",
    # Payslip
    "PayslipProjection",
    "Payslip",
    "PayslipRepository",
    # Domain Events
    "DomainEventType",
    "DomainEvent",
    "PayrollRunCreatedEvent",
    "PayrollRunCalculatedEvent",
    "PayrollRunApprovedEvent",
    "PayrollRunPaidEvent",
    "PayrollRunPostedEvent",
    "PayrollRunCancelledEvent",
    "PayslipGeneratedEvent",
    "PayslipSentToEmployeeEvent",
    "EmployeeStructureUpdatedEvent",
    "SalaryComponentAddedEvent",
    "PayrollRunCreated",
    "PayrollRunProcessed",
    "PayrollRunPosted",
    "PayslipGenerated",
    "PayslipSentToEmployee",
    "DomainEventPublisher",
    # Invariants
    "InvariantResult",
    "PayrollInvariants",
    "PayrollInvariantEnforcer",
    "PayrollInvariantsValidator",
]
