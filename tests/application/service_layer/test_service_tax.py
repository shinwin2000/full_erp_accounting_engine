# tests/application/service_layer/test_service_tax.py
"""
Comprehensive unit tests for application/service_layer/service_tax.py.

Covers:
- Enums: TaxType, FakturStatus, PKPStatus
- DTO classes: construction and attributes
- Exceptions: TaxServiceError, TaxRateNotFoundError, InvalidNPWPError,
  FakturPajakError, CoretaxSubmissionError, PKPStatusError
- TaxService:
  - __init__ and lazy getters (_get_ppn_calculator, _get_pph21_calculator, ...)
  - _check_authority, _validate_npwp, _get_pph23_object_code
  - calculate_ppn (rates, luxury, exempt)
  - create_faktur_pajak_keluaran (NPWP validation, generation)
  - submit_faktur_pajak_to_coretax (success, rejection, not found)
  - report_spt_masa_ppn (calculation, Coretax submission, events)
  - calculate_pph21 (PTKP, tariff)
  - calculate_pph23 (rate lookup, object code)
  - change_pkp_status (valid status, already same, invalid)
  - get_pkp_status
  - use_meterai (amount based on type)
  - update_tax_profile
  - get_stats, get_audit_trail
- Factory function create_tax_service
- Events: publishing mocked, verify events called
- All private methods are exercised via public method calls or direct calls.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from application.service_layer.service_tax import (
    CoretaxSubmissionError,
    FakturPajakDTO,
    FakturPajakError,
    FakturStatus,
    InvalidNPWPError,
    MeteraiUsageRequest,
    PKPStatus,
    PKPStatusChangeRequest,
    PKPStatusError,
    PPh21CalculationRequest,
    PPh23CalculationRequest,
    PPNCalculationRequest,
    PPNCalculationResponse,
    SPTMasaPpnDTO,
    TaxRateNotFoundError,
    TaxService,
    TaxServiceError,
    TaxType,
    TaxWithholdingSlipDTO,
    audit,
    create_tax_service,
)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_tax_repo():
    repo = AsyncMock()
    repo.save_faktur_pajak = AsyncMock()
    repo.get_faktur_pajak = AsyncMock()
    repo.list_faktur_keluaran = AsyncMock(return_value=[])
    repo.list_faktur_masukan = AsyncMock(return_value=[])
    repo.save_spt_ppn = AsyncMock()
    repo.get_employee_tax_data = AsyncMock()
    repo.get_pkp_status = AsyncMock()
    repo.save_pkp_status = AsyncMock()
    repo.save_meterai_usage = AsyncMock()
    repo.save_tax_profile = AsyncMock()
    repo.get_last_faktur_number = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def mock_coretax():
    client = AsyncMock()
    client.submit_faktur = AsyncMock()
    client.submit_spt_ppn = AsyncMock()
    return client


@pytest.fixture
def mock_uow():
    uow = AsyncMock()
    uow.commit = AsyncMock()
    return uow


@pytest.fixture
def mock_event_publisher():
    publisher = AsyncMock()
    publisher.publish = AsyncMock()
    return publisher


@pytest.fixture
def service(mock_tax_repo, mock_coretax, mock_uow, mock_event_publisher):
    """TaxService with all dependencies mocked."""
    return TaxService(
        tax_repo=mock_tax_repo,
        coretax_client=mock_coretax,
        uow=mock_uow,
        event_publisher=mock_event_publisher,
    )


@pytest.fixture
def legal_entity_id():
    return uuid4()


@pytest.fixture
def user_id():
    return uuid4()


@pytest.fixture
def sample_faktur(legal_entity_id):
    return FakturPajakDTO(
        id=uuid4(),
        legal_entity_id=legal_entity_id,
        faktur_number="010-00000001",
        npwp_penjual="12.345.678.9-012.345",
        npwp_pembeli="12.345.678.9-012.346",
        nama_pembeli="PT Customer",
        dpp=Decimal("1000000"),
        ppn=Decimal("110000"),
        ppnbm=Decimal("0"),
        faktur_date=date(2025, 1, 15),
        status=FakturStatus.DRAFT.value,
    )


# ============================================================================
# Tests for Enums
# ============================================================================

class TestEnums:
    def test_tax_type_members(self):
        assert TaxType.PPN.value == "PPN"
        assert TaxType.PPH21.value == "PPH21"
        assert TaxType.PPH23.value == "PPH23"

    def test_faktur_status_members(self):
        assert FakturStatus.DRAFT.value == "DRAFT"
        assert FakturStatus.SUBMITTED.value == "SUBMITTED"
        assert FakturStatus.APPROVED.value == "APPROVED"

    def test_pkp_status_members(self):
        assert PKPStatus.NON_PKP.value == "NON_PKP"
        assert PKPStatus.PKP.value == "PKP"


# ============================================================================
# Tests for DTOs
# ============================================================================

class TestDTOs:
    def test_ppn_calculation_request(self, legal_entity_id):
        req = PPNCalculationRequest(
            legal_entity_id=legal_entity_id,
            is_luxury_goods=True,
            tax_period="2025-01",
            transaction_date=date.today(),
            dpp=Decimal("1000"),
        )
        assert req.legal_entity_id == legal_entity_id
        assert req.dpp == Decimal("1000")

    def test_ppn_calculation_response(self):
        resp = PPNCalculationResponse(
            dpp=Decimal("1000"),
            vat_rate=Decimal("0.11"),
            vat_amount=Decimal("110"),
            luxury_goods_vat=Decimal("0"),
            total_vat=Decimal("110"),
            is_exempted=False,
        )
        assert resp.total_vat == Decimal("110")

    def test_pph21_calculation_request(self):
        req = PPh21CalculationRequest(
            employee_id=uuid4(),
            gross_income=Decimal("10000000"),
            period_month=1,
            period_year=2025,
        )
        assert req.gross_income == Decimal("10000000")

    def test_pph23_calculation_request(self):
        req = PPh23CalculationRequest(
            supplier_id=uuid4(),
            gross_amount=Decimal("5000000"),
            transaction_type="JASA",
            is_has_npwp=True,
        )
        assert req.gross_amount == Decimal("5000000")

    def test_faktur_pajak_dto(self):
        faktur = FakturPajakDTO(
            id=uuid4(),
            legal_entity_id=uuid4(),
            faktur_number="010-00000001",
            npwp_penjual="123",
            npwp_pembeli="456",
            nama_pembeli="Buyer",
            dpp=Decimal("1000"),
            ppn=Decimal("110"),
            ppnbm=Decimal("0"),
            faktur_date=date.today(),
        )
        assert faktur.faktur_number == "010-00000001"

    def test_spt_masa_ppn_dto(self):
        spt = SPTMasaPpnDTO(
            id=uuid4(),
            legal_entity_id=uuid4(),
            masa_pajak="2025-01",
            total_penyerahan_dpp=Decimal("1000"),
            total_ppn_keluaran=Decimal("110"),
            total_ppn_masukan=Decimal("50"),
            kompensasi_dari_masa_sebelumnya=Decimal("0"),
            ppn_kurang_bayar=Decimal("60"),
            ppn_lebih_bayar=Decimal("0"),
            status="DRAFT",
        )
        assert spt.ppn_kurang_bayar == Decimal("60")

    def test_tax_withholding_slip_dto(self):
        slip = TaxWithholdingSlipDTO(
            id=uuid4(),
            legal_entity_id=uuid4(),
            counterparty_npwp="123",
            counterparty_name="Supplier",
            tax_type="PPH23",
            gross_amount=Decimal("5000"),
            tax_amount=Decimal("100"),
            slip_number="SLIP-001",
            slip_date=date.today(),
            period="2025-01",
        )
        assert slip.tax_amount == Decimal("100")

    def test_pkp_status_change_request(self):
        req = PKPStatusChangeRequest(
            legal_entity_id=uuid4(),
            new_status="PKP",
            reason="Revenue threshold exceeded",
            changed_by=uuid4(),
        )
        assert req.new_status == "PKP"

    def test_meterai_usage_request(self):
        req = MeteraiUsageRequest(
            legal_entity_id=uuid4(),
            document_type="INVOICE",
            document_number="INV-001",
            meterai_type="10000",
            used_date=date.today(),
            used_by=uuid4(),
        )
        assert req.document_number == "INV-001"


# ============================================================================
# Tests for Exceptions
# ============================================================================

class TestExceptions:
    def test_tax_service_error(self):
        with pytest.raises(TaxServiceError):
            raise TaxServiceError("error")

    def test_tax_rate_not_found_error(self):
        with pytest.raises(TaxRateNotFoundError):
            raise TaxRateNotFoundError("rate not found")

    def test_invalid_npwp_error(self):
        with pytest.raises(InvalidNPWPError):
            raise InvalidNPWPError("invalid")

    def test_faktur_pajak_error(self):
        with pytest.raises(FakturPajakError):
            raise FakturPajakError("error")

    def test_coretax_submission_error(self):
        with pytest.raises(CoretaxSubmissionError):
            raise CoretaxSubmissionError("error")

    def test_pkp_status_error(self):
        with pytest.raises(PKPStatusError):
            raise PKPStatusError("error")


# ============================================================================
# Tests for TaxService
# ============================================================================

class TestTaxService:
    def test_init(self, service):
        assert service._tax_repo is not None
        assert service._coretax is not None
        assert service._uow is not None
        assert service._event_publisher is not None
        assert service._stats == {"calculations": 0, "faktur_created": 0, "faktur_submitted": 0, "spt_submitted": 0, "pkp_changes": 0, "meterai_used": 0}
        assert service._audit_trail == []

    # ---- Private helpers ----

    def test_check_authority_no_user(self, service):
        # Should not raise
        service._check_authority(None, "permission")
        # With user, just logs
        service._check_authority(uuid4(), "permission")

    def test_validate_npwp_valid(self, service):
        assert service._validate_npwp("12.345.678.9-012.345") is True
        assert service._validate_npwp("123456789012345") is True  # 15 digits
        assert service._validate_npwp("1234567890123456") is True  # 16 digits
        assert service._validate_npwp("1234") is False
        assert service._validate_npwp("abc") is False

    def test_get_pph23_object_code(self, service):
        assert service._get_pph23_object_code("JASA") == "24-104-01"
        assert service._get_pph23_object_code("SEWA") == "24-104-02"
        assert service._get_pph23_object_code("ROYALTI") == "24-104-03"
        assert service._get_pph23_object_code("UNKNOWN") == "24-104-99"
        assert service._get_pph23_object_code(None) == "24-104-99"

    # ---- Lazy getters ----

    def test_get_ppn_calculator(self, service):
        calc1 = service._get_ppn_calculator()
        calc2 = service._get_ppn_calculator()
        assert calc1 is calc2
        from policy_engine.tax_indonesia.ppn_calculator import PPNCalculator
        assert isinstance(calc1, PPNCalculator)

    def test_get_pph21_calculator(self, service):
        calc = service._get_pph21_calculator()
        assert calc is not None

    def test_get_pph23_calculator(self, service):
        calc = service._get_pph23_calculator()
        assert calc is not None

    def test_get_pph4_calculator(self, service):
        calc = service._get_pph4_calculator()
        assert calc is not None

    def test_get_withholding_engine(self, service):
        engine = service._get_withholding_engine()
        assert engine is not None

    def test_get_rate_registry(self, service):
        registry = service._get_rate_registry()
        assert registry is not None

    def test_get_penalty_engine(self, service):
        engine = service._get_penalty_engine()
        assert engine is not None

    # ---- calculate_ppn ----

    @pytest.mark.asyncio
    async def test_calculate_ppn_normal(self, service, legal_entity_id):
        request = PPNCalculationRequest(
            legal_entity_id=legal_entity_id,
            is_luxury_goods=False,
            tax_period="2025-01",
            transaction_date=date(2025, 1, 15),
            dpp=Decimal("1000000"),
        )
        # Mock _is_ppn_exempted to return False
        with patch.object(service, "_is_ppn_exempted", return_value=False):
            response = await service.calculate_ppn(request)
            assert response.dpp == Decimal("1000000")
            assert response.vat_rate == Decimal("0.11")
            assert response.vat_amount == Decimal("110000")
            assert response.luxury_goods_vat == Decimal("0")
            assert response.total_vat == Decimal("110000")
            assert response.is_exempted is False
            # Stats incremented
            assert service._stats["calculations"] == 1
            # Event published
            service._event_publisher.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_calculate_ppn_luxury(self, service, legal_entity_id):
        request = PPNCalculationRequest(
            legal_entity_id=legal_entity_id,
            is_luxury_goods=True,
            tax_period="2025-01",
            transaction_date=date(2025, 1, 15),
            dpp=Decimal("1000000"),
        )
        with patch.object(service, "_is_ppn_exempted", return_value=False):
            response = await service.calculate_ppn(request)
            assert response.vat_rate == Decimal("0.12")
            assert response.luxury_goods_vat == Decimal("200000")  # 20% of dpp
            assert response.total_vat == Decimal("320000")  # 120000 + 200000

    @pytest.mark.asyncio
    async def test_calculate_ppn_exempted(self, service, legal_entity_id):
        request = PPNCalculationRequest(
            legal_entity_id=legal_entity_id,
            dpp=Decimal("1000"),
            transaction_date=date.today(),
        )
        with patch.object(service, "_is_ppn_exempted", return_value=True):
            response = await service.calculate_ppn(request)
            assert response.is_exempted is True
            assert response.total_vat == Decimal("0")  # vat_amount + luxury

    # ---- create_faktur_pajak_keluaran ----

    @pytest.mark.asyncio
    async def test_create_faktur_pajak_keluaran_success(self, service, legal_entity_id, user_id):
        # Mock _generate_faktur_number to return known
        service._generate_faktur_number = AsyncMock(return_value="010-00000001")
        faktur = await service.create_faktur_pajak_keluaran(
            legal_entity_id=legal_entity_id,
            npwp_penjual="12.345.678.9-012.345",
            npwp_pembeli="12.345.678.9-012.346",
            nama_pembeli="PT Customer",
            dpp=Decimal("1000000"),
            ppn=Decimal("110000"),
            ppnbm=Decimal("0"),
            faktur_date=date(2025, 1, 15),
            user_id=user_id,
        )
        assert faktur.faktur_number == "010-00000001"
        assert faktur.status == FakturStatus.DRAFT.value
        service._tax_repo.save_faktur_pajak.assert_called_once()
        service._uow.commit.assert_called_once()
        assert service._stats["faktur_created"] == 1

    @pytest.mark.asyncio
    async def test_create_faktur_pajak_keluaran_invalid_npwp(self, service, legal_entity_id):
        with pytest.raises(InvalidNPWPError, match="Invalid NPWP format"):
            await service.create_faktur_pajak_keluaran(
                legal_entity_id=legal_entity_id,
                npwp_penjual="1234",  # invalid
                npwp_pembeli="12.345.678.9-012.346",
                nama_pembeli="PT Customer",
                dpp=Decimal("1000"),
                ppn=Decimal("110"),
                ppnbm=Decimal("0"),
            )

    # ---- submit_faktur_pajak_to_coretax ----

    @pytest.mark.asyncio
    async def test_submit_faktur_pajak_success(self, service, sample_faktur, user_id):
        service._tax_repo.get_faktur_pajak.return_value = sample_faktur
        service._coretax.submit_faktur.return_value = {"success": True, "approval_code": "APP-123", "qr_code": "QR-123"}
        result = await service.submit_faktur_pajak_to_coretax(sample_faktur.id, user_id)
        assert result.status == FakturStatus.APPROVED.value
        assert result.approval_code == "APP-123"
        assert result.qr_code == "QR-123"
        service._tax_repo.save_faktur_pajak.assert_called()
        service._uow.commit.assert_called()
        assert service._stats["faktur_submitted"] == 1
        # Events published (submitted and approved)
        assert service._event_publisher.publish.call_count == 2

    @pytest.mark.asyncio
    async def test_submit_faktur_pajak_rejected(self, service, sample_faktur, user_id):
        service._tax_repo.get_faktur_pajak.return_value = sample_faktur
        service._coretax.submit_faktur.return_value = {"success": False, "message": "NPWP invalid"}
        with pytest.raises(CoretaxSubmissionError, match="Coretax rejection"):
            await service.submit_faktur_pajak_to_coretax(sample_faktur.id, user_id)
        assert sample_faktur.status == FakturStatus.REJECTED.value
        # Event published: submitted, then rejected
        assert service._event_publisher.publish.call_count == 2

    @pytest.mark.asyncio
    async def test_submit_faktur_pajak_not_found(self, service):
        service._tax_repo.get_faktur_pajak.return_value = None
        with pytest.raises(FakturPajakError, match="not found"):
            await service.submit_faktur_pajak_to_coretax(uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_submit_faktur_pajak_no_coretax(self, service, sample_faktur):
        service._coretax = None
        service._tax_repo.get_faktur_pajak.return_value = sample_faktur
        with pytest.raises(CoretaxSubmissionError, match="Coretax client not configured"):
            await service.submit_faktur_pajak_to_coretax(sample_faktur.id, uuid4())

    # ---- report_spt_masa_ppn ----

    @pytest.mark.asyncio
    async def test_report_spt_masa_ppn(self, service, legal_entity_id, user_id):
        # Mock faktur lists
        keluaran = [
            MagicMock(dpp=Decimal("1000"), ppn=Decimal("110")),
            MagicMock(dpp=Decimal("2000"), ppn=Decimal("220")),
        ]
        masukan = [
            MagicMock(ppn=Decimal("50")),
            MagicMock(ppn=Decimal("30")),
        ]
        service._tax_repo.list_faktur_keluaran.return_value = keluaran
        service._tax_repo.list_faktur_masukan.return_value = masukan
        service._coretax.submit_spt_ppn.return_value = {"status": "SUBMITTED"}

        spt = await service.report_spt_masa_ppn(
            legal_entity_id=legal_entity_id,
            masa_pajak="2025-01",
            kompensasi_dari_masa_sebelumnya=Decimal("10"),
            user_id=user_id,
        )
        assert spt.total_ppn_keluaran == Decimal("330")  # 110+220
        assert spt.total_ppn_masukan == Decimal("80")  # 50+30
        assert spt.ppn_kurang_bayar == Decimal("240")  # 330 - 80 - 10
        assert spt.ppn_lebih_bayar == Decimal("0")
        assert spt.status == "SUBMITTED"
        service._tax_repo.save_spt_ppn.assert_called()
        service._uow.commit.assert_called()
        assert service._stats["spt_submitted"] == 1

    @pytest.mark.asyncio
    async def test_report_spt_masa_ppn_lebih_bayar(self, service, legal_entity_id):
        # More input than output
        service._tax_repo.list_faktur_keluaran.return_value = [MagicMock(dpp=Decimal("1000"), ppn=Decimal("110"))]
        service._tax_repo.list_faktur_masukan.return_value = [MagicMock(ppn=Decimal("200"))]
        service._coretax.submit_spt_ppn.return_value = {"status": "SUBMITTED"}

        spt = await service.report_spt_masa_ppn(
            legal_entity_id=legal_entity_id,
            masa_pajak="2025-01",
            kompensasi_dari_masa_sebelumnya=Decimal("0"),
        )
        assert spt.ppn_kurang_bayar == Decimal("0")
        assert spt.ppn_lebih_bayar == Decimal("90")  # 200 - 110

    @pytest.mark.asyncio
    async def test_report_spt_masa_ppn_no_coretax(self, service, legal_entity_id):
        service._coretax = None
        service._tax_repo.list_faktur_keluaran.return_value = []
        service._tax_repo.list_faktur_masukan.return_value = []
        spt = await service.report_spt_masa_ppn(
            legal_entity_id=legal_entity_id,
            masa_pajak="2025-01",
        )
        assert spt.status == "GENERATED"

    # ---- calculate_pph21 ----

    @pytest.mark.asyncio
    async def test_calculate_pph21(self, service):
        employee_id = uuid4()
        request = PPh21CalculationRequest(
            employee_id=employee_id,
            gross_income=Decimal("10000000"),  # 10jt/month
            period_month=1,
            period_year=2025,
        )
        # Mock employee tax data
        employee = MagicMock()
        employee.marital_status = "TK"
        employee.dependents = 0
        service._tax_repo.get_employee_tax_data.return_value = employee

        # Mock PPh21Calculator methods
        mock_pph21 = MagicMock()
        mock_pph21.get_ptkp.return_value = Decimal("54000000")  # annual PTKP TK0
        mock_pph21.get_tariff.return_value = Decimal("0.05")  # 5% for first bracket
        with patch.object(service, "_get_pph21_calculator", return_value=mock_pph21):
            response = await service.calculate_pph21(request)
            # Annual gross = 120,000,000, PTKP = 54,000,000, PKP = 66,000,000
            # Tax = 66,000,000 * 5% = 3,300,000 per year, monthly = 275,000
            assert response.pph_21_due == Decimal("275000")
            assert response.tax_rate_applied == Decimal("0.05")
            assert service._stats["calculations"] == 1

    @pytest.mark.asyncio
    async def test_calculate_pph21_employee_not_found(self, service):
        service._tax_repo.get_employee_tax_data.return_value = None
        request = PPh21CalculationRequest(
            employee_id=uuid4(),
            gross_income=Decimal("1000"),
            period_month=1,
            period_year=2025,
        )
        with pytest.raises(TaxServiceError, match="tax data not found"):
            await service.calculate_pph21(request)

    # ---- calculate_pph23 ----

    @pytest.mark.asyncio
    async def test_calculate_pph23_success(self, service):
        supplier_id = uuid4()
        request = PPh23CalculationRequest(
            supplier_id=supplier_id,
            gross_amount=Decimal("10000000"),
            transaction_type="JASA",
            is_has_npwp=True,
            period="2025-01",
        )
        # Mock rate registry
        mock_registry = AsyncMock()
        mock_registry.get_pph23_rate.return_value = Decimal("0.02")  # 2%
        with patch.object(service, "_get_rate_registry", return_value=mock_registry):
            response = await service.calculate_pph23(request)
            assert response.tax_rate == Decimal("0.02")
            assert response.pph_23_due == Decimal("200000")  # 10,000,000 * 2%
            assert response.tax_object_code == "24-104-01"  # JASA
            assert service._stats["calculations"] == 1

    @pytest.mark.asyncio
    async def test_calculate_pph23_rate_not_found(self, service):
        request = PPh23CalculationRequest(
            supplier_id=uuid4(),
            gross_amount=Decimal("1000"),
            transaction_type="UNKNOWN",
        )
        mock_registry = AsyncMock()
        mock_registry.get_pph23_rate.return_value = None
        with patch.object(service, "_get_rate_registry", return_value=mock_registry):
            with pytest.raises(TaxRateNotFoundError):
                await service.calculate_pph23(request)

    # ---- PKP status ----

    @pytest.mark.asyncio
    async def test_change_pkp_status_success(self, service, legal_entity_id, user_id):
        service._tax_repo.get_pkp_status.return_value = "NON_PKP"
        request = PKPStatusChangeRequest(
            legal_entity_id=legal_entity_id,
            new_status="PKP",
            reason="Revenue exceeded",
            changed_by=user_id,
        )
        result = await service.change_pkp_status(request)
        assert result == PKPStatus.PKP
        service._tax_repo.save_pkp_status.assert_called_once()
        service._uow.commit.assert_called_once()
        assert service._stats["pkp_changes"] == 1

    @pytest.mark.asyncio
    async def test_change_pkp_status_already_same(self, service, legal_entity_id):
        service._tax_repo.get_pkp_status.return_value = "PKP"
        request = PKPStatusChangeRequest(
            legal_entity_id=legal_entity_id,
            new_status="PKP",
            reason="",
        )
        result = await service.change_pkp_status(request)
        assert result == PKPStatus.PKP
        service._tax_repo.save_pkp_status.assert_not_called()
        assert service._stats["pkp_changes"] == 0

    @pytest.mark.asyncio
    async def test_change_pkp_status_invalid(self, service, legal_entity_id):
        request = PKPStatusChangeRequest(
            legal_entity_id=legal_entity_id,
            new_status="INVALID",
            reason="",
        )
        with pytest.raises(PKPStatusError, match="Invalid PKP status"):
            await service.change_pkp_status(request)

    @pytest.mark.asyncio
    async def test_get_pkp_status(self, service, legal_entity_id):
        service._tax_repo.get_pkp_status.return_value = "PKP"
        status = await service.get_pkp_status(legal_entity_id)
        assert status == "PKP"

    # ---- meterai ----

    @pytest.mark.asyncio
    async def test_use_meterai_10000(self, service, legal_entity_id, user_id):
        request = MeteraiUsageRequest(
            legal_entity_id=legal_entity_id,
            document_type="INVOICE",
            document_number="INV-001",
            meterai_type="10000",
            used_date=date.today(),
            used_by=user_id,
        )
        result = await service.use_meterai(request)
        assert result["amount"] == Decimal("10000")
        service._tax_repo.save_meterai_usage.assert_called_once()
        service._uow.commit.assert_called_once()
        assert service._stats["meterai_used"] == 1

    @pytest.mark.asyncio
    async def test_use_meterai_6000(self, service, legal_entity_id):
        request = MeteraiUsageRequest(
            legal_entity_id=legal_entity_id,
            document_type="OTHER",
            document_number="DOC-001",
            meterai_type="6000",
            used_date=date.today(),
            used_by=uuid4(),
        )
        result = await service.use_meterai(request)
        assert result["amount"] == Decimal("6000")

    # ---- update_tax_profile ----

    @pytest.mark.asyncio
    async def test_update_tax_profile(self, service, legal_entity_id, user_id):
        profile_data = {"address": "Jl. Sudirman", "business_type": "MANUFACTURING"}
        result = await service.update_tax_profile(
            legal_entity_id=legal_entity_id,
            profile_data=profile_data,
            updated_by=user_id,
        )
        assert result["updated"] is True
        service._tax_repo.save_tax_profile.assert_called_once()
        service._uow.commit.assert_called_once()
        service._event_publisher.publish.assert_called_once()

    # ---- stats and audit ----

    def test_get_stats(self, service):
        service._stats["calculations"] = 5
        stats = service.get_stats()
        assert stats["calculations"] == 5
        # Should be a copy
        stats["calculations"] = 10
        assert service._stats["calculations"] == 5

    def test_get_audit_trail(self, service):
        service._record_audit("test", {"key": "value"})
        trail = service.get_audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "test"


# ============================================================================
# Tests for module-level audit decorator and factory
# ============================================================================

def test_audit_decorator():
    def dummy():
        return 42
    decorated = audit(dummy)
    assert decorated() == 42


@pytest.mark.asyncio
async def test_create_tax_service(mock_tax_repo, mock_coretax, mock_uow, mock_event_publisher):
    service = await create_tax_service(
        tax_repo=mock_tax_repo,
        coretax_client=mock_coretax,
        uow=mock_uow,
        event_publisher=mock_event_publisher,
    )
    assert isinstance(service, TaxService)
    assert service._tax_repo == mock_tax_repo
