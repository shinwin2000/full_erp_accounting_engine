#!/usr/bin/env python3
"""
Module: hr_to_payroll.py
Layer: Transformers
Responsibility: Mentransformasi event dari sistem HR (Employee Master, Attendance,
               Leave Request, Overtime Approval) menjadi command untuk menjalankan
               proses payroll.

Metode yang ditambahkan:
- BaseTransformer dengan entity dasar: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk PayrollCalculator, HRToPayrollTransformer.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from application.commands_cqrs.command_bus_unified import UnifiedCommandBus
from application.service_layer.service_payroll import PayrollService
from application.service_layer.service_tax import TaxService
from bootstrap.dependency_container.ioc_container import get_container
from domain.payroll.aggregate_root import PayrollAggregate as PayrollRun
from domain.payroll.tax_withholding_engine import TaxWithholdingEngine
from infrastructure.telemetry.alert_manager_router import trigger_alert
from infrastructure.telemetry.structured_json_logging import get_logger
from ports.primary.employee_repository_port import EmployeeRepositoryPort
from ports.primary.payroll_repository_port import PayrollRepositoryPort

if TYPE_CHECKING:
    from event_gateway.event_gate_singleton import EventEnvelope

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================
DEFAULT_CURRENCY = "IDR"
DEFAULT_SALARY_EXPENSE_ACCOUNT = "5-2100"
DEFAULT_BONUS_EXPENSE_ACCOUNT = "5-2110"
DEFAULT_BENEFIT_EXPENSE_ACCOUNT = "5-2120"
DEFAULT_TAX_PAYABLE_ACCOUNT = "2-3100"
DEFAULT_SALARY_PAYABLE_ACCOUNT = "2-2100"
DEFAULT_BANK_ACCOUNT = "1-1100"

BPJS_KETENAGAKERJAAN_RATE_JKK = Decimal("0.0024")
BPJS_KETENAGAKERJAAN_RATE_JKM = Decimal("0.0030")
BPJS_KETENAGAKERJAAN_RATE_JHT_EMPLOYER = Decimal("0.0370")
BPJS_KETENAGAKERJAAN_RATE_JHT_EMPLOYEE = Decimal("0.0200")
BPJS_KESEHATAN_RATE_EMPLOYER = Decimal("0.0400")
BPJS_KESEHATAN_RATE_EMPLOYEE = Decimal("0.0100")

PPh21_BRACKETS = [
    (0, 60000000, Decimal("0.05")),
    (60000000, 250000000, Decimal("0.15")),
    (250000000, 500000000, Decimal("0.25")),
    (500000000, 5000000000, Decimal("0.30")),
    (5000000000, float("inf"), Decimal("0.35")),
]

PTKP_AMOUNTS = {
    "TK/0": 54000000,
    "TK/1": 58500000,
    "TK/2": 63000000,
    "TK/3": 67500000,
    "K/0": 58500000,
    "K/1": 63000000,
    "K/2": 67500000,
    "K/3": 72000000,
}

HANDLED_EVENT_TYPES = [
    "PayrollPeriodOpen",
    "EmployeeActivated",
    "AttendanceRecorded",
    "OvertimeApproved",
    "LeaveApproved",
    "BonusApproved",
    "MonthlyPayrollTrigger",
]


# ============================================================================
# BaseTransformer (sama seperti sebelumnya, tetapi untuk menghindari duplikasi kita definisikan ulang)
# ============================================================================
class BaseTransformer:
    def __init__(self, name: str):
        self.name = name
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._transformer_id = str(uuid4())

    def _take_snapshot(self):
        import datetime

        self._snapshots.append(
            {
                "version": self._version,
                "transformer_id": self._transformer_id,
                "name": self.name,
                "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        import datetime

        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
                "version": self._version,
                "transformer_id": self._transformer_id,
                "details": details,
            }
        )

    def validate(self) -> dict[str, Any]:
        return {"is_valid": True, "errors": []}

    def to_dict(self) -> dict[str, Any]:
        return {"transformer_id": self._transformer_id, "name": self.name, "version": self._version}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BaseTransformer:
        instance = cls(data["name"])
        instance._version = data.get("version", 1)
        instance._transformer_id = data.get("transformer_id", str(uuid4()))
        return instance

    def clone(self) -> BaseTransformer:
        new = self.__class__(self.name)
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self._transformer_id})
        return new

    def snapshot(self) -> dict[str, Any]:
        import datetime

        return {
            "version": self._version,
            "transformer_id": self._transformer_id,
            "name": self.name,
            "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> BaseTransformer:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# ============================================================================
# EXCEPTIONS
# ============================================================================
class HRToPayrollTransformerError(Exception):
    pass


class EmployeeNotFoundError(HRToPayrollTransformerError):
    pass


class PayrollPeriodClosedError(HRToPayrollTransformerError):
    pass


class TaxCalculationError(HRToPayrollTransformerError):
    pass


# ============================================================================
# PayrollCalculator (dengan entity dasar)
# ============================================================================
class PayrollCalculator(BaseTransformer):
    def __init__(self):
        super().__init__("PayrollCalculator")
        self._tax_engine = TaxWithholdingEngine()

    async def calculate_employee_payroll(
        self, employee_data: dict[str, Any], period_year: int, period_month: int
    ) -> dict[str, Any]:
        basic_salary = Decimal(str(employee_data.get("basic_salary", 0)))
        days_present = employee_data.get("days_present", 20)
        total_work_days = 20
        salary_ratio = days_present / total_work_days
        prorated_salary = basic_salary * salary_ratio
        overtime_hours = Decimal(str(employee_data.get("overtime_hours", 0)))
        overtime_pay = overtime_hours * (basic_salary / 173) * Decimal("1.5")
        allowances = Decimal(str(employee_data.get("allowances", 0)))
        bonus = Decimal(str(employee_data.get("bonus", 0)))
        deductions = Decimal(str(employee_data.get("deductions", 0)))
        bpjs_jkk = basic_salary * BPJS_KETENAGAKERJAAN_RATE_JKK
        bpjs_jkm = basic_salary * BPJS_KETENAGAKERJAAN_RATE_JKM
        bpjs_jht_employer = basic_salary * BPJS_KETENAGAKERJAAN_RATE_JHT_EMPLOYER
        bpjs_jht_employee = basic_salary * BPJS_KETENAGAKERJAAN_RATE_JHT_EMPLOYEE
        bpjs_kesehatan_employer = basic_salary * BPJS_KESEHATAN_RATE_EMPLOYER
        bpjs_kesehatan_employee = basic_salary * BPJS_KESEHATAN_RATE_EMPLOYEE
        gross_income = prorated_salary + overtime_pay + allowances + bonus
        tax_pph21 = await self._calculate_pph21(
            employee_data=employee_data,
            monthly_gross=gross_income,
            period_year=period_year,
            period_month=period_month,
            bpjs_deductions=bpjs_jht_employee + bpjs_kesehatan_employee,
        )
        total_deductions = deductions + tax_pph21 + bpjs_jht_employee + bpjs_kesehatan_employee
        net_salary = gross_income - total_deductions
        return {
            "employee_id": employee_data.get("employee_id"),
            "employee_code": employee_data.get("employee_code"),
            "employee_name": employee_data.get("employee_name"),
            "basic_salary": basic_salary,
            "prorated_salary": prorated_salary,
            "overtime_pay": overtime_pay,
            "allowances": allowances,
            "bonus": bonus,
            "gross_income": gross_income,
            "deductions": deductions,
            "bpjs_jht_employee": bpjs_jht_employee,
            "bpjs_kesehatan_employee": bpjs_kesehatan_employee,
            "tax_pph21": tax_pph21,
            "total_deductions": total_deductions,
            "net_salary": net_salary,
            "employer_bpjs": {
                "jkk": bpjs_jkk,
                "jkm": bpjs_jkm,
                "jht": bpjs_jht_employer,
                "kesehatan": bpjs_kesehatan_employer,
            },
        }

    async def _calculate_pph21(
        self,
        employee_data: dict[str, Any],
        monthly_gross: Decimal,
        period_year: int,
        period_month: int,
        bpjs_deductions: Decimal,
    ) -> Decimal:
        ptkp_status = employee_data.get("ptkp_status", "TK/0")
        ptkp_annual = PTKP_AMOUNTS.get(ptkp_status, 54000000)
        previous_months_gross = employee_data.get("ytd_gross_income", 0)
        ytd_gross = previous_months_gross + float(monthly_gross)
        annualized_gross = (ytd_gross / period_month) * 12 if period_month > 0 else 0
        taxable_income = max(0, annualized_gross - ptkp_annual)
        annual_tax = Decimal(0)
        remaining = taxable_income
        for lower, upper, rate in PPh21_BRACKETS:
            if remaining <= 0:
                break
            bracket_amount = (
                min(remaining, Decimal(str(upper - lower))) if upper != float("inf") else remaining
            )
            annual_tax += Decimal(str(bracket_amount)) * rate
            remaining -= Decimal(str(bracket_amount))
        monthly_tax = annual_tax / 12
        tax_paid_ytd = employee_data.get("tax_paid_ytd", 0)
        current_month_tax = max(0, monthly_tax - Decimal(str(tax_paid_ytd)))
        return current_month_tax

    def validate(self) -> dict[str, Any]:
        return {"is_valid": True, "errors": []}

    def to_dict(self) -> dict[str, Any]:
        return super().to_dict()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PayrollCalculator:
        instance = cls()
        instance._version = data.get("version", 1)
        instance._transformer_id = data.get("transformer_id", str(uuid4()))
        return instance

    def clone(self) -> PayrollCalculator:
        new = PayrollCalculator()
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self._transformer_id})
        return new


# ============================================================================
# HRToPayrollTransformer (dengan entity dasar)
# ============================================================================
class HRToPayrollTransformer(BaseTransformer):
    def __init__(self):
        super().__init__("HRToPayrollTransformer")
        self._command_bus: UnifiedCommandBus | None = None
        self._payroll_service: PayrollService | None = None
        self._tax_service: TaxService | None = None
        self._employee_repo: EmployeeRepositoryPort | None = None
        self._payroll_repo: PayrollRepositoryPort | None = None
        self._calculator = PayrollCalculator()
        self._processed_events: set = set()

    async def _get_command_bus(self) -> UnifiedCommandBus:
        if self._command_bus is None:
            container = get_container()
            self._command_bus = container.resolve(UnifiedCommandBus)
        return self._command_bus

    async def _get_payroll_service(self) -> PayrollService:
        if self._payroll_service is None:
            container = get_container()
            self._payroll_service = container.resolve(PayrollService)
        return self._payroll_service

    async def _get_tax_service(self) -> TaxService:
        if self._tax_service is None:
            container = get_container()
            self._tax_service = container.resolve(TaxService)
        return self._tax_service

    async def _get_employee_repo(self) -> EmployeeRepositoryPort:
        if self._employee_repo is None:
            container = get_container()
            self._employee_repo = container.resolve(EmployeeRepositoryPort)
        return self._employee_repo

    async def _get_payroll_repo(self) -> PayrollRepositoryPort:
        if self._payroll_repo is None:
            container = get_container()
            self._payroll_repo = container.resolve(PayrollRepositoryPort)
        return self._payroll_repo

    async def transform(self, envelope: EventEnvelope) -> None:
        event_type = envelope.event_type
        event_id = str(envelope.id)
        event_payload = envelope.payload

        if event_id in self._processed_events:
            logger.debug(f"Event {event_id} already processed, skipping")
            return
        if event_type not in HANDLED_EVENT_TYPES:
            logger.debug(f"Event type {event_type} not handled")
            return

        logger.info(f"Transforming event {event_type} to payroll command")
        try:
            if event_type == "MonthlyPayrollTrigger":
                await self._process_monthly_payroll(event_payload, envelope)
            elif event_type == "EmployeeActivated":
                await self._sync_employee(event_payload, envelope)
            elif event_type in [
                "AttendanceRecorded",
                "OvertimeApproved",
                "LeaveApproved",
                "BonusApproved",
            ]:
                await self._update_payroll_component(event_type, event_payload, envelope)
            self._processed_events.add(event_id)
        except Exception as e:
            logger.exception(f"Failed to transform event {event_id}: {e}")
            await trigger_alert(
                title="HR to Payroll Transformation Failed",
                message=f"Error: {str(e)[:200]}",
                severity="error",
                source="HRToPayrollTransformer",
            )
            raise

    async def _process_monthly_payroll(
        self, payload: dict[str, Any], envelope: EventEnvelope
    ) -> None:
        fiscal_year = payload.get("fiscal_year", datetime.now().year)
        period_month = payload.get("period_month", datetime.now().month)
        legal_entity_id = (
            UUID(payload.get("legal_entity_id"))
            if payload.get("legal_entity_id")
            else envelope.metadata.get("legal_entity_id")
        )
        is_closed = await self._is_period_closed(fiscal_year, period_month, legal_entity_id)
        if is_closed:
            raise PayrollPeriodClosedError(
                f"Payroll period {fiscal_year}-{period_month:02d} is already closed"
            )
        employees = await self._get_active_employees(legal_entity_id)
        if not employees:
            logger.warning(f"No active employees found for period {fiscal_year}-{period_month:02d}")
            return
        payroll_results = []
        total_net_salary = Decimal(0)
        total_tax = Decimal(0)
        for emp in employees:
            attendance_data = await self._get_attendance_data(
                emp["employee_id"], fiscal_year, period_month
            )
            overtime_data = await self._get_overtime_data(
                emp["employee_id"], fiscal_year, period_month
            )
            leave_data = await self._get_leave_data(emp["employee_id"], fiscal_year, period_month)
            bonus_data = await self._get_bonus_data(emp["employee_id"], fiscal_year, period_month)
            employee_payload = {
                **emp,
                "days_present": attendance_data.get("days_present", 20),
                "days_absent": attendance_data.get("days_absent", 0),
                "days_leave": leave_data.get("days_taken", 0),
                "overtime_hours": overtime_data.get("total_hours", 0),
                "bonus": bonus_data.get("amount", 0),
                "ytd_gross_income": await self._get_ytd_gross_income(
                    emp["employee_id"], fiscal_year, period_month
                ),
                "tax_paid_ytd": await self._get_tax_paid_ytd(
                    emp["employee_id"], fiscal_year, period_month
                ),
            }
            result = await self._calculator.calculate_employee_payroll(
                employee_payload, fiscal_year, period_month
            )
            payroll_results.append(result)
            total_net_salary += result["net_salary"]
            total_tax += result["tax_pph21"]
        payroll_run_id = uuid4()
        payroll_run = PayrollRun(
            id=payroll_run_id,
            period_year=fiscal_year,
            period_month=period_month,
            legal_entity_id=legal_entity_id,
            total_employees=len(payroll_results),
            total_net_salary=total_net_salary,
            total_tax=total_tax,
            status="calculated",
            created_at=datetime.now(UTC),
        )
        payroll_repo = await self._get_payroll_repo()
        await payroll_repo.save_payroll_run(payroll_run, payroll_results)
        await self._create_payroll_journal(payroll_run_id, payroll_results, legal_entity_id)
        logger.info(f"Payroll run {payroll_run_id} completed for {len(payroll_results)} employees")
        await self._trigger_payment_command(payroll_run_id, total_net_salary, legal_entity_id)

    async def _create_payroll_journal(
        self, payroll_run_id: UUID, payroll_results: list[dict], legal_entity_id: UUID
    ) -> None:
        from application.dto_objects.journal_request import JournalCreateRequest, JournalLineRequest

        journal_lines = []
        total_salary_expense = sum(r["gross_income"] for r in payroll_results)
        total_tax_payable = sum(r["tax_pph21"] for r in payroll_results)
        total_net_salary = sum(r["net_salary"] for r in payroll_results)
        total_employer_bpjs = sum(
            r["employer_bpjs"]["jht"]
            + r["employer_bpjs"]["kesehatan"]
            + r["employer_bpjs"]["jkk"]
            + r["employer_bpjs"]["jkm"]
            for r in payroll_results
        )
        journal_lines.append(
            JournalLineRequest(
                account_code=DEFAULT_SALARY_EXPENSE_ACCOUNT,
                debit_amount=total_salary_expense,
                credit_amount=Decimal(0),
                description="Payroll expense for period",
            )
        )
        journal_lines.append(
            JournalLineRequest(
                account_code=DEFAULT_BENEFIT_EXPENSE_ACCOUNT,
                debit_amount=total_employer_bpjs,
                credit_amount=Decimal(0),
                description="Employer BPJS expense",
            )
        )
        journal_lines.append(
            JournalLineRequest(
                account_code=DEFAULT_TAX_PAYABLE_ACCOUNT,
                debit_amount=Decimal(0),
                credit_amount=total_tax_payable,
                description="PPh 21 payable",
            )
        )
        journal_lines.append(
            JournalLineRequest(
                account_code=DEFAULT_SALARY_PAYABLE_ACCOUNT,
                debit_amount=Decimal(0),
                credit_amount=total_net_salary,
                description="Net salary payable",
            )
        )
        create_request = JournalCreateRequest(
            journal_date=datetime.now(UTC).date(),
            description=f"Payroll Journal - Run {payroll_run_id}",
            lines=journal_lines,
            reference_number=str(payroll_run_id),
            source_type="payroll",
            source_id=str(payroll_run_id),
            created_by=UUID("00000000-0000-0000-0000-000000000000"),
            legal_entity_id=legal_entity_id,
        )
        command_bus = await self._get_command_bus()
        await command_bus.dispatch({"type": "journal.create", "data": create_request.to_dict()})

    async def _trigger_payment_command(
        self, payroll_run_id: UUID, total_net_salary: Decimal, legal_entity_id: UUID
    ) -> None:
        command_bus = await self._get_command_bus()
        await command_bus.dispatch(
            {
                "type": "payment.create",
                "data": {
                    "payroll_run_id": str(payroll_run_id),
                    "amount": float(total_net_salary),
                    "payment_date": datetime.now(UTC).date().isoformat(),
                    "payment_method": "bank_transfer",
                    "legal_entity_id": str(legal_entity_id),
                },
            }
        )

    async def _sync_employee(self, payload: dict[str, Any], envelope: EventEnvelope) -> None:
        employee_id = UUID(payload.get("employee_id"))
        legal_entity_id = (
            UUID(payload.get("legal_entity_id"))
            if payload.get("legal_entity_id")
            else envelope.metadata.get("legal_entity_id")
        )
        employee_repo = await self._get_employee_repo()
        employee = await employee_repo.get_by_id(employee_id)
        if employee:
            payroll_service = await self._get_payroll_service()
            await payroll_service.sync_employee(employee, legal_entity_id)
            logger.info(f"Employee {employee.employee_code} synced to payroll")

    async def _update_payroll_component(
        self, event_type: str, payload: dict[str, Any], envelope: EventEnvelope
    ) -> None:
        employee_id = UUID(payload.get("employee_id"))
        period_year = payload.get("fiscal_year", datetime.now().year)
        period_month = payload.get("period_month", datetime.now().month)
        legal_entity_id = (
            UUID(payload.get("legal_entity_id"))
            if payload.get("legal_entity_id")
            else envelope.metadata.get("legal_entity_id")
        )
        component_type = {
            "AttendanceRecorded": "attendance",
            "OvertimeApproved": "overtime",
            "LeaveApproved": "leave",
            "BonusApproved": "bonus",
        }.get(event_type, "unknown")
        if component_type != "unknown":
            payroll_service = await self._get_payroll_service()
            await payroll_service.update_payroll_component(
                employee_id=employee_id,
                component_type=component_type,
                data=payload,
                period_year=period_year,
                period_month=period_month,
                legal_entity_id=legal_entity_id,
            )
            logger.info(f"Payroll component {component_type} updated for employee {employee_id}")

    async def _get_active_employees(self, legal_entity_id: UUID) -> list[dict[str, Any]]:
        employee_repo = await self._get_employee_repo()
        employees = await employee_repo.find_active_for_payroll(
            datetime.now().date(), legal_entity_id
        )
        return [
            {
                "employee_id": emp.id,
                "employee_code": emp.employee_code,
                "employee_name": emp.full_name,
                "basic_salary": float(emp.basic_salary.amount) if emp.basic_salary else 0,
                "allowances": float(emp.allowances.amount) if emp.allowances else 0,
                "ptkp_status": emp.tax_status or "TK/0",
                "npwp": str(emp.npwp) if emp.npwp else None,
            }
            for emp in employees
        ]

    async def _get_attendance_data(
        self, employee_id: UUID, fiscal_year: int, period_month: int
    ) -> dict[str, Any]:
        payroll_service = await self._get_payroll_service()
        return await payroll_service.get_attendance_summary(employee_id, fiscal_year, period_month)

    async def _get_overtime_data(
        self, employee_id: UUID, fiscal_year: int, period_month: int
    ) -> dict[str, Any]:
        payroll_service = await self._get_payroll_service()
        return await payroll_service.get_overtime_summary(employee_id, fiscal_year, period_month)

    async def _get_leave_data(
        self, employee_id: UUID, fiscal_year: int, period_month: int
    ) -> dict[str, Any]:
        payroll_service = await self._get_payroll_service()
        return await payroll_service.get_leave_summary(employee_id, fiscal_year, period_month)

    async def _get_bonus_data(
        self, employee_id: UUID, fiscal_year: int, period_month: int
    ) -> dict[str, Any]:
        payroll_service = await self._get_payroll_service()
        return await payroll_service.get_bonus_summary(employee_id, fiscal_year, period_month)

    async def _get_ytd_gross_income(
        self, employee_id: UUID, fiscal_year: int, current_month: int
    ) -> Decimal:
        payroll_service = await self._get_payroll_service()
        return await payroll_service.get_ytd_gross_income(employee_id, fiscal_year, current_month)

    async def _get_tax_paid_ytd(
        self, employee_id: UUID, fiscal_year: int, current_month: int
    ) -> Decimal:
        payroll_service = await self._get_payroll_service()
        return await payroll_service.get_tax_paid_ytd(employee_id, fiscal_year, current_month)

    async def _is_period_closed(
        self, fiscal_year: int, period_month: int, legal_entity_id: UUID
    ) -> bool:
        payroll_repo = await self._get_payroll_repo()
        return await payroll_repo.is_period_closed(fiscal_year, period_month, legal_entity_id)

    async def reset(self) -> None:
        self._processed_events.clear()
        self._version += 1
        logger.info("HRToPayrollTransformer reset")

    def validate(self) -> dict[str, Any]:
        errors = []
        if self._calculator is None:
            errors.append("Calculator not initialized")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["processed_events_count"] = len(self._processed_events)
        data["calculator"] = self._calculator.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HRToPayrollTransformer:
        instance = cls()
        instance._version = data.get("version", 1)
        instance._transformer_id = data.get("transformer_id", str(uuid4()))
        if "calculator" in data:
            instance._calculator = PayrollCalculator.from_dict(data["calculator"])
        return instance

    def clone(self) -> HRToPayrollTransformer:
        new = HRToPayrollTransformer()
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self._transformer_id})
        return new

    def snapshot(self) -> dict[str, Any]:
        snap = super().snapshot()
        snap["processed_events_count"] = len(self._processed_events)
        return snap

    def touch(self, touched_by: str) -> HRToPayrollTransformer:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# ============================================================================
# TRANSFORMER FACTORY & EVENT HANDLER
# ============================================================================
_hr_to_payroll_transformer: HRToPayrollTransformer | None = None


async def get_hr_to_payroll_transformer() -> HRToPayrollTransformer:
    global _hr_to_payroll_transformer
    if _hr_to_payroll_transformer is None:
        _hr_to_payroll_transformer = HRToPayrollTransformer()
    return _hr_to_payroll_transformer


async def handle_hr_event(envelope: EventEnvelope) -> None:
    transformer = await get_hr_to_payroll_transformer()
    await transformer.transform(envelope)


__all__ = [
    "EmployeeNotFoundError",
    "HRToPayrollTransformer",
    "HRToPayrollTransformerError",
    "PayrollPeriodClosedError",
    "TaxCalculationError",
    "get_hr_to_payroll_transformer",
    "handle_hr_event",
]
