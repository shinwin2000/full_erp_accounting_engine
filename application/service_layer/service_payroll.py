# service_payroll.py - Complete rewrite with full event publishing

#!/usr/bin/env python3

"""
Module: service_payroll.py

Layer: 8 - Application / Service Layer

Responsibility:
    Service layer untuk Payroll Management.
    Mempublikasikan semua domain events yang sesuai.
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from domain.payroll.aggregate_root import PayrollAggregate
from domain.payroll.domain_events import (
    EmployeeStructureUpdated,
    PayrollRunApproved,
    PayrollRunCancelled,
    PayrollRunCreated,
    PayrollRunPaid,
    PayrollRunPosted,
    PayrollRunProcessed,
    PayslipGenerated,
    PayslipSentToEmployee,
    SalaryComponentAdded,
)
from domain.payroll.employee_salary_structure_vo import EmployeeSalaryStructure, SalaryComponentType
from domain.payroll.invariants import PayrollInvariantsValidator
from domain.payroll.payroll_run_entity import PayrollFrequency, PayrollRun, PayrollRunStatus
from domain.payroll.payslip_projection import Payslip
from domain.payroll.salary_component_entity import SalaryComponent
from domain.payroll.tax_withholding_engine import TaxWithholdingEngine
from ports.primary.employee_repository_port import EmployeeRepositoryPort
from ports.primary.event_publisher_port import EventPublisherPort
from ports.primary.ledger_repository_port import LedgerRepositoryPort
from ports.primary.payroll_repository_port import PayrollRepositoryPort
from ports.primary.unit_of_work_port import UnitOfWorkPort

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class PayrollFrequencyEnum(str, Enum):
    """Frequency of payroll."""

    MONTHLY = "MONTHLY"
    SEMI_MONTHLY = "SEMI_MONTHLY"
    WEEKLY = "WEEKLY"
    DAILY = "DAILY"


class PayrollStatusEnum(str, Enum):
    """Status of payroll run."""

    DRAFT = "draft"
    PROCESSED = "processed"
    APPROVED = "approved"
    PAID = "paid"
    POSTED = "posted"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


# ============================================================================
# DTOs
# ============================================================================


@dataclass(kw_only=True)
class EmployeeSalaryStructureDTO:
    """DTO for employee salary structure."""

    employee_id: UUID
    basic_salary: Decimal
    position_allowance: Decimal = Decimal("0")
    transport_allowance: Decimal = Decimal("0")
    meal_allowance: Decimal = Decimal("0")
    overtime_rate: Decimal = Decimal("0")
    bpjs_kesehatan_employee: Decimal | None = None
    bpjs_kesehatan_employer: Decimal | None = None
    bpjs_ketenagakerjaan_employee: Decimal | None = None
    bpjs_ketenagakerjaan_employer: Decimal | None = None
    other_deductions: dict[str, Decimal] = field(default_factory=dict)


@dataclass(kw_only=True)
class PayrollRunRequest:
    """Request to create payroll run."""

    legal_entity_id: UUID
    period_month: int
    period_year: int
    frequency: str = "MONTHLY"
    employee_ids: list[UUID] | None = None
    auto_post_to_gl: bool = True


@dataclass(kw_only=True)
class PayrollRunResponse:
    """Response for payroll run."""

    payroll_run_id: UUID
    period: str
    frequency: str
    employee_count: int
    total_gross_pay: Decimal
    total_deductions: Decimal
    total_net_pay: Decimal
    total_tax_withheld: Decimal
    status: str
    generated_at: datetime


@dataclass(kw_only=True)
class PayslipResponse:
    """Response for payslip."""

    payslip_id: UUID
    employee_id: UUID
    employee_name: str
    payroll_run_id: UUID
    gross_pay: Decimal
    total_deductions: Decimal
    net_pay: Decimal
    tax_withheld: Decimal
    components: list[dict[str, Any]]
    generated_at: datetime
    sent_at: datetime | None = None


@dataclass(kw_only=True)
class PayrollPostingResponse:
    """Response for payroll posting."""

    payroll_run_id: UUID
    posted_to_gl: bool
    journal_id: UUID | None = None
    posting_errors: list[str] = field(default_factory=list)


@dataclass(kw_only=True)
class SalaryComponentRequest:
    """Request to add salary component."""

    employee_id: UUID
    component_type: str
    amount: Decimal
    description: str
    effective_date: date | None = None


# ============================================================================
# Exceptions
# ============================================================================


class PayrollServiceError(Exception):
    pass


class EmployeeNotFoundError(PayrollServiceError):
    pass


class PayrollRunNotFoundError(PayrollServiceError):
    pass


class PayrollRunAlreadyProcessedError(PayrollServiceError):
    pass


class TaxCalculationError(PayrollServiceError):
    pass


# ============================================================================
# Main Service
# ============================================================================


class PayrollService:
    """
    Service untuk penggajian.
    """

    def __init__(
        self,
        payroll_repo: PayrollRepositoryPort,
        employee_repo: EmployeeRepositoryPort,
        ledger_repo: LedgerRepositoryPort | None = None,
        uow: UnitOfWorkPort | None = None,
        event_publisher: EventPublisherPort | None = None,
    ):
        if payroll_repo is None:
            raise ValueError("payroll_repo is required")
        if employee_repo is None:
            raise ValueError("employee_repo is required")

        self._payroll_repo = payroll_repo
        self._employee_repo = employee_repo
        self._ledger_repo = ledger_repo
        self._uow = uow
        self._event_publisher = event_publisher
        self._tax_engine = TaxWithholdingEngine()
        self._validator = PayrollInvariantsValidator()
        self._stats = {"payroll_runs": 0, "payslips_generated": 0, "journals_posted": 0}

        logger.info("PayrollService initialized")

    # ========================================================================
    # Employee Salary Structure
    # ========================================================================

    async def set_employee_salary_structure(
        self,
        employee_id: UUID,
        structure: EmployeeSalaryStructureDTO,
        user_id: UUID,
        effective_date: date | None = None,
        correlation_id: str | None = None,
    ) -> None:
        """Set or update employee salary structure."""
        employee = await self._employee_repo.get_by_id(employee_id)
        if not employee:
            raise EmployeeNotFoundError(f"Employee {employee_id} not found")

        # Get old structure for event
        old_structure = await self._payroll_repo.get_salary_structure(
            employee_id, effective_date or date.today()
        )
        old_basic = old_structure.basic_salary if old_structure else Decimal("0")

        effective_date = effective_date or date.today()
        salary_structure = EmployeeSalaryStructure(
            employee_id=employee_id,
            effective_date=effective_date,
            basic_salary=structure.basic_salary,
            position_allowance=structure.position_allowance,
            transport_allowance=structure.transport_allowance,
            meal_allowance=structure.meal_allowance,
            overtime_rate=structure.overtime_rate,
            bpjs_kesehatan_employee=structure.bpjs_kesehatan_employee,
            bpjs_kesehatan_employer=structure.bpjs_kesehatan_employer,
            bpjs_ketenagakerjaan_employee=structure.bpjs_ketenagakerjaan_employee,
            bpjs_ketenagakerjaan_employer=structure.bpjs_ketenagakerjaan_employer,
            other_deductions=structure.other_deductions,
            created_by=user_id,
            created_at=datetime.utcnow(),
        )
        await self._payroll_repo.save_salary_structure(salary_structure)
        if self._uow:
            await self._uow.commit()

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = EmployeeStructureUpdated(
                aggregate_id=employee_id,
                aggregate_version=1,
                employee_id=employee_id,
                employee_name=employee.name,
                old_basic_salary=old_basic,
                new_basic_salary=structure.basic_salary,
                updated_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

        logger.info(f"Salary structure set for employee {employee_id} effective {effective_date}")

    async def get_salary_structure(
        self, employee_id: UUID, as_of_date: date | None = None
    ) -> EmployeeSalaryStructureDTO | None:
        """Get employee salary structure as of date."""
        structure = await self._payroll_repo.get_salary_structure(
            employee_id, as_of_date or date.today()
        )
        if not structure:
            return None

        return EmployeeSalaryStructureDTO(
            employee_id=structure.employee_id,
            basic_salary=structure.basic_salary,
            position_allowance=structure.position_allowance,
            transport_allowance=structure.transport_allowance,
            meal_allowance=structure.meal_allowance,
            overtime_rate=structure.overtime_rate,
            bpjs_kesehatan_employee=structure.bpjs_kesehatan_employee,
            bpjs_kesehatan_employer=structure.bpjs_kesehatan_employer,
            bpjs_ketenagakerjaan_employee=structure.bpjs_ketenagakerjaan_employee,
            bpjs_ketenagakerjaan_employer=structure.bpjs_ketenagakerjaan_employer,
            other_deductions=structure.other_deductions,
        )

    # ========================================================================
    # Salary Component Management
    # ========================================================================

    async def add_salary_component(
        self,
        request: SalaryComponentRequest,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> None:
        """Add a salary component to an employee."""
        employee = await self._employee_repo.get_by_id(request.employee_id)
        if not employee:
            raise EmployeeNotFoundError(f"Employee {request.employee_id} not found")

        component = SalaryComponent(
            id=uuid4(),
            employee_id=request.employee_id,
            component_type=SalaryComponentType(request.component_type),
            amount=request.amount,
            description=request.description,
            effective_date=request.effective_date or date.today(),
            created_by=user_id,
            created_at=datetime.utcnow(),
        )
        await self._payroll_repo.save_salary_component(component)
        if self._uow:
            await self._uow.commit()

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = SalaryComponentAdded(
                aggregate_id=request.employee_id,
                aggregate_version=1,
                component_name=component.description,
                component_type=component.component_type.value,
                amount=component.amount,
                added_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

        logger.info(f"Salary component added for employee {request.employee_id}")

    # ========================================================================
    # Payroll Run
    # ========================================================================

    async def create_payroll_run(
        self, request: PayrollRunRequest, user_id: UUID, correlation_id: str | None = None
    ) -> PayrollRunResponse:
        """Create a new payroll run for the period."""
        # Check if payroll run already exists
        existing = await self._payroll_repo.find_payroll_run(
            request.legal_entity_id, request.period_year, request.period_month
        )
        if existing and existing.status != PayrollRunStatus.CANCELLED:
            raise PayrollRunAlreadyProcessedError(
                f"Payroll run for {request.period_year}-{request.period_month:02d} already exists"
            )

        period_str = f"{request.period_year}-{request.period_month:02d}"

        # Get employees to include
        employee_ids = request.employee_ids
        if not employee_ids:
            employees = await self._employee_repo.list_active_employees(
                request.legal_entity_id, date(request.period_year, request.period_month, 1)
            )
            employee_ids = [e.id for e in employees]

        # Create payroll run aggregate
        payroll_run = PayrollRun(
            id=uuid4(),
            legal_entity_id=request.legal_entity_id,
            period_year=request.period_year,
            period_month=request.period_month,
            frequency=PayrollFrequency(request.frequency),
            status=PayrollRunStatus.DRAFT,
            employee_ids=employee_ids,
            created_by=user_id,
            created_at=datetime.utcnow(),
            processed_at=None,
            posted_to_gl=False,
        )

        aggregate = PayrollAggregate(payroll_run=payroll_run, version=0)
        aggregate.create(user_id)

        await self._payroll_repo.save_payroll_run(aggregate)
        if self._uow:
            await self._uow.commit()

        self._stats["payroll_runs"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = PayrollRunCreated(
                aggregate_id=payroll_run.id,
                aggregate_version=1,
                payroll_run=payroll_run,
                created_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

        logger.info(f"Payroll run created for period {period_str}")
        return await self._to_payroll_run_response(payroll_run)

    async def process_payroll_run(
        self, payroll_run_id: UUID, user_id: UUID, correlation_id: str | None = None
    ) -> PayrollRunResponse:
        """Process payroll run: calculate all components and generate payslips."""
        aggregate = await self._payroll_repo.get_payroll_run(payroll_run_id)
        if not aggregate:
            raise PayrollRunNotFoundError(f"Payroll run {payroll_run_id} not found")

        payroll_run = aggregate.payroll_run
        if payroll_run.status != PayrollRunStatus.DRAFT:
            raise PayrollRunAlreadyProcessedError(f"Payroll run already {payroll_run.status.value}")

        # Calculate for each employee
        payslips = []
        total_gross = Decimal("0")
        total_deductions = Decimal("0")
        total_net = Decimal("0")
        total_tax = Decimal("0")

        for emp_id in payroll_run.employee_ids:
            structure = await self.get_salary_structure(
                emp_id, date(payroll_run.period_year, payroll_run.period_month, 1)
            )
            if not structure:
                logger.warning(f"No salary structure for employee {emp_id}, skipping")
                continue

            employee = await self._employee_repo.get_by_id(emp_id)
            if not employee:
                continue

            # Calculate components
            components = await self._calculate_components(structure, payroll_run)
            payslip = await self._generate_payslip(employee, payroll_run, components, user_id)

            total_gross += payslip.gross_pay
            total_deductions += payslip.total_deductions
            total_net += payslip.net_pay
            total_tax += payslip.tax_withheld
            payslips.append(payslip)
            self._stats["payslips_generated"] += 1

        # Update payroll run
        aggregate.process(total_gross, total_deductions, total_net, total_tax, user_id)
        await self._payroll_repo.save_payroll_run(aggregate)

        for ps in payslips:
            await self._payroll_repo.save_payslip(ps)

        if self._uow:
            await self._uow.commit()

        # --- PUBLISH PROCESSED EVENT ---
        if self._event_publisher:
            event = PayrollRunProcessed(
                aggregate_id=payroll_run_id,
                aggregate_version=1,
                payroll_run=payroll_run,
                calculated_by=str(user_id),
                total_employees=len(payslips),
                total_net=total_net,
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

        # --- PUBLISH PAYSLIP GENERATED EVENTS ---
        if self._event_publisher:
            for ps in payslips:
                employee = await self._employee_repo.get_by_id(ps.employee_id)
                event = PayslipGenerated(
                    aggregate_id=ps.id,
                    aggregate_version=1,
                    payslip=ps,
                    employee_name=employee.name if employee else "Unknown",
                    user_id=str(user_id),
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event, correlation_id=correlation_id)

        logger.info(f"Payroll run {payroll_run_id} processed: {len(payslips)} employees")
        return await self._to_payroll_run_response(payroll_run)

    async def approve_payroll_run(
        self, payroll_run_id: UUID, user_id: UUID, correlation_id: str | None = None
    ) -> PayrollRunResponse:
        """Approve a processed payroll run."""
        aggregate = await self._payroll_repo.get_payroll_run(payroll_run_id)
        if not aggregate:
            raise PayrollRunNotFoundError(f"Payroll run {payroll_run_id} not found")

        payroll_run = aggregate.payroll_run
        if payroll_run.status != PayrollRunStatus.PROCESSED:
            raise PayrollServiceError(f"Cannot approve payroll run in status {payroll_run.status.value}")

        aggregate.approve(user_id)
        await self._payroll_repo.save_payroll_run(aggregate)
        if self._uow:
            await self._uow.commit()

        # --- PUBLISH APPROVED EVENT ---
        if self._event_publisher:
            event = PayrollRunApproved(
                aggregate_id=payroll_run_id,
                aggregate_version=1,
                payroll_run=payroll_run,
                approved_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

        logger.info(f"Payroll run {payroll_run_id} approved")
        return await self._to_payroll_run_response(payroll_run)

    async def pay_payroll_run(
        self, payroll_run_id: UUID, user_id: UUID, correlation_id: str | None = None
    ) -> PayrollRunResponse:
        """Mark payroll run as paid."""
        aggregate = await self._payroll_repo.get_payroll_run(payroll_run_id)
        if not aggregate:
            raise PayrollRunNotFoundError(f"Payroll run {payroll_run_id} not found")

        payroll_run = aggregate.payroll_run
        if payroll_run.status != PayrollRunStatus.APPROVED:
            raise PayrollServiceError(f"Cannot pay payroll run in status {payroll_run.status.value}")

        aggregate.mark_paid(user_id)
        await self._payroll_repo.save_payroll_run(aggregate)
        if self._uow:
            await self._uow.commit()

        # --- PUBLISH PAID EVENT ---
        if self._event_publisher:
            event = PayrollRunPaid(
                aggregate_id=payroll_run_id,
                aggregate_version=1,
                payroll_run=payroll_run,
                paid_by=str(user_id),
                total_paid=payroll_run.total_net_pay,
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

        logger.info(f"Payroll run {payroll_run_id} paid")
        return await self._to_payroll_run_response(payroll_run)

    async def cancel_payroll_run(
        self, payroll_run_id: UUID, reason: str, user_id: UUID, correlation_id: str | None = None
    ) -> None:
        """Cancel a payroll run."""
        aggregate = await self._payroll_repo.get_payroll_run(payroll_run_id)
        if not aggregate:
            raise PayrollRunNotFoundError(f"Payroll run {payroll_run_id} not found")

        payroll_run = aggregate.payroll_run
        if payroll_run.status in (PayrollRunStatus.COMPLETED, PayrollRunStatus.CANCELLED):
            raise PayrollServiceError(f"Cannot cancel payroll run in status {payroll_run.status.value}")

        aggregate.cancel(reason, user_id)
        await self._payroll_repo.save_payroll_run(aggregate)
        if self._uow:
            await self._uow.commit()

        # --- PUBLISH CANCELLED EVENT ---
        if self._event_publisher:
            event = PayrollRunCancelled(
                aggregate_id=payroll_run_id,
                aggregate_version=1,
                payroll_run=payroll_run,
                cancelled_by=str(user_id),
                reason=reason,
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

        logger.info(f"Payroll run {payroll_run_id} cancelled")

    async def _calculate_components(
        self, structure: EmployeeSalaryStructureDTO, payroll_run: PayrollRun
    ) -> list[SalaryComponent]:
        """Calculate all salary components for an employee."""
        components = []

        # Gaji pokok
        components.append(
            SalaryComponent(
                id=uuid4(),
                employee_id=structure.employee_id,
                component_type=SalaryComponentType.BASIC_SALARY,
                amount=structure.basic_salary,
                description="Gaji Pokok",
            )
        )

        # Tunjangan
        if structure.position_allowance > 0:
            components.append(
                SalaryComponent(
                    id=uuid4(),
                    employee_id=structure.employee_id,
                    component_type=SalaryComponentType.ALLOWANCE,
                    amount=structure.position_allowance,
                    description="Tunjangan Jabatan",
                )
            )
        if structure.transport_allowance > 0:
            components.append(
                SalaryComponent(
                    id=uuid4(),
                    employee_id=structure.employee_id,
                    component_type=SalaryComponentType.ALLOWANCE,
                    amount=structure.transport_allowance,
                    description="Tunjangan Transportasi",
                )
            )
        if structure.meal_allowance > 0:
            components.append(
                SalaryComponent(
                    id=uuid4(),
                    employee_id=structure.employee_id,
                    component_type=SalaryComponentType.ALLOWANCE,
                    amount=structure.meal_allowance,
                    description="Tunjangan Makan",
                )
            )

        # Deductions: BPJS
        if structure.bpjs_kesehatan_employee is not None and structure.bpjs_kesehatan_employee > 0:
            components.append(
                SalaryComponent(
                    id=uuid4(),
                    employee_id=structure.employee_id,
                    component_type=SalaryComponentType.DEDUCTION_BPJS_KESEHATAN,
                    amount=structure.bpjs_kesehatan_employee,
                    description="Potongan BPJS Kesehatan",
                )
            )

        if (
            structure.bpjs_ketenagakerjaan_employee is not None
            and structure.bpjs_ketenagakerjaan_employee > 0
        ):
            components.append(
                SalaryComponent(
                    id=uuid4(),
                    employee_id=structure.employee_id,
                    component_type=SalaryComponentType.DEDUCTION_BPJS_KETENAGAKERJAAN,
                    amount=structure.bpjs_ketenagakerjaan_employee,
                    description="Potongan BPJS JHT",
                )
            )

        # Other deductions
        for name, amt in structure.other_deductions.items():
            if amt > 0:
                components.append(
                    SalaryComponent(
                        id=uuid4(),
                        employee_id=structure.employee_id,
                        component_type=SalaryComponentType.OTHER_DEDUCTION,
                        amount=amt,
                        description=name,
                    )
                )

        return components

    async def _generate_payslip(
        self,
        employee: Any,
        payroll_run: PayrollRun,
        components: list[SalaryComponent],
        user_id: UUID,
    ) -> Payslip:
        """Generate payslip for an employee."""
        gross_pay = sum(
            c.amount
            for c in components
            if c.component_type
            in (
                SalaryComponentType.BASIC_SALARY,
                SalaryComponentType.ALLOWANCE,
                SalaryComponentType.OVERTIME,
                SalaryComponentType.BONUS,
            )
        )
        total_deductions = sum(
            c.amount
            for c in components
            if c.component_type
            in (
                SalaryComponentType.DEDUCTION_BPJS_KESEHATAN,
                SalaryComponentType.DEDUCTION_BPJS_KETENAGAKERJAAN,
                SalaryComponentType.TAX_PPH21,
                SalaryComponentType.OTHER_DEDUCTION,
            )
        )

        taxable_income = gross_pay - total_deductions
        tax = await self._tax_engine.calculate_pph21(
            employee_id=employee.id,
            annual_taxable_income=taxable_income * 12,
            period_month=payroll_run.period_month,
            period_year=payroll_run.period_year,
        )
        monthly_tax = (tax / 12).quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)

        if monthly_tax > 0:
            components.append(
                SalaryComponent(
                    id=uuid4(),
                    employee_id=employee.id,
                    component_type=SalaryComponentType.TAX_PPH21,
                    amount=monthly_tax,
                    description="PPh 21",
                )
            )
            total_deductions += monthly_tax

        net_pay = gross_pay - total_deductions

        payslip = Payslip(
            id=uuid4(),
            employee_id=employee.id,
            payroll_run_id=payroll_run.id,
            period_month=payroll_run.period_month,
            period_year=payroll_run.period_year,
            gross_pay=gross_pay,
            total_deductions=total_deductions,
            net_pay=net_pay,
            tax_withheld=monthly_tax,
            components=components,
            generated_at=datetime.utcnow(),
            generated_by=user_id,
            sent_at=None,
        )
        return payslip

    async def post_payroll_to_gl(
        self, payroll_run_id: UUID, user_id: UUID, correlation_id: str | None = None
    ) -> PayrollPostingResponse:
        """Post payroll journal entries to General Ledger."""
        aggregate = await self._payroll_repo.get_payroll_run(payroll_run_id)
        if not aggregate:
            raise PayrollRunNotFoundError(f"Payroll run {payroll_run_id} not found")

        payroll_run = aggregate.payroll_run
        if payroll_run.status != PayrollRunStatus.PAID:
            raise PayrollServiceError("Payroll must be paid before posting to GL")

        if not self._ledger_repo:
            raise PayrollServiceError("LedgerRepository not configured")

        payslips = await self._payroll_repo.get_payslips_by_run(payroll_run_id)
        if not payslips:
            raise PayrollServiceError("No payslips found for this payroll run")

        # Build journal lines
        salary_expense_account = "5-5100"
        salary_payable_account = "2-2000"
        tax_payable_account = "2-2100"
        bpjs_payable_account = "2-2200"

        total_gross = sum(p.gross_pay for p in payslips)
        total_net = sum(p.net_pay for p in payslips)
        total_tax = sum(p.tax_withheld for p in payslips)
        total_bpjs = sum(p.total_deductions - p.tax_withheld for p in payslips)

        lines = [
            {"account_code": salary_expense_account, "debit": total_gross, "credit": Decimal("0")},
            {"account_code": salary_payable_account, "debit": Decimal("0"), "credit": total_net},
            {"account_code": tax_payable_account, "debit": Decimal("0"), "credit": total_tax},
            {"account_code": bpjs_payable_account, "debit": Decimal("0"), "credit": total_bpjs},
        ]

        journal_id = await self._ledger_repo.post_journal(
            legal_entity_id=payroll_run.legal_entity_id,
            journal_date=date(payroll_run.period_year, payroll_run.period_month, 1),
            period=f"{payroll_run.period_year}-{payroll_run.period_month:02d}",
            description=f"Payroll for {payroll_run.period_year}-{payroll_run.period_month:02d}",
            lines=lines,
            source_system="payroll",
            user_id=user_id,
        )

        self._stats["journals_posted"] += 1

        # Update payroll run
        aggregate.mark_posted(journal_id, user_id)
        await self._payroll_repo.save_payroll_run(aggregate)
        if self._uow:
            await self._uow.commit()

        # --- PUBLISH POSTED EVENT ---
        if self._event_publisher:
            event = PayrollRunPosted(
                aggregate_id=payroll_run_id,
                aggregate_version=1,
                payroll_run=payroll_run,
                journal_id=journal_id,
                posted_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

        return PayrollPostingResponse(
            payroll_run_id=payroll_run_id,
            posted_to_gl=True,
            journal_id=journal_id,
            posting_errors=[],
        )

    # ========================================================================
    # Payslip Operations
    # ========================================================================

    async def get_payslip(self, payslip_id: UUID) -> PayslipResponse | None:
        """Get payslip by ID."""
        payslip = await self._payroll_repo.get_payslip(payslip_id)
        if not payslip:
            return None

        employee = await self._employee_repo.get_by_id(payslip.employee_id)
        return self._to_payslip_response(payslip, employee.name if employee else "Unknown")

    async def send_payslip_to_employee(
        self, payslip_id: UUID, user_id: UUID, correlation_id: str | None = None
    ) -> None:
        """Send payslip to employee via email/notification."""
        payslip = await self._payroll_repo.get_payslip(payslip_id)
        if not payslip:
            raise PayrollServiceError(f"Payslip {payslip_id} not found")

        payslip.sent_at = datetime.utcnow()
        await self._payroll_repo.save_payslip(payslip)
        if self._uow:
            await self._uow.commit()

        # --- PUBLISH SENT EVENT ---
        if self._event_publisher:
            event = PayslipSentToEmployee(
                aggregate_id=payslip_id,
                aggregate_version=1,
                payslip_id=payslip_id,
                employee_id=payslip.employee_id,
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

        logger.info(f"Payslip {payslip_id} sent to employee")

    # ========================================================================
    # Reports
    # ========================================================================

    async def generate_payroll_report(
        self, legal_entity_id: UUID, period_year: int, period_month: int, output_format: str = "CSV"
    ) -> str:
        """Generate payroll summary report."""
        payroll_run = await self._payroll_repo.find_payroll_run(
            legal_entity_id, period_year, period_month
        )
        if not payroll_run:
            raise PayrollRunNotFoundError(f"No payroll run for {period_year}-{period_month}")

        payslips = await self._payroll_repo.get_payslips_by_run(payroll_run.id)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Employee ID", "Name", "Gross Pay", "Deductions", "Net Pay", "Tax"])

        for ps in payslips:
            emp = await self._employee_repo.get_by_id(ps.employee_id)
            emp_name = emp.name if emp else "Unknown"
            writer.writerow(
                [
                    str(ps.employee_id),
                    emp_name,
                    float(ps.gross_pay),
                    float(ps.total_deductions),
                    float(ps.net_pay),
                    float(ps.tax_withheld),
                ]
            )

        return output.getvalue()

    # ========================================================================
    # Private Helpers
    # ========================================================================

    async def _to_payroll_run_response(self, payroll_run: PayrollRun) -> PayrollRunResponse:
        return PayrollRunResponse(
            payroll_run_id=payroll_run.id,
            period=f"{payroll_run.period_year}-{payroll_run.period_month:02d}",
            frequency=payroll_run.frequency.value,
            employee_count=len(payroll_run.employee_ids),
            total_gross_pay=payroll_run.total_gross_pay,
            total_deductions=payroll_run.total_deductions,
            total_net_pay=payroll_run.total_net_pay,
            total_tax_withheld=payroll_run.total_tax_withheld,
            status=payroll_run.status.value,
            generated_at=payroll_run.created_at,
        )

    def _to_payslip_response(self, payslip: Payslip, employee_name: str) -> PayslipResponse:
        return PayslipResponse(
            payslip_id=payslip.id,
            employee_id=payslip.employee_id,
            employee_name=employee_name,
            payroll_run_id=payslip.payroll_run_id,
            gross_pay=payslip.gross_pay,
            total_deductions=payslip.total_deductions,
            net_pay=payslip.net_pay,
            tax_withheld=payslip.tax_withheld,
            components=[c.__dict__ for c in payslip.components],
            generated_at=payslip.generated_at,
            sent_at=payslip.sent_at,
        )

    def get_stats(self) -> dict[str, int]:
        """Get service statistics."""
        return self._stats.copy()


# ============================================================================
# Factory
# ============================================================================


async def create_payroll_service(
    payroll_repo: PayrollRepositoryPort,
    employee_repo: EmployeeRepositoryPort,
    ledger_repo: LedgerRepositoryPort | None = None,
    uow: UnitOfWorkPort | None = None,
    event_publisher: EventPublisherPort | None = None,
) -> PayrollService:
    return PayrollService(payroll_repo, employee_repo, ledger_repo, uow, event_publisher)


__all__ = [
    "EmployeeNotFoundError",
    "EmployeeSalaryStructureDTO",
    "PayrollFrequencyEnum",
    "PayrollPostingResponse",
    "PayrollRunAlreadyProcessedError",
    "PayrollRunNotFoundError",
    "PayrollRunRequest",
    "PayrollRunResponse",
    "PayrollService",
    "PayrollServiceError",
    "PayrollStatusEnum",
    "PayslipResponse",
    "SalaryComponentRequest",
    "TaxCalculationError",
    "create_payroll_service",
]