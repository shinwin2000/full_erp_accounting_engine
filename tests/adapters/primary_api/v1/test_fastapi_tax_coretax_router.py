# tests/adapters/primary_api/v1/test_fastapi_tax_coretax_router.py
"""
Comprehensive unit tests for FastAPI Tax & Coretax Router.

Perbaikan:
- Semua async test diberi @pytest.mark.asyncio
- Flaky tests menggunakan mock datetime (FIXED_NOW, FIXED_DATE)
- Duplikasi struktural dihilangkan dengan parametrize
- Mock quality ditingkatkan: AsyncMock, verifikasi panggilan
- Negative path ditambahkan: ValueError, Exception
- Semua assertion bermakna
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException, UploadFile
from fastapi.responses import Response

from adapters.primary_api.v1.fastapi_tax_coretax_router import (
    CoretaxDashboardResponseSchema,
    CoretaxSubmissionResponseSchema,
    EBupotCreateSchema,
    EBupotResponseSchema,
    EBupotStatus,
    EMeteraiPurchaseSchema,
    EMeteraiStatus,
    EMeteraiValidateSchema,
    FakturPajakCreateSchema,
    FakturPajakResponseSchema,
    FakturStatus,
    IdempotencyManager,
    NSFPRequestSchema,
    NSFPResponseSchema,
    NTPNValidationResponseSchema,
    NTPNValidationSchema,
    SPTMasaPPH21CreateSchema,
    SPTMasaPPH23CreateSchema,
    SPTMasaPPNCreateSchema,
    SPTStatus,
    SPTTahunanBadanCreateSchema,
    SPTType,
    TaxCalculationRequestSchema,
    TaxCalculationResponseSchema,
    TaxFilingStatusSchema,
    TaxType,
    bulk_submit_faktur,
    calculate_tax,
    cancel_e_bupot,
    cancel_faktur_pajak,
    create_e_bupot,
    create_faktur_pajak,
    export_tax_data,
    get_coretax_bulk_use_case,
    get_coretax_dashboard,
    get_coretax_service,
    get_faktur_pajak,
    get_nsfp_quota,
    get_tax_due_dates,
    get_tax_filing_status,
    get_tax_service,
    get_tax_summary,
    health,
    info,
    list_e_bupot,
    list_faktur_pajak,
    ping,
    purchase_e_meterai,
    request_nsfp,
    submit_spt_pph21,
    submit_spt_pph23,
    submit_spt_ppn,
    submit_spt_tahunan_badan,
    validate_e_meterai,
    validate_ntpn,
)

# ============================================================================
# FIXED DATETIME - untuk menghindari flaky tests
# ============================================================================
FIXED_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
FIXED_DATE = date(2026, 1, 1)


@pytest.fixture(autouse=True)
def mock_datetime_now():
    """Mock datetime.now() dan date.today() untuk menghindari flaky tests."""
    with patch("adapters.primary_api.v1.fastapi_tax_coretax_router.datetime") as mock_dt, \
         patch("adapters.primary_api.v1.fastapi_tax_coretax_router.date") as mock_date:
        mock_dt.now.return_value = FIXED_NOW
        mock_date.today.return_value = FIXED_DATE
        yield


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_token_payload():
    return MagicMock(user_id=uuid4())


@pytest.fixture
def mock_legal_entity_id():
    return uuid4()


@pytest.fixture
def mock_tax_service():
    """Create a fully mocked TaxService with realistic return values."""
    svc = AsyncMock()

    # Tax calculation
    svc.calculate_tax.return_value = MagicMock(
        tax_type="ppn",
        taxable_base=Decimal("1000"),
        tax_rate=Decimal("0.11"),
        tax_amount=Decimal("110"),
        notes="PPN 11%",
        calculated_at=FIXED_NOW,
    )

    # Filing status
    svc.get_filing_status.return_value = [
        MagicMock(
            tax_type="ppn",
            period="2026-05",
            due_date=FIXED_DATE,
            status="submitted",
            submitted_at=FIXED_NOW,
            approved_at=None,
            is_late=False,
            days_overdue=0,
        )
    ]

    # Due dates
    svc.get_upcoming_due_dates.return_value = [
        MagicMock(
            tax_type="ppn",
            period="2026-06",
            due_date=FIXED_DATE,
            is_overdue=False,
            days_remaining=30,
            estimated_amount=Decimal("100000"),
            status="pending",
        )
    ]

    # Summary
    svc.get_tax_summary.return_value = MagicMock(
        ppn_output=Decimal("100000"),
        ppn_input=Decimal("50000"),
        ppn_net=Decimal("50000"),
        ppn_payable=Decimal("50000"),
        ppn_credited=Decimal("0"),
        pph21=Decimal("10000"),
        pph22=Decimal("0"),
        pph23=Decimal("20000"),
        pph25=Decimal("0"),
        pph26=Decimal("0"),
        pph4_2=Decimal("0"),
        pph_badan=Decimal("0"),
        pph_total=Decimal("30000"),
        total_tax=Decimal("80000"),
        paid_amount=Decimal("30000"),
        outstanding=Decimal("50000"),
    )

    # Export
    svc.export_tax_data.return_value = b"csv data"

    return svc


@pytest.fixture
def mock_coretax_service():
    """Create a fully mocked CoretaxService with realistic return values."""
    svc = AsyncMock()

    # Faktur
    def mock_faktur(**kwargs):
        defaults = {
            "id": uuid4(),
            "faktur_number": "010-2026-05-00000001",
            "nsfp": "00000001",
            "reference_id": uuid4(),
            "faktur_date": FIXED_DATE,
            "npwp_penjual": "123456789012345",
            "npwp_pembeli": "987654321098765",
            "nama_pembeli": "PT Pembeli",
            "dpp": Decimal("100000"),
            "ppn_rate": Decimal("0.11"),
            "ppn_amount": Decimal("11000"),
            "ppn_bm_amount": Decimal("0"),
            "status": "draft",
            "approval_code": None,
            "qr_code": None,
            "rejection_reason": None,
            "submitted_at": None,
            "approved_at": None,
            "created_at": FIXED_NOW,
            "created_by": uuid4(),
            "version": 1,
        }
        defaults.update(kwargs)
        return MagicMock(**defaults)

    svc.create_faktur_pajak.return_value = mock_faktur()
    svc.get_faktur_pajak_by_id.return_value = mock_faktur()
    svc.cancel_faktur_pajak.return_value = mock_faktur(status="cancelled")
    svc.list_faktur_pajak.return_value = MagicMock(items=[mock_faktur()])

    # NSFP
    svc.request_nsfp.return_value = MagicMock(
        request_id=uuid4(),
        tahun=2026,
        bulan=5,
        nsfp_list=["00000001", "00000002"],
        jumlah=2,
        remaining_quota=48,
        requested_at=FIXED_NOW,
    )
    svc.get_nsfp_quota.return_value = MagicMock(
        total_quota=50,
        used=2,
        remaining=48,
        available_in_cache=10,
    )

    # NTPN
    svc.validate_ntpn.return_value = MagicMock(
        ntpn="1234567890123456",
        is_valid=True,
        message="Valid",
        taxpayer_id="123456789012345",
        taxpayer_name="PT Maju",
        tax_type="PPN",
        amount=Decimal("100000"),
        payment_date=FIXED_DATE,
        period="2026-05",
        validated_at=FIXED_NOW,
    )

    # SPT
    def mock_submission(**kwargs):
        defaults = {
            "id": uuid4(),
            "status": "success",
            "coretax_tracking_id": "TRK-001",
            "coretax_response": {"status": "ok"},
            "error_message": None,
            "created_at": FIXED_NOW,
            "submitted_at": FIXED_NOW,
        }
        defaults.update(kwargs)
        return MagicMock(**defaults)

    svc.submit_spt_ppn.return_value = mock_submission()
    svc.submit_spt_pph21.return_value = mock_submission()
    svc.submit_spt_pph23.return_value = mock_submission()
    svc.submit_spt_tahunan_badan.return_value = mock_submission()

    # e-Bupot
    def mock_bupot(**kwargs):
        defaults = {
            "id": uuid4(),
            "bupot_number": "BUPOT-001",
            "official_number": "OFF-001",
            "coretax_id": "COR-001",
            "status": "draft",
            "created_at": FIXED_NOW,
            "submitted_at": None,
            "approved_at": None,
            "version": 1,
        }
        defaults.update(kwargs)
        return MagicMock(**defaults)

    svc.create_e_bupot.return_value = mock_bupot()
    svc.cancel_e_bupot.return_value = mock_bupot(status="cancelled")
    svc.list_e_bupot.return_value = MagicMock(items=[mock_bupot()])

    # e-Meterai
    svc.validate_e_meterai.return_value = MagicMock(
        is_valid=True,
        status="active",
        value=Decimal("10000"),
        used_at=None,
        used_on_document=None,
        message="Valid",
    )
    svc.purchase_e_meterai.return_value = MagicMock(
        purchase_id=uuid4(),
        transaction_id="TXN-001",
        quantity=10,
        total_amount=Decimal("100000"),
        meterai_list=["1234567890123456-0001", "1234567890123456-0002"],
        status="success",
        purchased_at=FIXED_NOW,
    )

    # Dashboard
    svc.get_dashboard.return_value = MagicMock(
        nsfp_quota_remaining=100,
        nsfp_quota_used=50,
        faktur_submitted_today=5,
        faktur_approved_today=3,
        faktur_rejected_today=0,
        spt_submitted_this_month=10,
        spt_approved_this_month=7,
        spt_rejected_this_month=2,
        api_health="healthy",
        last_sync_at=FIXED_NOW,
        pending_faktur=2,
        pending_spt=1,
        pending_bupot=0,
    )

    return svc


@pytest.fixture
def mock_bulk_use_case():
    uc = AsyncMock()
    uc.submit_faktur_batch.return_value = MagicMock(
        batch_id=uuid4(),
        total_submitted=2,
        success_count=2,
        failed_count=0,
        failed_ids=[],
        errors=[],
    )
    return uc


# ============================================================================
# IDEMPOTENCY MANAGER TESTS
# ============================================================================

class TestIdempotencyManager:
    def test_construction(self):
        instance = IdempotencyManager()
        assert isinstance(instance, IdempotencyManager)
        assert instance._storage == {}
        assert instance._ttl_seconds == 86400

    def test_get_cached_result_miss(self):
        instance = IdempotencyManager()
        result = instance.get_cached_result("key", "method")
        assert result is None

    def test_cache_and_retrieve(self):
        instance = IdempotencyManager()
        data = {"id": "123", "status": "ok"}
        instance.cache_result("key", "method", data)
        cached = instance.get_cached_result("key", "method")
        assert cached == data

    @patch("adapters.primary_api.v1.fastapi_tax_coretax_router.datetime")
    def test_cache_expiration(self, mock_dt):
        mock_dt.now.return_value = FIXED_NOW
        instance = IdempotencyManager()
        instance._ttl_seconds = 0
        instance.cache_result("key", "method", {"foo": "bar"})
        cached = instance.get_cached_result("key", "method")
        assert cached is None

    def test_key_generation_deterministic(self):
        instance = IdempotencyManager()
        key1 = instance._get_key("abc", "create_faktur_pajak")
        key2 = instance._get_key("abc", "create_faktur_pajak")
        key3 = instance._get_key("abc", "cancel_faktur_pajak")
        assert key1 == key2
        assert key1 != key3


# ============================================================================
# ENUM TESTS (parametrized untuk menghindari duplikasi)
# ============================================================================

ENUM_TEST_DATA = [
    (TaxType, [
        "PPN", "PPH_21", "PPH_22", "PPH_23", "PPH_26", "PPH_25", "PPH_29",
        "PPH_4_2", "PPH_BADAN", "PPH_FINAL"
    ]),
    (FakturStatus, [
        "DRAFT", "PENDING", "SUBMITTED", "APPROVED", "REJECTED",
        "CANCELLED", "VOID", "POSTED", "LOCKED", "ARCHIVED"
    ]),
    (SPTType, ["MASA_PPN", "MASA_PPH_21", "MASA_PPH_23", "TAHUNAN_BADAN", "TAHUNAN_OP"]),
    (SPTStatus, ["DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "CANCELLED", "LOCKED", "ARCHIVED"]),
    (EBupotStatus, ["DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "CANCELLED"]),
    (EMeteraiStatus, ["ACTIVE", "USED", "EXPIRED", "REVOKED", "PURCHASED"]),
]


class TestEnums:
    @pytest.mark.parametrize("enum_class, members", ENUM_TEST_DATA)
    def test_members_exist(self, enum_class, members):
        for member in members:
            assert hasattr(enum_class, member)

    @pytest.mark.parametrize("enum_class, members", ENUM_TEST_DATA)
    def test_member_is_instance(self, enum_class, members):
        first_member = getattr(enum_class, members[0])
        assert isinstance(first_member, enum_class)


# ============================================================================
# SCHEMA TESTS (parametrized)
# ============================================================================

SCHEMA_TEST_DATA = [
    (TaxCalculationRequestSchema, {
        "transaction_date": FIXED_DATE,
        "transaction_type": MagicMock(value="sale"),
        "amount": Decimal("1000"),
        "tax_type": TaxType.PPN,
        "npwp": "123456789012345",
        "counterparty_npwp": "987654321098765",
        "is_import": False,
        "has_tax_invoice": True,
        "has_npwp": True,
        "is_public_company": False,
        "annual_revenue": Decimal("1000000000"),
        "special_rate": Decimal("0.1"),
    }),
    (TaxCalculationResponseSchema, {
        "tax_type": TaxType.PPN,
        "taxable_base": Decimal("1000"),
        "tax_rate": Decimal("0.11"),
        "tax_rate_percent": Decimal("11"),
        "tax_amount": Decimal("110"),
        "notes": "PPN 11%",
        "calculated_at": FIXED_NOW,
    }),
    (FakturPajakCreateSchema, {
        "reference_id": uuid4(),
        "faktur_date": FIXED_DATE,
        "npwp_pembeli": "123456789012345",
        "nama_pembeli": "PT Pembeli",
        "alamat_pembeli": "Jl. Pembeli",
        "dpp": Decimal("100000"),
        "ppn_rate": Decimal("0.11"),
        "is_ppn_bm": False,
        "ppn_bm_rate": Decimal("0"),
        "note_type": "normal",
        "correction_sequence": 0,
        "description": "Test faktur",
    }),
    (FakturPajakResponseSchema, {
        "id": uuid4(),
        "faktur_number": "010-2026-05-00000001",
        "nsfp": "00000001",
        "reference_id": uuid4(),
        "faktur_date": FIXED_DATE,
        "npwp_penjual": "123456789012345",
        "npwp_pembeli": "987654321098765",
        "nama_pembeli": "PT Pembeli",
        "dpp": Decimal("100000"),
        "ppn_rate": Decimal("0.11"),
        "ppn_amount": Decimal("11000"),
        "ppn_bm_amount": Decimal("0"),
        "status": FakturStatus.DRAFT,
        "approval_code": None,
        "qr_code": None,
        "rejection_reason": None,
        "submitted_at": None,
        "approved_at": None,
        "created_at": FIXED_NOW,
        "created_by": uuid4(),
        "version": 1,
    }),
    (NSFPRequestSchema, {"tahun": 2026, "bulan": 5, "jumlah": 50}),
    (NSFPResponseSchema, {
        "request_id": uuid4(),
        "tahun": 2026,
        "bulan": 5,
        "nsfp_list": ["00000001", "00000002"],
        "jumlah": 2,
        "remaining_quota": 48,
        "requested_at": FIXED_NOW,
    }),
    (NTPNValidationSchema, {
        "ntpn": "1234567890123456",
        "amount": Decimal("100000"),
        "payment_date": FIXED_DATE,
        "npwp": "123456789012345",
        "tax_type": "PPN",
    }),
    (NTPNValidationResponseSchema, {
        "ntpn": "1234567890123456",
        "is_valid": True,
        "validation_message": "Valid",
        "taxpayer_id": "123456789012345",
        "taxpayer_name": "PT Maju",
        "tax_type": "PPN",
        "amount": Decimal("100000"),
        "payment_date": FIXED_DATE,
        "period": "2026-05",
        "validated_at": FIXED_NOW,
    }),
    (SPTMasaPPNCreateSchema, {
        "masa_pajak": 5,
        "tahun_pajak": 2026,
        "total_penyerahan": Decimal("100000000"),
        "total_ppn_keluaran": Decimal("11000000"),
        "total_ppn_masukan": Decimal("5000000"),
        "kompensasi_dari_masa_sebelumnya": Decimal("0"),
        "ppn_kurang_bayar": Decimal("6000000"),
        "ppn_lebih_bayar": Decimal("0"),
        "ntpn_list": ["1234567890123456"],
    }),
    (SPTMasaPPH21CreateSchema, {
        "masa_pajak": 5,
        "tahun_pajak": 2026,
        "total_bruto": Decimal("50000000"),
        "total_pph_terutang": Decimal("5000000"),
        "jumlah_bayar": Decimal("5000000"),
        "ntpn": "1234567890123456",
    }),
    (SPTMasaPPH23CreateSchema, {
        "masa_pajak": 5,
        "tahun_pajak": 2026,
        "jenis_pajak": "23",
        "total_dpp": Decimal("10000000"),
        "total_pph_dipotong": Decimal("2000000"),
        "total_bayar": Decimal("2000000"),
        "kompensasi": Decimal("0"),
        "ntpn": "1234567890123456",
    }),
    (SPTTahunanBadanCreateSchema, {
        "tahun_pajak": 2026,
        "penghasilan_neto_komersial": Decimal("100000000"),
        "penghasilan_neto_fiskal": Decimal("100000000"),
        "kompensasi_kerugian": Decimal("0"),
        "penghasilan_kena_pajak": Decimal("100000000"),
        "pph_terutang": Decimal("22000000"),
        "total_kredit_pajak": Decimal("5000000"),
        "kurang_bayar": Decimal("17000000"),
        "lebih_bayar": Decimal("0"),
        "ntpn": "1234567890123456",
    }),
    (EBupotCreateSchema, {
        "masa_pajak": 5,
        "tahun_pajak": 2026,
        "npwp_pemotong": "123456789012345",
        "npwp_penerima": "987654321098765",
        "nama_penerima": "PT Penerima",
        "alamat_penerima": "Jl. Penerima",
        "jenis_pajak": "23",
        "jenis_penghasilan_code": "01",
        "dpp": Decimal("100000"),
        "tarif": Decimal("0.02"),
        "tanggal_pemotongan": FIXED_DATE,
        "invoice_reference": "INV-001",
        "keterangan": "Test",
    }),
    (EBupotResponseSchema, {
        "id": uuid4(),
        "bupot_number": "BUPOT-001",
        "official_number": "OFF-001",
        "coretax_id": "COR-001",
        "status": EBupotStatus.DRAFT,
        "created_at": FIXED_NOW,
        "submitted_at": None,
        "approved_at": None,
        "version": 1,
    }),
    (EMeteraiValidateSchema, {"meterai_code": "MTR-001", "document_id": "DOC-001"}),
    (EMeteraiPurchaseSchema, {
        "quantity": 10,
        "npwp": "123456789012345",
        "purpose": "Faktur",
    }),
    (CoretaxDashboardResponseSchema, {
        "nsfp_quota_remaining": 100,
        "nsfp_quota_used": 50,
        "faktur_submitted_today": 5,
        "faktur_approved_today": 3,
        "faktur_rejected_today": 0,
        "spt_submitted_this_month": 10,
        "spt_approved_this_month": 7,
        "spt_rejected_this_month": 2,
        "api_health": "healthy",
        "last_sync_at": FIXED_NOW,
        "pending_faktur": 2,
        "pending_spt": 1,
        "pending_bupot": 0,
    }),
    (CoretaxSubmissionResponseSchema, {
        "submission_id": uuid4(),
        "submission_type": "FAKTUR",
        "reference_number": "REF-001",
        "status": "success",
        "coretax_tracking_id": "TRK-001",
        "coretax_response": {"status": "ok"},
        "error_message": None,
        "created_at": FIXED_NOW,
        "submitted_at": FIXED_NOW,
    }),
    (TaxFilingStatusSchema, {
        "tax_type": TaxType.PPN,
        "period": "2026-05",
        "due_date": FIXED_DATE,
        "status": "submitted",
        "submitted_at": FIXED_NOW,
        "approved_at": None,
        "is_late": False,
        "days_overdue": 0,
    }),
]


class TestSchemas:
    @pytest.mark.parametrize("schema_class, kwargs", SCHEMA_TEST_DATA)
    def test_construction_success(self, schema_class, kwargs):
        instance = schema_class(**kwargs)
        assert isinstance(instance, schema_class)
        first_key = next(iter(kwargs))
        assert getattr(instance, first_key) == kwargs[first_key]


# ============================================================================
# HEALTH CHECK TESTS
# ============================================================================

def test_ping():
    result = ping()
    assert result == {"status": "ok", "service": "tax-router"}


def test_health():
    result = health()
    assert result == {"status": "healthy"}


def test_info():
    result = info()
    assert result["version"] == "1.0"
    assert result["name"] == "Tax & Coretax Router"


# ============================================================================
# DEPENDENCY INJECTION TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_get_tax_service():
    request = MagicMock()
    request.app.state.container = MagicMock()
    request.app.state.container.resolve.return_value = "tax_service"
    result = await get_tax_service(request)
    assert result == "tax_service"


@pytest.mark.asyncio
async def test_get_coretax_service():
    request = MagicMock()
    request.app.state.container = MagicMock()
    request.app.state.container.resolve.return_value = "coretax_service"
    result = await get_coretax_service(request)
    assert result == "coretax_service"


@pytest.mark.asyncio
async def test_get_coretax_bulk_use_case():
    request = MagicMock()
    request.app.state.container = MagicMock()
    request.app.state.container.resolve.return_value = "bulk_use_case"
    result = await get_coretax_bulk_use_case(request)
    assert result == "bulk_use_case"


# ============================================================================
# TAX CALCULATION TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_calculate_tax_success(mock_tax_service, mock_legal_entity_id):
    request = TaxCalculationRequestSchema(
        transaction_date=FIXED_DATE,
        transaction_type=MagicMock(value="sale"),
        amount=Decimal("1000"),
        tax_type=TaxType.PPN,
        npwp="123456789012345",
        counterparty_npwp="987654321098765",
        is_import=False,
        has_tax_invoice=True,
        has_npwp=True,
        is_public_company=False,
        annual_revenue=Decimal("1000000000"),
        special_rate=Decimal("0.1"),
    )
    result = await calculate_tax(
        request=request,
        _permission=None,
        legal_entity_id=mock_legal_entity_id,
        tax_service=mock_tax_service,
    )
    assert isinstance(result, TaxCalculationResponseSchema)
    assert result.tax_type == TaxType.PPN
    assert result.tax_amount == Decimal("110")
    mock_tax_service.calculate_tax.assert_called_once()

    # Verify called with correct parameters
    call_kwargs = mock_tax_service.calculate_tax.call_args[1]
    assert call_kwargs["legal_entity_id"] == mock_legal_entity_id
    assert call_kwargs["amount"] == Decimal("1000")
    assert call_kwargs["tax_type"] == "ppn"


@pytest.mark.parametrize("side_effect, expected_status", [
    (ValueError("Invalid tax type"), 422),
    (Exception("DB error"), 500),
])
@pytest.mark.asyncio
async def test_calculate_tax_errors(mock_tax_service, mock_legal_entity_id,
                                    side_effect, expected_status):
    mock_tax_service.calculate_tax.side_effect = side_effect
    request = TaxCalculationRequestSchema(
        transaction_date=FIXED_DATE,
        transaction_type=MagicMock(value="sale"),
        amount=Decimal("1000"),
        tax_type=TaxType.PPN,
    )
    with pytest.raises(HTTPException) as exc:
        await calculate_tax(
            request=request,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            tax_service=mock_tax_service,
        )
    assert exc.value.status_code == expected_status


# ============================================================================
# FAKTUR PAJAK TESTS
# ============================================================================

@pytest.mark.asyncio
class TestFakturPajak:
    async def test_create_faktur_pajak_success(self, mock_coretax_service, mock_token_payload, mock_legal_entity_id):
        request = FakturPajakCreateSchema(
            reference_id=uuid4(),
            faktur_date=FIXED_DATE,
            npwp_pembeli="123456789012345",
            nama_pembeli="PT Pembeli",
            dpp=Decimal("100000"),
            ppn_rate=Decimal("0.11"),
        )
        result = await create_faktur_pajak(
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            coretax_service=mock_coretax_service,
        )
        assert isinstance(result, FakturPajakResponseSchema)
        assert result.faktur_number == "010-2026-05-00000001"
        assert result.dpp == Decimal("100000")
        mock_coretax_service.create_faktur_pajak.assert_called_once()

    async def test_create_faktur_pajak_idempotency(self, mock_coretax_service, mock_token_payload, mock_legal_entity_id):
        request = FakturPajakCreateSchema(
            reference_id=uuid4(),
            faktur_date=FIXED_DATE,
            npwp_pembeli="123456789012345",
            nama_pembeli="PT Pembeli",
            dpp=Decimal("100000"),
            ppn_rate=Decimal("0.11"),
        )
        with patch("adapters.primary_api.v1.fastapi_tax_coretax_router._idempotency_manager") as mock_im:
            cached = {
                "id": str(uuid4()),
                "faktur_number": "010-2026-05-00000001",
                "nsfp": "00000001",
                "reference_id": str(uuid4()),
                "faktur_date": FIXED_DATE.isoformat(),
                "npwp_penjual": "123456789012345",
                "npwp_pembeli": "987654321098765",
                "nama_pembeli": "PT Pembeli",
                "dpp": "100000",
                "ppn_rate": "0.11",
                "ppn_amount": "11000",
                "ppn_bm_amount": "0",
                "status": "draft",
                "approval_code": None,
                "qr_code": None,
                "rejection_reason": None,
                "submitted_at": None,
                "approved_at": None,
                "created_at": FIXED_NOW.isoformat(),
                "created_by": str(uuid4()),
                "version": 1,
            }
            mock_im.get_cached_result.return_value = cached
            result = await create_faktur_pajak(
                request=request,
                idempotency_key="key123",
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                coretax_service=mock_coretax_service,
            )
            assert isinstance(result, FakturPajakResponseSchema)
            assert result.faktur_number == "010-2026-05-00000001"
            mock_coretax_service.create_faktur_pajak.assert_not_called()

    async def test_list_faktur_pajak_success(self, mock_coretax_service, mock_legal_entity_id):
        result = await list_faktur_pajak(
            status=FakturStatus.DRAFT,
            start_date=FIXED_DATE,
            end_date=FIXED_DATE,
            page=1,
            page_size=10,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            coretax_service=mock_coretax_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], FakturPajakResponseSchema)
        mock_coretax_service.list_faktur_pajak.assert_called_once()

    async def test_get_faktur_pajak_success(self, mock_coretax_service, mock_legal_entity_id):
        faktur_id = uuid4()
        result = await get_faktur_pajak(
            faktur_id=faktur_id,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            coretax_service=mock_coretax_service,
        )
        assert isinstance(result, FakturPajakResponseSchema)
        assert result.faktur_number == "010-2026-05-00000001"
        mock_coretax_service.get_faktur_pajak_by_id.assert_called_once_with(faktur_id, mock_legal_entity_id)

    async def test_get_faktur_pajak_not_found(self, mock_coretax_service, mock_legal_entity_id):
        mock_coretax_service.get_faktur_pajak_by_id.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_faktur_pajak(
                faktur_id=uuid4(),
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                coretax_service=mock_coretax_service,
            )
        assert exc.value.status_code == 404

    async def test_cancel_faktur_pajak_success(self, mock_coretax_service, mock_token_payload, mock_legal_entity_id):
        faktur_id = uuid4()
        result = await cancel_faktur_pajak(
            faktur_id=faktur_id,
            reason="Test reason",
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            coretax_service=mock_coretax_service,
        )
        assert result["status"] == "cancelled"
        assert "cancelled successfully" in result["message"]
        mock_coretax_service.cancel_faktur_pajak.assert_called_once_with(
            faktur_id=faktur_id,
            legal_entity_id=mock_legal_entity_id,
            reason="Test reason",
            cancelled_by=mock_token_payload.user_id,
        )

    async def test_cancel_faktur_pajak_not_found(self, mock_coretax_service, mock_token_payload, mock_legal_entity_id):
        mock_coretax_service.cancel_faktur_pajak.return_value = None
        with pytest.raises(HTTPException) as exc:
            await cancel_faktur_pajak(
                faktur_id=uuid4(),
                reason="Test",
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                coretax_service=mock_coretax_service,
            )
        assert exc.value.status_code == 404

    async def test_cancel_faktur_pajak_value_error(self, mock_coretax_service, mock_token_payload, mock_legal_entity_id):
        mock_coretax_service.cancel_faktur_pajak.side_effect = ValueError("Invalid reason")
        with pytest.raises(HTTPException) as exc:
            await cancel_faktur_pajak(
                faktur_id=uuid4(),
                reason="Test",
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                coretax_service=mock_coretax_service,
            )
        assert exc.value.status_code == 422


# ============================================================================
# NSFP TESTS
# ============================================================================

@pytest.mark.asyncio
class TestNSFP:
    async def test_request_nsfp_success(self, mock_coretax_service, mock_token_payload, mock_legal_entity_id):
        request = NSFPRequestSchema(tahun=2026, bulan=5, jumlah=2)
        result = await request_nsfp(
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            coretax_service=mock_coretax_service,
        )
        assert isinstance(result, NSFPResponseSchema)
        assert result.tahun == 2026
        assert result.bulan == 5
        assert result.jumlah == 2
        assert len(result.nsfp_list) == 2
        mock_coretax_service.request_nsfp.assert_called_once()

    async def test_request_nsfp_idempotency(self, mock_coretax_service, mock_token_payload, mock_legal_entity_id):
        request = NSFPRequestSchema(tahun=2026, bulan=5, jumlah=2)
        with patch("adapters.primary_api.v1.fastapi_tax_coretax_router._idempotency_manager") as mock_im:
            cached = {
                "request_id": str(uuid4()),
                "tahun": 2026,
                "bulan": 5,
                "nsfp_list": ["00000001", "00000002"],
                "jumlah": 2,
                "remaining_quota": 48,
                "requested_at": FIXED_NOW.isoformat(),
            }
            mock_im.get_cached_result.return_value = cached
            result = await request_nsfp(
                request=request,
                idempotency_key="key123",
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                coretax_service=mock_coretax_service,
            )
            assert isinstance(result, NSFPResponseSchema)
            assert result.tahun == 2026
            mock_coretax_service.request_nsfp.assert_not_called()

    async def test_get_nsfp_quota_success(self, mock_coretax_service, mock_legal_entity_id):
        result = await get_nsfp_quota(
            tahun=2026,
            bulan=5,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            coretax_service=mock_coretax_service,
        )
        assert result["tahun"] == 2026
        assert result["bulan"] == 5
        assert result["remaining"] == 48
        mock_coretax_service.get_nsfp_quota.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            tahun=2026,
            bulan=5,
        )


# ============================================================================
# NTPN TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_validate_ntpn_success(mock_coretax_service, mock_legal_entity_id):
    request = NTPNValidationSchema(
        ntpn="1234567890123456",
        amount=Decimal("100000"),
        payment_date=FIXED_DATE,
        npwp="123456789012345",
        tax_type="PPN",
    )
    result = await validate_ntpn(
        request=request,
        idempotency_key=None,
        _permission=None,
        legal_entity_id=mock_legal_entity_id,
        coretax_service=mock_coretax_service,
    )
    assert isinstance(result, NTPNValidationResponseSchema)
    assert result.is_valid is True
    assert result.ntpn == "1234567890123456"
    mock_coretax_service.validate_ntpn.assert_called_once()

    # Verify called with correct parameters
    call_kwargs = mock_coretax_service.validate_ntpn.call_args[1]
    assert call_kwargs["legal_entity_id"] == mock_legal_entity_id
    assert call_kwargs["ntpn"] == "1234567890123456"
    assert call_kwargs["amount"] == Decimal("100000")


# ============================================================================
# SPT SUBMISSION TESTS
# ============================================================================

@pytest.mark.asyncio
class TestSPTSubmission:
    async def test_submit_spt_ppn_success(self, mock_coretax_service, mock_token_payload, mock_legal_entity_id):
        request = SPTMasaPPNCreateSchema(
            masa_pajak=5,
            tahun_pajak=2026,
            total_penyerahan=Decimal("100000000"),
            total_ppn_keluaran=Decimal("11000000"),
            total_ppn_masukan=Decimal("5000000"),
            kompensasi_dari_masa_sebelumnya=Decimal("0"),
            ppn_kurang_bayar=Decimal("6000000"),
            ppn_lebih_bayar=Decimal("0"),
            ntpn_list=["1234567890123456"],
        )
        result = await submit_spt_ppn(
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            coretax_service=mock_coretax_service,
        )
        assert isinstance(result, CoretaxSubmissionResponseSchema)
        assert result.status == "success"
        assert result.coretax_tracking_id == "TRK-001"
        mock_coretax_service.submit_spt_ppn.assert_called_once()

    async def test_submit_spt_pph21_success(self, mock_coretax_service, mock_token_payload, mock_legal_entity_id):
        request = SPTMasaPPH21CreateSchema(
            masa_pajak=5,
            tahun_pajak=2026,
            total_bruto=Decimal("50000000"),
            total_pph_terutang=Decimal("5000000"),
            jumlah_bayar=Decimal("5000000"),
            ntpn="1234567890123456",
        )
        result = await submit_spt_pph21(
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            coretax_service=mock_coretax_service,
        )
        assert isinstance(result, CoretaxSubmissionResponseSchema)
        assert result.submission_type == "spt_pph21"
        mock_coretax_service.submit_spt_pph21.assert_called_once()

    async def test_submit_spt_pph23_success(self, mock_coretax_service, mock_token_payload, mock_legal_entity_id):
        request = SPTMasaPPH23CreateSchema(
            masa_pajak=5,
            tahun_pajak=2026,
            jenis_pajak="23",
            total_dpp=Decimal("10000000"),
            total_pph_dipotong=Decimal("2000000"),
            total_bayar=Decimal("2000000"),
            kompensasi=Decimal("0"),
            ntpn="1234567890123456",
        )
        result = await submit_spt_pph23(
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            coretax_service=mock_coretax_service,
        )
        assert isinstance(result, CoretaxSubmissionResponseSchema)
        assert result.submission_type.startswith("spt_pph23")
        mock_coretax_service.submit_spt_pph23.assert_called_once()

    async def test_submit_spt_tahunan_badan_success(self, mock_coretax_service, mock_token_payload, mock_legal_entity_id):
        request = SPTTahunanBadanCreateSchema(
            tahun_pajak=2026,
            penghasilan_neto_komersial=Decimal("100000000"),
            penghasilan_neto_fiskal=Decimal("100000000"),
            kompensasi_kerugian=Decimal("0"),
            penghasilan_kena_pajak=Decimal("100000000"),
            pph_terutang=Decimal("22000000"),
            total_kredit_pajak=Decimal("5000000"),
            kurang_bayar=Decimal("17000000"),
            lebih_bayar=Decimal("0"),
            ntpn="1234567890123456",
        )
        result = await submit_spt_tahunan_badan(
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            coretax_service=mock_coretax_service,
        )
        assert isinstance(result, CoretaxSubmissionResponseSchema)
        assert result.submission_type == "spt_tahunan_badan"
        mock_coretax_service.submit_spt_tahunan_badan.assert_called_once()

    async def test_spt_submission_value_error(self, mock_coretax_service, mock_token_payload, mock_legal_entity_id):
        mock_coretax_service.submit_spt_ppn.side_effect = ValueError("Invalid period")
        request = SPTMasaPPNCreateSchema(
            masa_pajak=13,
            tahun_pajak=2026,
            total_penyerahan=Decimal("0"),
            total_ppn_keluaran=Decimal("0"),
            total_ppn_masukan=Decimal("0"),
            kompensasi_dari_masa_sebelumnya=Decimal("0"),
            ppn_kurang_bayar=Decimal("0"),
            ppn_lebih_bayar=Decimal("0"),
            ntpn_list=[],
        )
        with pytest.raises(HTTPException) as exc:
            await submit_spt_ppn(
                request=request,
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                coretax_service=mock_coretax_service,
            )
        assert exc.value.status_code == 422


# ============================================================================
# E-BUPOT TESTS
# ============================================================================

@pytest.mark.asyncio
class TestEBupot:
    async def test_create_e_bupot_success(self, mock_coretax_service, mock_token_payload, mock_legal_entity_id):
        request = EBupotCreateSchema(
            masa_pajak=5,
            tahun_pajak=2026,
            npwp_pemotong="123456789012345",
            npwp_penerima="987654321098765",
            nama_penerima="PT Penerima",
            alamat_penerima="Jl. Penerima",
            jenis_pajak="23",
            jenis_penghasilan_code="01",
            dpp=Decimal("100000"),
            tarif=Decimal("0.02"),
            tanggal_pemotongan=FIXED_DATE,
            invoice_reference="INV-001",
            keterangan="Test",
        )
        result = await create_e_bupot(
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            coretax_service=mock_coretax_service,
        )
        assert isinstance(result, EBupotResponseSchema)
        assert result.bupot_number == "BUPOT-001"
        assert result.status == EBupotStatus.DRAFT
        mock_coretax_service.create_e_bupot.assert_called_once()

    async def test_list_e_bupot_success(self, mock_coretax_service, mock_legal_entity_id):
        result = await list_e_bupot(
            masa_pajak=5,
            tahun_pajak=2026,
            status=EBupotStatus.DRAFT,
            page=1,
            page_size=10,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            coretax_service=mock_coretax_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], EBupotResponseSchema)
        mock_coretax_service.list_e_bupot.assert_called_once()

    async def test_cancel_e_bupot_success(self, mock_coretax_service, mock_token_payload, mock_legal_entity_id):
        bupot_id = uuid4()
        result = await cancel_e_bupot(
            bupot_id=bupot_id,
            reason="Test reason",
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            coretax_service=mock_coretax_service,
        )
        assert result["status"] == "cancelled"
        mock_coretax_service.cancel_e_bupot.assert_called_once_with(
            bupot_id=bupot_id,
            legal_entity_id=mock_legal_entity_id,
            reason="Test reason",
            cancelled_by=mock_token_payload.user_id,
        )

    async def test_cancel_e_bupot_not_found(self, mock_coretax_service, mock_token_payload, mock_legal_entity_id):
        mock_coretax_service.cancel_e_bupot.return_value = None
        with pytest.raises(HTTPException) as exc:
            await cancel_e_bupot(
                bupot_id=uuid4(),
                reason="Test",
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                coretax_service=mock_coretax_service,
            )
        assert exc.value.status_code == 404


# ============================================================================
# E-METERAI TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_validate_e_meterai_success(mock_coretax_service, mock_legal_entity_id):
    request = EMeteraiValidateSchema(meterai_code="1234567890123456", document_id="DOC-001")
    result = await validate_e_meterai(
        request=request,
        idempotency_key=None,
        _permission=None,
        legal_entity_id=mock_legal_entity_id,
        coretax_service=mock_coretax_service,
    )
    assert result["is_valid"] is True
    assert result["status"] == "active"
    assert result["value"] == "10000"
    mock_coretax_service.validate_e_meterai.assert_called_once_with(
        legal_entity_id=mock_legal_entity_id,
        meterai_code="1234567890123456",
        document_id="DOC-001",
    )


@pytest.mark.asyncio
async def test_purchase_e_meterai_success(mock_coretax_service, mock_token_payload, mock_legal_entity_id):
    request = EMeteraiPurchaseSchema(quantity=10, npwp="123456789012345", purpose="Faktur")
    result = await purchase_e_meterai(
        request=request,
        idempotency_key=None,
        _permission=None,
        current_user=mock_token_payload,
        legal_entity_id=mock_legal_entity_id,
        coretax_service=mock_coretax_service,
    )
    assert result["quantity"] == 10
    assert result["total_amount"] == "100000"
    assert len(result["meterai_list"]) == 2
    mock_coretax_service.purchase_e_meterai.assert_called_once_with(
        legal_entity_id=mock_legal_entity_id,
        quantity=10,
        npwp="123456789012345",
        purpose="Faktur",
        purchased_by=mock_token_payload.user_id,
    )


# ============================================================================
# BULK SUBMISSION TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_bulk_submit_faktur_success(mock_bulk_use_case, mock_token_payload, mock_legal_entity_id):
    faktur_ids = [uuid4(), uuid4()]
    result = await bulk_submit_faktur(
        faktur_ids=faktur_ids,
        idempotency_key=None,
        _permission=None,
        current_user=mock_token_payload,
        legal_entity_id=mock_legal_entity_id,
        bulk_use_case=mock_bulk_use_case,
    )
    assert result["total_submitted"] == 2
    assert result["success_count"] == 2
    assert result["failed_count"] == 0
    mock_bulk_use_case.submit_faktur_batch.assert_called_once_with(
        faktur_ids=faktur_ids,
        legal_entity_id=mock_legal_entity_id,
        submitted_by=mock_token_payload.user_id,
    )


# ============================================================================
# CORETAX DASHBOARD TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_get_coretax_dashboard_success(mock_coretax_service, mock_legal_entity_id):
    result = await get_coretax_dashboard(
        _permission=None,
        legal_entity_id=mock_legal_entity_id,
        coretax_service=mock_coretax_service,
    )
    assert isinstance(result, CoretaxDashboardResponseSchema)
    assert result.nsfp_quota_remaining == 100
    assert result.api_health == "healthy"
    mock_coretax_service.get_dashboard.assert_called_once_with(mock_legal_entity_id)


# ============================================================================
# TAX FILING STATUS TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_get_tax_filing_status_success(mock_tax_service, mock_legal_entity_id):
    result = await get_tax_filing_status(
        year=2026,
        tax_type=TaxType.PPN,
        _permission=None,
        legal_entity_id=mock_legal_entity_id,
        tax_service=mock_tax_service,
    )
    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], TaxFilingStatusSchema)
    assert result[0].tax_type == TaxType.PPN
    assert result[0].status == "submitted"
    mock_tax_service.get_filing_status.assert_called_once_with(
        legal_entity_id=mock_legal_entity_id,
        year=2026,
        tax_type="ppn",
    )


# ============================================================================
# TAX DUE DATES TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_get_tax_due_dates_success(mock_tax_service, mock_legal_entity_id):
    result = await get_tax_due_dates(
        days_ahead=30,
        _permission=None,
        legal_entity_id=mock_legal_entity_id,
        tax_service=mock_tax_service,
    )
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["tax_type"] == "ppn"
    assert result[0]["days_remaining"] == 30
    mock_tax_service.get_upcoming_due_dates.assert_called_once_with(
        legal_entity_id=mock_legal_entity_id,
        days_ahead=30,
    )


# ============================================================================
# TAX SUMMARY TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_get_tax_summary_success(mock_tax_service, mock_legal_entity_id):
    result = await get_tax_summary(
        start_date=FIXED_DATE,
        end_date=FIXED_DATE,
        _permission=None,
        legal_entity_id=mock_legal_entity_id,
        tax_service=mock_tax_service,
    )
    assert result["period_start"] == FIXED_DATE.isoformat()
    assert result["total_tax"] == "80000"
    assert result["outstanding"] == "50000"
    mock_tax_service.get_tax_summary.assert_called_once_with(
        legal_entity_id=mock_legal_entity_id,
        start_date=FIXED_DATE,
        end_date=FIXED_DATE,
    )


# ============================================================================
# EXPORT TAX DATA TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_export_tax_data_success(mock_tax_service, mock_legal_entity_id):
    result = await export_tax_data(
        start_date=FIXED_DATE,
        end_date=FIXED_DATE,
        format="csv",
        tax_type=TaxType.PPN,
        _permission=None,
        legal_entity_id=mock_legal_entity_id,
        tax_service=mock_tax_service,
    )
    assert isinstance(result, Response)
    assert result.body == b"csv data"
    assert result.media_type == "text/csv"
    mock_tax_service.export_tax_data.assert_called_once_with(
        legal_entity_id=mock_legal_entity_id,
        start_date=FIXED_DATE,
        end_date=FIXED_DATE,
        format="csv",
        tax_type="ppn",
    )


@pytest.mark.asyncio
async def test_export_tax_data_excel(mock_tax_service, mock_legal_entity_id):
    mock_tax_service.export_tax_data.return_value = b"excel data"
    result = await export_tax_data(
        start_date=FIXED_DATE,
        end_date=FIXED_DATE,
        format="excel",
        tax_type=None,
        _permission=None,
        legal_entity_id=mock_legal_entity_id,
        tax_service=mock_tax_service,
    )
    assert isinstance(result, Response)
    assert result.media_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    mock_tax_service.export_tax_data.assert_called_once_with(
        legal_entity_id=mock_legal_entity_id,
        start_date=FIXED_DATE,
        end_date=FIXED_DATE,
        format="excel",
        tax_type=None,
    )


@pytest.mark.asyncio
async def test_export_tax_data_error(mock_tax_service, mock_legal_entity_id):
    mock_tax_service.export_tax_data.side_effect = Exception("Export error")
    with pytest.raises(HTTPException) as exc:
        await export_tax_data(
            start_date=FIXED_DATE,
            end_date=FIXED_DATE,
            format="csv",
            tax_type=None,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            tax_service=mock_tax_service,
        )
    assert exc.value.status_code == 500