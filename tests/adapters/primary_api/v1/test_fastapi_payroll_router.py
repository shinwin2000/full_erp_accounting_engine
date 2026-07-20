# tests/adapters/primary_api/v1/test_fastapi_payroll_router.py
# Perbaikan kualitas assertions: semua assert True dihapus,
# diganti dengan assertion yang memeriksa nilai aktual,
# efek samping, atau interaksi mock.

from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from uuid import uuid4

from adapters.primary_api.v1.fastapi_payroll_router import (
    AddSalaryComponentRequest,
    CancelPayrollRunRequest,
    CreatePayrollRunRequest,
    PayrollFrequency,
    PayrollRunResponseModel,
    PayrollStatus,
    PayslipResponseModel,
    PostPayrollToGLRequest,
    PostPayrollToGLResponse,
    SalaryComponentType,
    SalaryStructureResponse,
    SetSalaryStructureRequest,
    add_salary_component,
    approve_payroll_run,
    cancel_payroll_run,
    create_payroll_run,
    generate_payroll_report,
    get_correlation_id,
    get_idempotency_key,
    get_payroll_run,
    get_payroll_stats,
    get_payslip,
    get_salary_structure,
    list_payroll_runs,
    pay_payroll_run,
    post_payroll_to_gl,
    process_payroll_run,
    router,
    send_payslip_to_employee,
    set_salary_structure,
)


# ============================================================================
# Enum tests
# ============================================================================
class TestPayrollFrequency:
    def test_members_exist(self):
        expected = ["MONTHLY", "SEMI_MONTHLY", "WEEKLY", "DAILY"]
        for name in expected:
            assert hasattr(PayrollFrequency, name)

    def test_member_is_instance(self):
        assert isinstance(PayrollFrequency.MONTHLY, PayrollFrequency)


class TestPayrollStatus:
    def test_members_exist(self):
        expected = [
            "DRAFT",
            "PROCESSED",
            "APPROVED",
            "PAID",
            "POSTED",
            "COMPLETED",
            "CANCELLED",
        ]
        for name in expected:
            assert hasattr(PayrollStatus, name)

    def test_member_is_instance(self):
        assert isinstance(PayrollStatus.DRAFT, PayrollStatus)


class TestSalaryComponentType:
    def test_members_exist(self):
        expected = [
            "BASIC_SALARY",
            "ALLOWANCE",
            "OVERTIME",
            "BONUS",
            "DEDUCTION_BPJS_KESEHATAN",
            "DEDUCTION_BPJS_KETENAGAKERJAAN",
            "TAX_PPH21",
            "OTHER_DEDUCTION",
            "OTHER_ALLOWANCE",
        ]
        for name in expected:
            assert hasattr(SalaryComponentType, name)

    def test_member_is_instance(self):
        assert isinstance(SalaryComponentType.BASIC_SALARY, SalaryComponentType)


# ============================================================================
# Pydantic model tests
# ============================================================================
class TestCreatePayrollRunRequest:
    def test_construction(self):
        data = {
            "legal_entity_id": uuid4(),
            "period_month": 12,
            "period_year": 2024,
            "frequency": PayrollFrequency.MONTHLY,
            "employee_ids": [uuid4()],
            "auto_post_to_gl": True,
            "idempotency_key": "idem123",
        }
        instance = CreatePayrollRunRequest(**data)
        assert instance.legal_entity_id == data["legal_entity_id"]
        assert instance.period_month == 12
        assert instance.period_year == 2024
        assert instance.frequency == PayrollFrequency.MONTHLY
        assert instance.employee_ids == data["employee_ids"]
        assert instance.auto_post_to_gl is True
        assert instance.idempotency_key == "idem123"


class TestPayrollRunResponseModel:
    def test_construction(self):
        now = datetime.now()
        data = {
            "payroll_run_id": uuid4(),
            "period": "2024-12",
            "frequency": "MONTHLY",
            "employee_count": 10,
            "total_gross_pay": Decimal("100000.00"),
            "total_deductions": Decimal("20000.00"),
            "total_net_pay": Decimal("80000.00"),
            "total_tax_withheld": Decimal("5000.00"),
            "status": "draft",
            "generated_at": now,
            "idempotency_key": "idem123",
        }
        instance = PayrollRunResponseModel(**data)
        assert instance.payroll_run_id == data["payroll_run_id"]
        assert instance.total_gross_pay == Decimal("100000.00")


class TestSetSalaryStructureRequest:
    def test_construction(self):
        data = {
            "employee_id": uuid4(),
            "basic_salary": Decimal("5000000"),
            "position_allowance": Decimal("1000000"),
            "transport_allowance": Decimal("500000"),
            "meal_allowance": Decimal("300000"),
            "overtime_rate": Decimal("50000"),
            "bpjs_kesehatan_employee": Decimal("50000"),
            "bpjs_kesehatan_employer": Decimal("100000"),
            "bpjs_ketenagakerjaan_employee": Decimal("20000"),
            "bpjs_ketenagakerjaan_employer": Decimal("40000"),
            "other_deductions": {"loan": Decimal("100000")},
            "effective_date": date(2024, 1, 1),
            "idempotency_key": "idem123",
        }
        instance = SetSalaryStructureRequest(**data)
        assert instance.employee_id == data["employee_id"]
        assert instance.basic_salary == Decimal("5000000")


class TestSalaryStructureResponse:
    def test_construction(self):
        data = {
            "employee_id": uuid4(),
            "basic_salary": Decimal("5000000"),
            "position_allowance": Decimal("1000000"),
            "transport_allowance": Decimal("500000"),
            "meal_allowance": Decimal("300000"),
            "overtime_rate": Decimal("50000"),
            "bpjs_kesehatan_employee": Decimal("50000"),
            "bpjs_kesehatan_employer": Decimal("100000"),
            "bpjs_ketenagakerjaan_employee": Decimal("20000"),
            "bpjs_ketenagakerjaan_employer": Decimal("40000"),
            "other_deductions": {"loan": Decimal("100000")},
        }
        instance = SalaryStructureResponse(**data)
        assert instance.employee_id == data["employee_id"]


class TestAddSalaryComponentRequest:
    def test_construction(self):
        data = {
            "employee_id": uuid4(),
            "component_type": SalaryComponentType.BONUS,
            "amount": Decimal("100000"),
            "description": "Performance bonus",
            "effective_date": date(2024, 1, 1),
            "idempotency_key": "idem123",
        }
        instance = AddSalaryComponentRequest(**data)
        assert instance.employee_id == data["employee_id"]
        assert instance.component_type == SalaryComponentType.BONUS


class TestPayslipResponseModel:
    def test_construction(self):
        now = datetime.now()
        data = {
            "payslip_id": uuid4(),
            "employee_id": uuid4(),
            "employee_name": "John Doe",
            "payroll_run_id": uuid4(),
            "gross_pay": Decimal("10000000"),
            "total_deductions": Decimal("2000000"),
            "net_pay": Decimal("8000000"),
            "tax_withheld": Decimal("500000"),
            "components": [{"type": "BASIC", "amount": 5000000}],
            "generated_at": now,
            "sent_at": now,
        }
        instance = PayslipResponseModel(**data)
        assert instance.employee_name == "John Doe"


class TestPostPayrollToGLRequest:
    def test_construction(self):
        data = {"payroll_run_id": uuid4(), "idempotency_key": "idem123"}
        instance = PostPayrollToGLRequest(**data)
        assert instance.payroll_run_id == data["payroll_run_id"]


class TestPostPayrollToGLResponse:
    def test_construction(self):
        data = {
            "payroll_run_id": uuid4(),
            "posted_to_gl": True,
            "journal_id": uuid4(),
            "posting_errors": [],
            "idempotency_key": "idem123",
        }
        instance = PostPayrollToGLResponse(**data)
        assert instance.posted_to_gl is True


class TestCancelPayrollRunRequest:
    def test_construction(self):
        data = {"reason": "Test cancel", "idempotency_key": "idem123"}
        instance = CancelPayrollRunRequest(**data)
        assert instance.reason == "Test cancel"


# ============================================================================
# Helper functions tests
# ============================================================================
def test_get_correlation_id_from_header():
    request = MagicMock(spec=Request)
    request.headers = {"X-Correlation-ID": "corr-123"}
    result = get_correlation_id(request)
    assert result == "corr-123"


def test_get_correlation_id_generated():
    request = MagicMock(spec=Request)
    request.headers = {}
    result = get_correlation_id(request)
    # should be a UUID string
    assert len(result) == 36
    # coba parse ke UUID
    uuid4(result)  # should not raise


def test_get_idempotency_key_from_header():
    request = MagicMock(spec=Request)
    request.headers = {"Idempotency-Key": "idem-123"}
    result = get_idempotency_key(request)
    assert result == "idem-123"


def test_get_idempotency_key_generated():
    request = MagicMock(spec=Request)
    request.headers = {}
    result = get_idempotency_key(request)
    assert len(result) == 36
    uuid4(result)  # should not raise


# ============================================================================
# Endpoint tests with TestClient
# ============================================================================
@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture
def mock_payroll_service():
    with patch(
        "adapters.primary_api.v1.fastapi_payroll_router.get_service"
    ) as mock_get_service:
        mock_service = AsyncMock()
        mock_get_service.return_value = mock_service
        yield mock_service


@pytest.fixture
def mock_current_user():
    with patch(
        "adapters.primary_api.v1.fastapi_payroll_router.get_current_user"
    ) as mock:
        mock.return_value = MagicMock(user_id=uuid4())
        yield mock


class TestPayrollRunEndpoints:
    def test_create_payroll_run_success(self, client, mock_payroll_service, mock_current_user):
        run_id = uuid4()
        mock_payroll_service.get_payroll_run_by_idempotency_key.return_value = None
        mock_payroll_service.create_payroll_run.return_value = MagicMock(
            payroll_run_id=run_id,
            period="2024-12",
            frequency="MONTHLY",
            employee_count=5,
            total_gross_pay=Decimal("50000000"),
            total_deductions=Decimal("10000000"),
            total_net_pay=Decimal("40000000"),
            total_tax_withheld=Decimal("5000000"),
            status="draft",
            generated_at=datetime.now(),
        )

        payload = {
            "legal_entity_id": str(uuid4()),
            "period_month": 12,
            "period_year": 2024,
            "frequency": "MONTHLY",
            "employee_ids": [str(uuid4())],
            "auto_post_to_gl": True,
            "idempotency_key": "idem123",
        }
        response = client.post("/runs", json=payload)
        assert response.status_code == 201
        data = response.json()
        assert data["payroll_run_id"] == str(run_id)
        assert data["period"] == "2024-12"
        assert data["status"] == "draft"
        mock_payroll_service.create_payroll_run.assert_awaited_once()

    def test_create_payroll_run_idempotent(self, client, mock_payroll_service, mock_current_user):
        run_id = uuid4()
        existing = MagicMock(
            payroll_run_id=run_id,
            period="2024-12",
            frequency="MONTHLY",
            employee_count=5,
            total_gross_pay=Decimal("50000000"),
            total_deductions=Decimal("10000000"),
            total_net_pay=Decimal("40000000"),
            total_tax_withheld=Decimal("5000000"),
            status="draft",
            generated_at=datetime.now(),
        )
        mock_payroll_service.get_payroll_run_by_idempotency_key.return_value = existing

        payload = {
            "legal_entity_id": str(uuid4()),
            "period_month": 12,
            "period_year": 2024,
            "frequency": "MONTHLY",
            "idempotency_key": "idem123",
        }
        response = client.post("/runs", json=payload)
        assert response.status_code == 201
        data = response.json()
        assert data["payroll_run_id"] == str(run_id)
        mock_payroll_service.create_payroll_run.assert_not_awaited()

    def test_process_payroll_run_success(self, client, mock_payroll_service, mock_current_user):
        run_id = uuid4()
        mock_payroll_service.get_payroll_run_by_idempotency_key.return_value = None
        mock_payroll_service.process_payroll_run.return_value = MagicMock(
            payroll_run_id=run_id,
            period="2024-12",
            frequency="MONTHLY",
            employee_count=5,
            total_gross_pay=Decimal("50000000"),
            total_deductions=Decimal("10000000"),
            total_net_pay=Decimal("40000000"),
            total_tax_withheld=Decimal("5000000"),
            status="processed",
            generated_at=datetime.now(),
        )

        response = client.post(f"/runs/{run_id}/process")
        assert response.status_code == 200
        data = response.json()
        assert data["payroll_run_id"] == str(run_id)
        assert data["status"] == "processed"
        mock_payroll_service.process_payroll_run.assert_awaited_once()

    def test_approve_payroll_run_success(self, client, mock_payroll_service, mock_current_user):
        run_id = uuid4()
        mock_payroll_service.get_payroll_run_by_idempotency_key.return_value = None
        mock_payroll_service.approve_payroll_run.return_value = MagicMock(
            payroll_run_id=run_id,
            period="2024-12",
            frequency="MONTHLY",
            employee_count=5,
            total_gross_pay=Decimal("50000000"),
            total_deductions=Decimal("10000000"),
            total_net_pay=Decimal("40000000"),
            total_tax_withheld=Decimal("5000000"),
            status="approved",
            generated_at=datetime.now(),
        )

        response = client.post(f"/runs/{run_id}/approve")
        assert response.status_code == 200
        data = response.json()
        assert data["payroll_run_id"] == str(run_id)
        assert data["status"] == "approved"

    def test_pay_payroll_run_success(self, client, mock_payroll_service, mock_current_user):
        run_id = uuid4()
        mock_payroll_service.get_payroll_run_by_idempotency_key.return_value = None
        mock_payroll_service.pay_payroll_run.return_value = MagicMock(
            payroll_run_id=run_id,
            period="2024-12",
            frequency="MONTHLY",
            employee_count=5,
            total_gross_pay=Decimal("50000000"),
            total_deductions=Decimal("10000000"),
            total_net_pay=Decimal("40000000"),
            total_tax_withheld=Decimal("5000000"),
            status="paid",
            generated_at=datetime.now(),
        )

        response = client.post(f"/runs/{run_id}/pay")
        assert response.status_code == 200
        data = response.json()
        assert data["payroll_run_id"] == str(run_id)
        assert data["status"] == "paid"

    def test_post_payroll_to_gl_success(self, client, mock_payroll_service, mock_current_user):
        run_id = uuid4()
        journal_id = uuid4()
        mock_payroll_service.get_payroll_post_result_by_idempotency_key.return_value = None
        mock_payroll_service.post_payroll_to_gl.return_value = MagicMock(
            payroll_run_id=run_id,
            posted_to_gl=True,
            journal_id=journal_id,
            posting_errors=[],
        )

        payload = {"payroll_run_id": str(run_id), "idempotency_key": "idem123"}
        response = client.post(f"/runs/{run_id}/post-to-gl", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["payroll_run_id"] == str(run_id)
        assert data["posted_to_gl"] is True
        assert data["journal_id"] == str(journal_id)

    def test_post_payroll_to_gl_idempotent(self, client, mock_payroll_service, mock_current_user):
        run_id = uuid4()
        journal_id = uuid4()
        existing = MagicMock(
            payroll_run_id=run_id,
            posted_to_gl=True,
            journal_id=journal_id,
            posting_errors=[],
        )
        mock_payroll_service.get_payroll_post_result_by_idempotency_key.return_value = existing

        payload = {"payroll_run_id": str(run_id), "idempotency_key": "idem123"}
        response = client.post(f"/runs/{run_id}/post-to-gl", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["payroll_run_id"] == str(run_id)
        assert data["posted_to_gl"] is True
        mock_payroll_service.post_payroll_to_gl.assert_not_awaited()

    def test_cancel_payroll_run_not_implemented(self, client, mock_payroll_service, mock_current_user):
        run_id = uuid4()
        mock_payroll_service.get_payroll_run_by_idempotency_key.return_value = None
        mock_payroll_service.cancel_payroll_run.return_value = None

        payload = {"reason": "Test cancel", "idempotency_key": "idem123"}
        response = client.post(f"/runs/{run_id}/cancel", json=payload)
        # Karena endpoint raise 501, kita test bahwa response 501
        assert response.status_code == 501
        assert "Not Implemented" in response.text

    def test_get_payroll_run_not_implemented(self, client, mock_payroll_service, mock_current_user):
        run_id = uuid4()
        response = client.get(f"/runs/{run_id}")
        assert response.status_code == 501
        assert "Not Implemented" in response.text

    def test_list_payroll_runs_not_implemented(self, client, mock_payroll_service, mock_current_user):
        legal_entity_id = uuid4()
        response = client.get(f"/runs?legal_entity_id={legal_entity_id}")
        assert response.status_code == 501
        assert "Not Implemented" in response.text


class TestPayslipEndpoints:
    def test_get_payslip_success(self, client, mock_payroll_service, mock_current_user):
        payslip_id = uuid4()
        mock_payroll_service.get_payslip.return_value = MagicMock(
            payslip_id=payslip_id,
            employee_id=uuid4(),
            employee_name="John Doe",
            payroll_run_id=uuid4(),
            gross_pay=Decimal("10000000"),
            total_deductions=Decimal("2000000"),
            net_pay=Decimal("8000000"),
            tax_withheld=Decimal("500000"),
            components=[{"type": "BASIC", "amount": 5000000}],
            generated_at=datetime.now(),
            sent_at=None,
        )

        response = client.get(f"/payslips/{payslip_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["payslip_id"] == str(payslip_id)
        assert data["employee_name"] == "John Doe"

    def test_get_payslip_not_found(self, client, mock_payroll_service, mock_current_user):
        mock_payroll_service.get_payslip.return_value = None
        response = client.get(f"/payslips/{uuid4()}")
        assert response.status_code == 404
        assert "not found" in response.text.lower()

    def test_send_payslip_to_employee_success(self, client, mock_payroll_service, mock_current_user):
        payslip_id = uuid4()
        mock_payroll_service.get_payslip_send_status_by_idempotency_key.return_value = None
        mock_payroll_service.send_payslip_to_employee.return_value = None

        response = client.post(f"/payslips/{payslip_id}/send")
        assert response.status_code == 204
        mock_payroll_service.send_payslip_to_employee.assert_awaited_once()

    def test_send_payslip_to_employee_idempotent(self, client, mock_payroll_service, mock_current_user):
        payslip_id = uuid4()
        existing = MagicMock(payslip_id=payslip_id)
        mock_payroll_service.get_payslip_send_status_by_idempotency_key.return_value = existing

        response = client.post(f"/payslips/{payslip_id}/send")
        assert response.status_code == 204
        mock_payroll_service.send_payslip_to_employee.assert_not_awaited()


class TestSalaryStructureEndpoints:
    def test_set_salary_structure_success(self, client, mock_payroll_service, mock_current_user):
        employee_id = uuid4()
        mock_payroll_service.get_salary_structure_by_idempotency_key.return_value = None
        mock_payroll_service.set_employee_salary_structure.return_value = None

        payload = {
            "employee_id": str(employee_id),
            "basic_salary": "5000000",
            "position_allowance": "1000000",
            "transport_allowance": "500000",
            "meal_allowance": "300000",
            "overtime_rate": "50000",
            "bpjs_kesehatan_employee": "50000",
            "bpjs_kesehatan_employer": "100000",
            "bpjs_ketenagakerjaan_employee": "20000",
            "bpjs_ketenagakerjaan_employer": "40000",
            "other_deductions": {},
            "effective_date": "2024-01-01",
            "idempotency_key": "idem123",
        }
        response = client.post("/salary-structure", json=payload)
        assert response.status_code == 204
        mock_payroll_service.set_employee_salary_structure.assert_awaited_once()

    def test_set_salary_structure_idempotent(self, client, mock_payroll_service, mock_current_user):
        employee_id = uuid4()
        mock_payroll_service.get_salary_structure_by_idempotency_key.return_value = True

        payload = {
            "employee_id": str(employee_id),
            "basic_salary": "5000000",
            "idempotency_key": "idem123",
        }
        response = client.post("/salary-structure", json=payload)
        assert response.status_code == 204
        mock_payroll_service.set_employee_salary_structure.assert_not_awaited()

    def test_get_salary_structure_success(self, client, mock_payroll_service, mock_current_user):
        employee_id = uuid4()
        mock_payroll_service.get_salary_structure.return_value = MagicMock(
            employee_id=employee_id,
            basic_salary=Decimal("5000000"),
            position_allowance=Decimal("1000000"),
            transport_allowance=Decimal("500000"),
            meal_allowance=Decimal("300000"),
            overtime_rate=Decimal("50000"),
            bpjs_kesehatan_employee=Decimal("50000"),
            bpjs_kesehatan_employer=Decimal("100000"),
            bpjs_ketenagakerjaan_employee=Decimal("20000"),
            bpjs_ketenagakerjaan_employer=Decimal("40000"),
            other_deductions={},
        )

        response = client.get(f"/salary-structure/{employee_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["employee_id"] == str(employee_id)
        assert data["basic_salary"] == "5000000"

    def test_get_salary_structure_not_found(self, client, mock_payroll_service, mock_current_user):
        mock_payroll_service.get_salary_structure.return_value = None
        response = client.get(f"/salary-structure/{uuid4()}")
        assert response.status_code == 404
        assert "not found" in response.text.lower()


class TestSalaryComponentEndpoints:
    def test_add_salary_component_success(self, client, mock_payroll_service, mock_current_user):
        employee_id = uuid4()
        mock_payroll_service.get_salary_component_by_idempotency_key.return_value = None
        mock_payroll_service.add_salary_component.return_value = None

        payload = {
            "employee_id": str(employee_id),
            "component_type": "BONUS",
            "amount": "100000",
            "description": "Performance bonus",
            "effective_date": "2024-01-01",
            "idempotency_key": "idem123",
        }
        response = client.post("/salary-components", json=payload)
        assert response.status_code == 204
        mock_payroll_service.add_salary_component.assert_awaited_once()

    def test_add_salary_component_idempotent(self, client, mock_payroll_service, mock_current_user):
        employee_id = uuid4()
        mock_payroll_service.get_salary_component_by_idempotency_key.return_value = True

        payload = {
            "employee_id": str(employee_id),
            "component_type": "BONUS",
            "amount": "100000",
            "description": "Performance bonus",
            "idempotency_key": "idem123",
        }
        response = client.post("/salary-components", json=payload)
        assert response.status_code == 204
        mock_payroll_service.add_salary_component.assert_not_awaited()


class TestReportEndpoint:
    def test_generate_payroll_report_success(self, client, mock_payroll_service, mock_current_user):
        legal_entity_id = uuid4()
        mock_payroll_service.generate_payroll_report.return_value = "CSV content"

        response = client.get(
            f"/reports/payroll-summary?legal_entity_id={legal_entity_id}&period_year=2024&period_month=12&output_format=CSV"
        )
        assert response.status_code == 200
        assert response.text == "CSV content"
        mock_payroll_service.generate_payroll_report.assert_awaited_once_with(
            legal_entity_id=legal_entity_id,
            period_year=2024,
            period_month=12,
            output_format="CSV",
        )


class TestStatsEndpoint:
    def test_get_payroll_stats_success(self, client, mock_payroll_service, mock_current_user):
        mock_payroll_service.get_stats.return_value = {"total_runs": 5, "total_employees": 100}

        response = client.get("/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["total_runs"] == 5
        mock_payroll_service.get_stats.assert_called_once()