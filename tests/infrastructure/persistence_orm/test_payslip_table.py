# tests/infrastructure/persistence_orm/test_payslip_table.py
# Comprehensive tests for PayslipTable ORM model

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from infrastructure.persistence_orm.payslip_table import PayslipTable


class TestPayslipTable:
    """Tests for the PayslipTable ORM table model."""

    def test_tablename_defined(self):
        """ORM model declares a table name."""
        assert hasattr(PayslipTable, "__tablename__")
        assert isinstance(PayslipTable.__tablename__, str)
        assert len(PayslipTable.__tablename__) > 0

    def test_instantiation(self):
        """ORM model can be instantiated in-memory (without a DB session)."""
        instance = PayslipTable(
            id=uuid4(),
            payslip_number="SLIP-001",
            period_year=2026,
            period_month=7,
            employee_id=uuid4(),
            employee_code="EMP001",
            employee_name="John Doe",
            payroll_run_id=uuid4(),
            basic_salary=Decimal("5000000"),
            allowances=Decimal("1000000"),
            net_pay=Decimal("6000000"),
            status="generated",
        )
        assert isinstance(instance, PayslipTable)
        assert instance.payslip_number == "SLIP-001"
        assert instance.basic_salary == Decimal("5000000")

    # -------------------- Property Tests --------------------
    def test_is_generated(self):
        entry = PayslipTable(status="generated")
        assert entry.is_generated is True
        entry.status = "approved"
        assert entry.is_generated is False

    def test_is_approved(self):
        entry = PayslipTable(status="approved")
        assert entry.is_approved is True
        entry.status = "generated"
        assert entry.is_approved is False

    def test_is_paid(self):
        entry = PayslipTable(status="paid")
        assert entry.is_paid is True
        entry.status = "generated"
        assert entry.is_paid is False

    def test_is_cancelled(self):
        entry = PayslipTable(status="cancelled")
        assert entry.is_cancelled is True
        entry.status = "generated"
        assert entry.is_cancelled is False

    def test_period_display(self):
        entry = PayslipTable(period_year=2026, period_month=7)
        assert entry.period_display == "2026-07"

    def test_total_income(self):
        entry = PayslipTable(
            basic_salary=Decimal("5000000"),
            allowances=Decimal("1000000"),
            overtime=Decimal("500000"),
            bonus=Decimal("200000"),
            thirteenth_month=Decimal("0"),
            other_income=Decimal("100000"),
        )
        assert entry.total_income == Decimal("6800000")

    def test_total_deductions_calc(self):
        entry = PayslipTable(
            tax_pph21=Decimal("200000"),
            bpjs_employment=Decimal("100000"),
            bpjs_health=Decimal("50000"),
            bpjs_pension=Decimal("75000"),
            loan_deduction=Decimal("300000"),
            cooperative_deduction=Decimal("50000"),
            other_deductions=Decimal("25000"),
        )
        assert entry.total_deductions_calc == Decimal("800000")  # 200k+100k+50k+75k+300k+50k+25k

    def test_is_balanced_true(self):
        entry = PayslipTable(
            basic_salary=Decimal("5000000"),
            allowances=Decimal("1000000"),
            net_pay=Decimal("6000000"),
            tax_pph21=Decimal(0),
            bpjs_employment=Decimal(0),
            bpjs_health=Decimal(0),
            bpjs_pension=Decimal(0),
            loan_deduction=Decimal(0),
            cooperative_deduction=Decimal(0),
            other_deductions=Decimal(0),
        )
        assert entry.is_balanced is True

    def test_is_balanced_false(self):
        entry = PayslipTable(
            basic_salary=Decimal("5000000"),
            allowances=Decimal("1000000"),
            net_pay=Decimal("7000000"),  # wrong
            tax_pph21=Decimal(0),
            bpjs_employment=Decimal(0),
            bpjs_health=Decimal(0),
            bpjs_pension=Decimal(0),
            loan_deduction=Decimal(0),
            cooperative_deduction=Decimal(0),
            other_deductions=Decimal(0),
        )
        assert entry.is_balanced is False

    def test_tax_rate_effective_zero_gross(self):
        entry = PayslipTable(gross_income=Decimal(0), tax_pph21=Decimal("100000"))
        assert entry.tax_rate_effective == Decimal(0)

    def test_tax_rate_effective_normal(self):
        entry = PayslipTable(gross_income=Decimal("10000000"), tax_pph21=Decimal("200000"))
        assert entry.tax_rate_effective == Decimal("2.00")  # 200k / 10M * 100 = 2%

    # -------------------- Business Method Tests --------------------
    def test_approve_from_generated(self, fixed_now):
        entry = PayslipTable(
            status="generated",
            payslip_number="SLIP-001",
            version=1,
        )
        approver_id = uuid4()
        with patch("infrastructure.persistence_orm.payslip_table.datetime") as mock_dt:
            mock_dt.utcnow.return_value = fixed_now.replace(tzinfo=None)
            new_entry = entry.approve(approver_id)
        assert new_entry.status == "approved"
        assert new_entry.approved_by == approver_id
        assert new_entry.approved_at == fixed_now.replace(tzinfo=None)
        assert new_entry.version == 2
        # Original entry unchanged
        assert entry.status == "generated"

    def test_approve_from_invalid_status_raises(self):
        entry = PayslipTable(status="approved")
        with pytest.raises(ValueError, match="Cannot approve payslip with status approved"):
            entry.approve(uuid4())

    def test_mark_paid_from_generated(self, fixed_now):
        entry = PayslipTable(
            status="generated",
            version=1,
        )
        payment_date = date(2026, 7, 31)
        payment_ref = "PAY-123"
        run_id = uuid4()
        with patch("infrastructure.persistence_orm.payslip_table.datetime") as mock_dt:
            mock_dt.utcnow.return_value = fixed_now.replace(tzinfo=None)
            new_entry = entry.mark_paid(payment_date, payment_ref, run_id)
        assert new_entry.status == "paid"
        assert new_entry.payment_date == payment_date
        assert new_entry.payment_reference == payment_ref
        assert new_entry.payment_run_id == run_id
        assert new_entry.version == 2

    def test_mark_paid_from_approved(self):
        entry = PayslipTable(status="approved")
        new_entry = entry.mark_paid(date.today())
        assert new_entry.status == "paid"

    def test_mark_paid_from_invalid_status_raises(self):
        entry = PayslipTable(status="cancelled")
        with pytest.raises(ValueError, match="Cannot mark payslip as paid with status cancelled"):
            entry.mark_paid(date.today())

    def test_cancel_from_generated(self, fixed_now):
        entry = PayslipTable(status="generated", version=1)
        with patch("infrastructure.persistence_orm.payslip_table.datetime") as mock_dt:
            mock_dt.utcnow.return_value = fixed_now.replace(tzinfo=None)
            new_entry = entry.cancel()
        assert new_entry.status == "cancelled"
        assert new_entry.version == 2

    def test_cancel_from_approved(self):
        entry = PayslipTable(status="approved")
        new_entry = entry.cancel()
        assert new_entry.status == "cancelled"

    def test_cancel_from_paid_raises(self):
        entry = PayslipTable(status="paid")
        with pytest.raises(ValueError, match="Cannot cancel a paid payslip"):
            entry.cancel()

    def test_recalculate(self, fixed_now):
        entry = PayslipTable(
            basic_salary=Decimal("5000000"),
            allowances=Decimal("1000000"),
            tax_pph21=Decimal("200000"),
            bpjs_employment=Decimal("100000"),
            bpjs_health=Decimal("50000"),
            bpjs_pension=Decimal("75000"),
            loan_deduction=Decimal("300000"),
            cooperative_deduction=Decimal("50000"),
            other_deductions=Decimal("25000"),
            version=1,
        )
        # Initially gross, total_deductions, net_pay may be zero or stale
        entry.gross_income = Decimal(0)
        entry.total_deductions = Decimal(0)
        entry.net_pay = Decimal(0)
        with patch("infrastructure.persistence_orm.payslip_table.datetime") as mock_dt:
            mock_dt.utcnow.return_value = fixed_now.replace(tzinfo=None)
            new_entry = entry.recalculate()
        # total_income = 5,000,000 + 1,000,000 = 6,000,000
        assert new_entry.gross_income == Decimal("6000000")
        # total_deductions_calc = 200k+100k+50k+75k+300k+50k+25k = 800,000
        assert new_entry.total_deductions == Decimal("800000")
        # net_pay = 6,000,000 - 800,000 = 5,200,000
        assert new_entry.net_pay == Decimal("5200000")
        assert new_entry.version == 2

    def test_recalculate_negative_net_pay_sets_zero(self):
        entry = PayslipTable(
            basic_salary=Decimal("100000"),
            allowances=Decimal(0),
            tax_pph21=Decimal("200000"),  # more than income
            bpjs_employment=Decimal(0),
            bpjs_health=Decimal(0),
            bpjs_pension=Decimal(0),
            loan_deduction=Decimal(0),
            cooperative_deduction=Decimal(0),
            other_deductions=Decimal(0),
            version=1,
        )
        new_entry = entry.recalculate()
        assert new_entry.net_pay == Decimal(0)

    def test_update_notes(self, fixed_now):
        entry = PayslipTable(status="generated", notes="old", version=1)
        with patch("infrastructure.persistence_orm.payslip_table.datetime") as mock_dt:
            mock_dt.utcnow.return_value = fixed_now.replace(tzinfo=None)
            new_entry = entry.update_notes("new notes")
        assert new_entry.notes == "new notes"
        assert new_entry.version == 2

    def test_update_notes_on_paid_raises(self):
        entry = PayslipTable(status="paid")
        with pytest.raises(ValueError, match="Cannot update notes for a paid payslip"):
            entry.update_notes("new notes")

    # -------------------- Factory Method Tests --------------------
    def test_create_minimal(self):
        legal_id = uuid4()
        emp_id = uuid4()
        run_id = uuid4()
        entry = PayslipTable.create(
            legal_entity_id=legal_id,
            payslip_number="SLIP-002",
            employee_id=emp_id,
            employee_code="EMP002",
            employee_name="Jane Doe",
            payroll_run_id=run_id,
            period_year=2026,
            period_month=7,
            basic_salary=Decimal("6000000"),
        )
        assert entry.payslip_number == "SLIP-002"
        assert entry.legal_entity_id == legal_id
        assert entry.employee_id == emp_id
        assert entry.payroll_run_id == run_id
        assert entry.status == "generated"
        assert entry.version == 1
        # Calculated fields
        assert entry.gross_income == Decimal("6000000")
        assert entry.total_deductions == Decimal(0)
        assert entry.net_pay == Decimal("6000000")

    def test_create_with_deductions(self):
        entry = PayslipTable.create(
            legal_entity_id=uuid4(),
            payslip_number="SLIP-003",
            employee_id=uuid4(),
            employee_code="EMP003",
            employee_name="John Smith",
            payroll_run_id=uuid4(),
            period_year=2026,
            period_month=7,
            basic_salary=Decimal("5000000"),
            allowances=Decimal("1000000"),
            tax_pph21=Decimal("200000"),
            bpjs_employment=Decimal("100000"),
        )
        assert entry.gross_income == Decimal("6000000")
        assert entry.total_deductions == Decimal("300000")
        assert entry.net_pay == Decimal("5700000")

    def test_create_negative_net_pay_clamps_to_zero(self):
        entry = PayslipTable.create(
            legal_entity_id=uuid4(),
            payslip_number="SLIP-004",
            employee_id=uuid4(),
            employee_code="EMP004",
            employee_name="Test",
            payroll_run_id=uuid4(),
            period_year=2026,
            period_month=7,
            basic_salary=Decimal("100000"),
            tax_pph21=Decimal("200000"),  # > income
        )
        assert entry.net_pay == Decimal(0)

    def test_from_payroll_run(self):
        # Mock PayrollRunTable and EmployeeTable
        payroll_run = MagicMock()
        payroll_run.id = uuid4()
        payroll_run.legal_entity_id = uuid4()
        payroll_run.period_year = 2026
        payroll_run.period_month = 7

        employee = MagicMock()
        employee.id = uuid4()
        employee.employee_code = "EMP005"
        employee.full_name = "Alice"

        entry = PayslipTable.from_payroll_run(
            payroll_run=payroll_run,
            employee=employee,
            payslip_number="SLIP-005",
            basic_salary=Decimal("7000000"),
            allowances=Decimal("500000"),
            overtime=Decimal("200000"),
            loan_deduction=Decimal("300000"),
        )
        assert entry.legal_entity_id == payroll_run.legal_entity_id
        assert entry.payroll_run_id == payroll_run.id
        assert entry.period_year == 2026
        assert entry.period_month == 7
        assert entry.employee_id == employee.id
        assert entry.employee_code == "EMP005"
        assert entry.employee_name == "Alice"
        assert entry.basic_salary == Decimal("7000000")
        assert entry.allowances == Decimal("500000")
        assert entry.overtime == Decimal("200000")
        assert entry.loan_deduction == Decimal("300000")
        # gross = 7,700,000
        assert entry.gross_income == Decimal("7700000")
        # total deductions = 300,000 (no other)
        assert entry.total_deductions == Decimal("300000")
        assert entry.net_pay == Decimal("7400000")

    # -------------------- Serialization Tests --------------------
    def test_to_dict(self):
        entry = PayslipTable(
            id=uuid4(),
            legal_entity_id=uuid4(),
            payslip_number="SLIP-006",
            period_year=2026,
            period_month=7,
            employee_id=uuid4(),
            employee_code="EMP006",
            employee_name="Bob",
            payroll_run_id=uuid4(),
            basic_salary=Decimal("5000000"),
            gross_income=Decimal("6000000"),
            total_deductions=Decimal("500000"),
            net_pay=Decimal("5500000"),
            status="generated",
            version=1,
            created_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
            updated_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        )
        d = entry.to_dict()
        assert d["payslip_number"] == "SLIP-006"
        assert d["period_year"] == 2026
        assert d["net_pay"] == "5500000"
        assert d["status"] == "generated"
        assert d["created_at"] == "2026-01-01T12:00:00+00:00"

    def test_to_db_record(self):
        entry = PayslipTable(
            id=uuid4(),
            legal_entity_id=uuid4(),
            payslip_number="SLIP-007",
            period_year=2026,
            period_month=7,
            employee_id=uuid4(),
            employee_code="EMP007",
            employee_name="Charlie",
            payroll_run_id=uuid4(),
            basic_salary=Decimal("5000000"),
            gross_income=Decimal("5000000"),
            total_deductions=Decimal(0),
            net_pay=Decimal("5000000"),
            status="generated",
        )
        rec = entry.to_db_record()
        assert rec["payslip_number"] == "SLIP-007"
        assert rec["basic_salary"] == Decimal("5000000")
        assert rec["version"] == 1

    # -------------------- __str__, __repr__, __eq__, __hash__ Tests --------------------
    def test_str(self):
        entry = PayslipTable(
            payslip_number="SLIP-008",
            employee_name="David",
            period_year=2026,
            period_month=7,
        )
        assert str(entry) == "Payslip SLIP-008 - David - 2026-07"

    def test_repr(self):
        entry = PayslipTable(id=uuid4(), payslip_number="SLIP-009", status="generated")
        assert repr(entry).startswith("PayslipTable(id=")
        assert "SLIP-009" in repr(entry)

    def test_eq(self):
        id1 = uuid4()
        entry1 = PayslipTable(id=id1)
        entry2 = PayslipTable(id=id1)
        entry3 = PayslipTable(id=uuid4())
        assert entry1 == entry2
        assert entry1 != entry3
        assert entry1 != "string"

    def test_hash(self):
        id1 = uuid4()
        entry = PayslipTable(id=id1)
        assert hash(entry) == hash(id1)

    # -------------------- Fixture for fixed datetime --------------------
    @pytest.fixture
    def fixed_now(self):
        return datetime(2026, 7, 27, 12, 0, 0, tzinfo=UTC)
