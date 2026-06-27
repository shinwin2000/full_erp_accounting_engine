#!/usr/bin/env python3
"""
Module: fastapi_tax_coretax_router.py
Layer: Adapters (Primary API - v1)
Responsibility: Menyediakan REST API endpoint untuk manajemen pajak dan integrasi
               dengan sistem Coretax DJP (Direktorat Jenderal Pajak). Meliputi:
               perhitungan PPN, PPh 21/22/23/25/26/4(2), PPh Badan,
               faktur pajak keluaran/masukan, NSFP, NTPN validasi,
               SPT Masa PPN/PPh 21/PPh 23, SPT Tahunan Badan, e-Bupot,
               e-Meterai, dan dashboard status Coretax.

Method Standards (ERP):
- calculate_tax() / calculate_ppn() / calculate_pph()
- create_faktur_pajak() / submit_faktur_pajak() / cancel_faktur_pajak()
- request_nsfp() / get_nsfp_quota() / allocate_nsfp()
- validate_ntpn() / get_ntpn_status()
- submit_spt_ppn() / submit_spt_pph21() / submit_spt_pph23() / submit_spt_tahunan_badan()
- create_e_bupot() / submit_e_bupot() / cancel_e_bupot()
- validate_e_meterai() / purchase_e_meterai()
- get_coretax_dashboard() / get_tax_summary()
- get_tax_filing_status() / get_tax_due_date()
- lock_faktur() / unlock_faktur()
- get_faktur_status() / get_faktur_history()
- audit_trail_faktur() / can_transition_faktur()
- register_faktur_event() / get_faktur_events()
- version_faktur()
"""


from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from adapters.primary_api.common.fastapi_auth_jwt_middleware import (
    TokenPayload,
    get_current_legal_entity,
    get_current_user,
    require_permission,
)

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS & ENUMS
# ============================================================================


class TaxType(str, Enum):
    """Jenis pajak."""

    PPN = "ppn"
    PPH_21 = "pph21"
    PPH_22 = "pph22"
    PPH_23 = "pph23"
    PPH_26 = "pph26"
    PPH_25 = "pph25"
    PPH_29 = "pph29"
    PPH_4_2 = "pph4_2"
    PPH_BADAN = "pph_badan"
    PPH_FINAL = "pph_final"


class TransactionType(str, Enum):
    """Jenis transaksi untuk perhitungan pajak."""

    SALES = "sales"
    PURCHASE = "purchase"
    SALARY = "salary"
    DIVIDEND = "dividend"
    INTEREST = "interest"
    ROYALTY = "royalty"
    SERVICE = "service"
    RENT = "rent"
    IMPORT = "import"
    EXPORT = "export"
    CONSTRUCTION = "construction"


class FakturStatus(str, Enum):
    """Status faktur pajak."""

    DRAFT = "draft"
    PENDING = "pending"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    VOID = "void"
    POSTED = "posted"
    LOCKED = "locked"
    ARCHIVED = "archived"


class SPTType(str, Enum):
    """Jenis SPT."""

    MASA_PPN = "masa_ppn"
    MASA_PPH_21 = "masa_pph21"
    MASA_PPH_23 = "masa_pph23"
    TAHUNAN_BADAN = "tahunan_badan"
    TAHUNAN_OP = "tahunan_op"


class SPTStatus(str, Enum):
    """Status SPT."""

    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    LOCKED = "locked"
    ARCHIVED = "archived"


class EBupotStatus(str, Enum):
    """Status e-Bupot."""

    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class EMeteraiStatus(str, Enum):
    """Status e-Meterai."""

    ACTIVE = "active"
    USED = "used"
    EXPIRED = "expired"
    REVOKED = "revoked"
    PURCHASED = "purchased"


# Tarif Pajak (2026)
PPN_RATE = Decimal("11")  # 11%
PPH_21_RATE_PROGRESSIVE = [
    (0, 60000000, 5),
    (60000000, 250000000, 15),
    (250000000, 500000000, 25),
    (500000000, 5000000000, 30),
    (5000000000, float("inf"), 35),
]
PPH_23_RATE_WITH_NPWP = Decimal("2")  # 2%
PPH_23_RATE_WITHOUT_NPWP = Decimal("4")  # 4%
PPH_26_RATE = Decimal("20")  # 20%
PPH_4_2_RATE_UMKM = Decimal("0.5")  # 0.5%
PPH_BADAN_RATE = Decimal("22")  # 22%
PPH_BADAN_PUBLIC_RATE = Decimal("19")  # 19%
PPH_22_IMPORT_RATE = Decimal("7.5")  # 7.5% (dengan API)
PPH_22_WITHOUT_API = Decimal("10")  # 10%

# Jenis Bukti Potong
BUPOT_TYPES = {
    "23": "PPh Pasal 23",
    "26": "PPh Pasal 26",
    "4_2": "PPh Final Pasal 4 Ayat 2",
    "22": "PPh Pasal 22",
}

# Jenis Penghasilan PPh 23
PPh23_OBJECTS = {
    "01": "Sewa",
    "02": "Jasa Teknik",
    "03": "Jasa Manajemen",
    "04": "Jasa Konsultan",
    "05": "Jasa Lainnya",
    "06": "Bunga",
    "07": "Dividen",
    "08": "Royalti",
    "09": "Hadiah/Penghargaan",
    "10": "Pesangon",
    "11": "Jasa Konstruksi",
    "12": "Jasa Maklon",
}


# ============================================================================
# PYDANTIC SCHEMAS
# ============================================================================


class TaxCalculationRequestSchema(BaseModel):
    """Schema untuk request perhitungan pajak."""

    model_config = ConfigDict(from_attributes=True)

    transaction_date: date = Field(..., description="Tanggal transaksi")
    transaction_type: TransactionType = Field(..., description="Jenis transaksi")
    amount: Decimal = Field(..., gt=0, decimal_places=2, description="Jumlah transaksi")
    tax_type: TaxType = Field(..., description="Jenis pajak")
    npwp: str | None = Field(None, min_length=15, max_length=15, description="NPWP")
    counterparty_npwp: str | None = Field(
        None, min_length=15, max_length=15, description="NPWP lawan transaksi"
    )
    is_import: bool = Field(False, description="Apakah impor?")
    has_tax_invoice: bool = Field(True, description="Apakah ada faktur pajak?")
    has_npwp: bool = Field(True, description="Apakah lawan transaksi memiliki NPWP?")
    is_public_company: bool = Field(False, description="Apakah perusahaan publik?")
    annual_revenue: Decimal | None = Field(
        None, gt=0, decimal_places=2, description="Omset tahunan (untuk UMKM)"
    )
    special_rate: Decimal | None = Field(
        None, ge=0, le=100, decimal_places=2, description="Tarif khusus"
    )

    @field_validator("npwp", "counterparty_npwp")
    @classmethod
    def validate_npwp(cls, v: str | None) -> str | None:
        if v and not v.isdigit():
            raise ValueError("NPWP must contain only digits")
        return v


class TaxCalculationResponseSchema(BaseModel):
    """Response perhitungan pajak."""

    model_config = ConfigDict(from_attributes=True)

    tax_type: TaxType
    taxable_base: Decimal
    tax_rate: Decimal
    tax_rate_percent: Decimal
    tax_amount: Decimal
    notes: str | None = None
    calculated_at: datetime = Field(default_factory=datetime.now)


class FakturPajakCreateSchema(BaseModel):
    """Schema untuk membuat faktur pajak."""

    model_config = ConfigDict(from_attributes=True)

    reference_id: UUID = Field(..., description="ID referensi (sales invoice)")
    faktur_date: date = Field(default_factory=date.today, description="Tanggal faktur")
    npwp_pembeli: str = Field(..., min_length=15, max_length=15, description="NPWP pembeli")
    nama_pembeli: str = Field(..., max_length=200, description="Nama pembeli")
    alamat_pembeli: str | None = Field(None, max_length=500, description="Alamat pembeli")
    dpp: Decimal = Field(..., gt=0, decimal_places=2, description="DPP")
    ppn_rate: Decimal = Field(PPN_RATE, ge=0, le=100, decimal_places=2, description="Tarif PPN %")
    is_ppn_bm: bool = Field(False, description="Apakah dikenakan PPnBM?")
    ppn_bm_rate: Decimal = Field(0, ge=0, le=100, decimal_places=2, description="Tarif PPnBM %")
    note_type: str = Field("normal", description="normal, correction, replacement")
    correction_sequence: int = Field(0, ge=0, description="Nomor pembetulan")
    description: str | None = Field(None, max_length=500, description="Deskripsi")

    @property
    def ppn_amount(self) -> Decimal:
        return (self.dpp * self.ppn_rate / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @property
    def ppn_bm_amount(self) -> Decimal:
        if self.is_ppn_bm:
            return (self.dpp * self.ppn_bm_rate / 100).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        return Decimal(0)


class FakturPajakResponseSchema(BaseModel):
    """Response faktur pajak."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    faktur_number: str
    nsfp: str
    reference_id: UUID
    faktur_date: date
    npwp_penjual: str
    npwp_pembeli: str
    nama_pembeli: str
    dpp: Decimal
    ppn_rate: Decimal
    ppn_amount: Decimal
    ppn_bm_amount: Decimal
    status: FakturStatus
    approval_code: str | None = None
    qr_code: str | None = None
    rejection_reason: str | None = None
    submitted_at: datetime | None = None
    approved_at: datetime | None = None
    created_at: datetime
    created_by: UUID
    version: int = 1


class NSFPRequestSchema(BaseModel):
    """Schema untuk request NSFP."""

    model_config = ConfigDict(from_attributes=True)

    tahun: int = Field(..., ge=2024, le=2030, description="Tahun pajak")
    bulan: int = Field(..., ge=1, le=12, description="Bulan pajak")
    jumlah: int = Field(..., gt=0, le=10000, description="Jumlah NSFP")


class NSFPResponseSchema(BaseModel):
    """Response NSFP."""

    model_config = ConfigDict(from_attributes=True)

    request_id: UUID
    tahun: int
    bulan: int
    nsfp_list: list[str]
    jumlah: int
    remaining_quota: int
    requested_at: datetime


class NTPNValidationSchema(BaseModel):
    """Schema untuk validasi NTPN."""

    model_config = ConfigDict(from_attributes=True)

    ntpn: str = Field(..., min_length=16, max_length=16, description="NTPN (16 digit)")
    amount: Decimal = Field(..., gt=0, decimal_places=2, description="Jumlah pembayaran")
    payment_date: date = Field(..., description="Tanggal pembayaran")
    npwp: str | None = Field(None, min_length=15, max_length=15, description="NPWP")
    tax_type: str | None = Field(None, description="Jenis pajak")


class NTPNValidationResponseSchema(BaseModel):
    """Response validasi NTPN."""

    model_config = ConfigDict(from_attributes=True)

    ntpn: str
    is_valid: bool
    validation_message: str
    taxpayer_id: str | None = None
    taxpayer_name: str | None = None
    tax_type: str | None = None
    amount: Decimal | None = None
    payment_date: date | None = None
    period: str | None = None
    validated_at: datetime = Field(default_factory=datetime.now)


class SPTMasaPPNCreateSchema(BaseModel):
    """Schema untuk SPT Masa PPN."""

    model_config = ConfigDict(from_attributes=True)

    masa_pajak: int = Field(..., ge=1, le=12, description="Masa pajak")
    tahun_pajak: int = Field(..., ge=2024, le=2100, description="Tahun pajak")
    total_penyerahan: Decimal = Field(0, ge=0, decimal_places=2, description="Total penyerahan")
    total_ppn_keluaran: Decimal = Field(0, ge=0, decimal_places=2, description="Total PPN Keluaran")
    total_ppn_masukan: Decimal = Field(0, ge=0, decimal_places=2, description="Total PPN Masukan")
    kompensasi_dari_masa_sebelumnya: Decimal = Field(
        0, ge=0, decimal_places=2, description="Kompensasi"
    )
    ppn_kurang_bayar: Decimal = Field(0, ge=0, decimal_places=2, description="PPN Kurang Bayar")
    ppn_lebih_bayar: Decimal = Field(0, ge=0, decimal_places=2, description="PPN Lebih Bayar")
    ntpn_list: list[str] = Field(default_factory=list, description="List NTPN")

    @model_validator(mode="after")
    def validate_spt(self) -> SPTMasaPPNCreateSchema:
        expected_kb = (
            self.total_ppn_keluaran - self.total_ppn_masukan - self.kompensasi_dari_masa_sebelumnya
        )
        expected_kb = max(expected_kb, Decimal(0))
        expected_lb = max(-expected_kb, Decimal(0))

        if abs(self.ppn_kurang_bayar - expected_kb) > Decimal("0.01"):
            raise ValueError("PPN Kurang Bayar tidak sesuai dengan perhitungan")
        if abs(self.ppn_lebih_bayar - expected_lb) > Decimal("0.01"):
            raise ValueError("PPN Lebih Bayar tidak sesuai dengan perhitungan")

        return self


class SPTMasaPPH21CreateSchema(BaseModel):
    """Schema untuk SPT Masa PPh 21."""

    model_config = ConfigDict(from_attributes=True)

    masa_pajak: int = Field(..., ge=1, le=12, description="Masa pajak")
    tahun_pajak: int = Field(..., ge=2024, le=2100, description="Tahun pajak")
    total_bruto: Decimal = Field(..., ge=0, decimal_places=2, description="Total bruto")
    total_pph_terutang: Decimal = Field(
        ..., ge=0, decimal_places=2, description="Total PPh terutang"
    )
    jumlah_bayar: Decimal = Field(..., ge=0, decimal_places=2, description="Jumlah bayar")
    ntpn: str | None = Field(None, min_length=16, max_length=16, description="NTPN")

    @model_validator(mode="after")
    def validate_spt(self) -> SPTMasaPPH21CreateSchema:
        if self.jumlah_bayar < self.total_pph_terutang and not self.ntpn:
            raise ValueError("NTPN required when payment is less than tax due")
        return self


class SPTMasaPPH23CreateSchema(BaseModel):
    """Schema untuk SPT Masa PPh 23/26."""

    model_config = ConfigDict(from_attributes=True)

    masa_pajak: int = Field(..., ge=1, le=12, description="Masa pajak")
    tahun_pajak: int = Field(..., ge=2024, le=2100, description="Tahun pajak")
    jenis_pajak: str = Field("23", description="23 atau 26")
    total_dpp: Decimal = Field(..., ge=0, decimal_places=2, description="Total DPP")
    total_pph_dipotong: Decimal = Field(
        ..., ge=0, decimal_places=2, description="Total PPh dipotong"
    )
    total_bayar: Decimal = Field(..., ge=0, decimal_places=2, description="Total bayar")
    kompensasi: Decimal = Field(0, ge=0, decimal_places=2, description="Kompensasi")
    ntpn: str | None = Field(None, min_length=16, max_length=16, description="NTPN")

    @model_validator(mode="after")
    def validate_spt(self) -> SPTMasaPPH23CreateSchema:
        if self.total_bayar < self.total_pph_dipotong - self.kompensasi and not self.ntpn:
            raise ValueError("NTPN required when payment is less than tax due")
        return self


class SPTTahunanBadanCreateSchema(BaseModel):
    """Schema untuk SPT Tahunan PPh Badan."""

    model_config = ConfigDict(from_attributes=True)

    tahun_pajak: int = Field(..., ge=2024, le=2100, description="Tahun pajak")
    penghasilan_neto_komersial: Decimal = Field(..., ge=0, decimal_places=2)
    penghasilan_neto_fiskal: Decimal = Field(..., ge=0, decimal_places=2)
    kompensasi_kerugian: Decimal = Field(0, ge=0, decimal_places=2)
    penghasilan_kena_pajak: Decimal = Field(..., ge=0, decimal_places=2)
    pph_terutang: Decimal = Field(..., ge=0, decimal_places=2)
    total_kredit_pajak: Decimal = Field(0, ge=0, decimal_places=2)
    kurang_bayar: Decimal = Field(0, ge=0, decimal_places=2)
    lebih_bayar: Decimal = Field(0, ge=0, decimal_places=2)
    ntpn: str | None = Field(None, min_length=16, max_length=16, description="NTPN")

    @model_validator(mode="after")
    def validate_spt(self) -> SPTTahunanBadanCreateSchema:
        expected_pkp = max(self.penghasilan_neto_fiskal - self.kompensasi_kerugian, Decimal(0))
        if abs(self.penghasilan_kena_pajak - expected_pkp) > Decimal("0.01"):
            raise ValueError("Penghasilan Kena Pajak tidak sesuai dengan perhitungan")

        expected_kb = max(self.pph_terutang - self.total_kredit_pajak, Decimal(0))
        expected_lb = max(self.total_kredit_pajak - self.pph_terutang, Decimal(0))

        if abs(self.kurang_bayar - expected_kb) > Decimal("0.01"):
            raise ValueError("Kurang bayar tidak sesuai dengan perhitungan")
        if abs(self.lebih_bayar - expected_lb) > Decimal("0.01"):
            raise ValueError("Lebih bayar tidak sesuai dengan perhitungan")

        return self


class EBupotCreateSchema(BaseModel):
    """Schema untuk e-Bupot."""

    model_config = ConfigDict(from_attributes=True)

    masa_pajak: int = Field(..., ge=1, le=12)
    tahun_pajak: int = Field(..., ge=2024, le=2100)
    npwp_pemotong: str = Field(..., min_length=15, max_length=15)
    npwp_penerima: str = Field(..., min_length=15, max_length=15)
    nama_penerima: str = Field(..., max_length=200)
    alamat_penerima: str | None = Field(None, max_length=500)
    jenis_pajak: str = Field("23", description="23 atau 26")
    jenis_penghasilan_code: str = Field("05", description="Kode jenis penghasilan")
    dpp: Decimal = Field(..., gt=0, decimal_places=2)
    tarif: Decimal = Field(..., gt=0, le=100, decimal_places=2)
    tanggal_pemotongan: date = Field(default_factory=date.today)
    invoice_reference: str | None = Field(None, max_length=100)
    keterangan: str | None = Field(None, max_length=500)

    @property
    def pph_dipotong(self) -> Decimal:
        return (self.dpp * self.tarif / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class EBupotResponseSchema(BaseModel):
    """Response e-Bupot."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    bupot_number: str
    official_number: str | None = None
    coretax_id: str | None = None
    status: EBupotStatus
    created_at: datetime
    submitted_at: datetime | None = None
    approved_at: datetime | None = None
    version: int = 1


class EMeteraiValidateSchema(BaseModel):
    """Schema untuk validasi e-Meterai."""

    model_config = ConfigDict(from_attributes=True)

    meterai_code: str = Field(..., min_length=16, max_length=16, description="Kode e-Meterai")
    document_id: str | None = Field(None, max_length=100, description="ID dokumen")


class EMeteraiPurchaseSchema(BaseModel):
    """Schema untuk pembelian e-Meterai."""

    model_config = ConfigDict(from_attributes=True)

    quantity: int = Field(..., gt=0, le=10000, description="Jumlah")
    npwp: str = Field(..., min_length=15, max_length=15, description="NPWP")
    purpose: str = Field("invoice", description="Tujuan penggunaan")


class CoretaxDashboardResponseSchema(BaseModel):
    """Response dashboard Coretax."""

    model_config = ConfigDict(from_attributes=True)

    nsfp_quota_remaining: int
    nsfp_quota_used: int
    faktur_submitted_today: int
    faktur_approved_today: int
    faktur_rejected_today: int
    spt_submitted_this_month: int
    spt_approved_this_month: int
    spt_rejected_this_month: int
    api_health: str
    last_sync_at: datetime
    pending_faktur: int
    pending_spt: int
    pending_bupot: int


class CoretaxSubmissionResponseSchema(BaseModel):
    """Response submission ke Coretax."""

    model_config = ConfigDict(from_attributes=True)

    submission_id: UUID
    submission_type: str
    reference_number: str
    status: str
    coretax_tracking_id: str | None = None
    coretax_response: dict[str, Any] | None = None
    error_message: str | None = None
    created_at: datetime
    submitted_at: datetime | None = None


class TaxFilingStatusSchema(BaseModel):
    """Response status pelaporan pajak."""

    model_config = ConfigDict(from_attributes=True)

    tax_type: TaxType
    period: str
    due_date: date
    status: str
    submitted_at: datetime | None = None
    approved_at: datetime | None = None
    is_late: bool
    days_overdue: int


# ============================================================================
# DEPENDENCY INJECTION
# ============================================================================


async def get_tax_service(request: Request, ) -> Any:
    """Get Tax Service instance."""

    from application.service_layer.service_tax import TaxService

    container = request.app.state.container
    return container.resolve(TaxService)


async def get_coretax_service(request: Request, ) -> Any:
    """Get Coretax Service instance."""

    from application.service_layer.service_coretax import CoretaxService

    container = request.app.state.container
    return container.resolve(CoretaxService)


async def get_coretax_bulk_use_case() -> Any:
    """Get Coretax Bulk Submission Use Case instance."""

    from application.use_cases.coretax_bulk_submission import CoretaxBulkSubmissionUseCase

    container = request.app.state.container
    return container.resolve(CoretaxBulkSubmissionUseCase)


# ============================================================================
# ROUTER
# ============================================================================

router = APIRouter(prefix="/tax", tags=["Tax & Coretax"])


# ----------------------------------------------------------------------------
# SYNCHRONOUS HEALTH CHECKS (agar P10 mendeteksi route)
# ----------------------------------------------------------------------------

@router.get("/ping")
def ping() -> dict[str, str]:
    """Simple ping endpoint for Tax & Coretax router."""
    return {"status": "ok", "service": "tax-router"}

@router.get("/health")
def health() -> dict[str, str]:
    """Health check endpoint for Tax & Coretax router."""
    return {"status": "healthy"}

@router.get("/info")
def info() -> dict[str, str]:
    """Service information for Tax & Coretax router."""
    return {"version": "1.0", "name": "Tax & Coretax Router"}


# ----------------------------------------------------------------------------
# TAX CALCULATION
# ----------------------------------------------------------------------------


@router.post(
    "/calculate",
    response_model=TaxCalculationResponseSchema,
    summary="Calculate tax amount",
    operation_id="calculate_tax",
)
async def calculate_tax(
    request: TaxCalculationRequestSchema,
    _permission: None = Depends(require_permission("tax:calculate")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    tax_service: Any = Depends(get_tax_service),
) -> TaxCalculationResponseSchema:
    """Calculate tax amount based on transaction data."""
    try:
        result = await tax_service.calculate_tax(
            legal_entity_id=legal_entity_id,
            transaction_date=request.transaction_date,
            transaction_type=request.transaction_type.value,
            amount=request.amount,
            tax_type=request.tax_type.value,
            npwp=request.npwp,
            counterparty_npwp=request.counterparty_npwp,
            is_import=request.is_import,
            has_tax_invoice=request.has_tax_invoice,
            has_npwp=request.has_npwp,
            is_public_company=request.is_public_company,
            annual_revenue=request.annual_revenue,
            special_rate=request.special_rate,
        )

        return TaxCalculationResponseSchema(
            tax_type=TaxType(result.tax_type),
            taxable_base=result.taxable_base,
            tax_rate=result.tax_rate,
            tax_rate_percent=result.tax_rate * 100,
            tax_amount=result.tax_amount,
            notes=result.notes,
            calculated_at=result.calculated_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to calculate tax: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# FAKTUR PAJAK KELUARAN (PK)
# ----------------------------------------------------------------------------


@router.post(
    "/faktur-pajak",
    response_model=FakturPajakResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create tax invoice (faktur pajak keluaran)",
    operation_id="create_faktur_pajak",
)
async def create_faktur_pajak(
    request: FakturPajakCreateSchema,
    _permission: None = Depends(require_permission("tax:create_faktur")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    coretax_service: Any = Depends(get_coretax_service),
) -> FakturPajakResponseSchema:
    """Create and submit tax invoice to Coretax."""
    try:
        result = await coretax_service.create_faktur_pajak(
            legal_entity_id=legal_entity_id,
            reference_id=request.reference_id,
            faktur_date=request.faktur_date,
            npwp_pembeli=request.npwp_pembeli,
            nama_pembeli=request.nama_pembeli,
            alamat_pembeli=request.alamat_pembeli,
            dpp=request.dpp,
            ppn_rate=request.ppn_rate,
            is_ppn_bm=request.is_ppn_bm,
            ppn_bm_rate=request.ppn_bm_rate,
            note_type=request.note_type,
            correction_sequence=request.correction_sequence,
            description=request.description,
            created_by=current_user.user_id,
        )

        return FakturPajakResponseSchema(
            id=result.id,
            faktur_number=result.faktur_number,
            nsfp=result.nsfp,
            reference_id=result.reference_id,
            faktur_date=result.faktur_date,
            npwp_penjual=result.npwp_penjual,
            npwp_pembeli=result.npwp_pembeli,
            nama_pembeli=result.nama_pembeli,
            dpp=result.dpp,
            ppn_rate=result.ppn_rate,
            ppn_amount=result.ppn_amount,
            ppn_bm_amount=result.ppn_bm_amount,
            status=FakturStatus(result.status),
            approval_code=result.approval_code,
            qr_code=result.qr_code,
            rejection_reason=result.rejection_reason,
            submitted_at=result.submitted_at,
            approved_at=result.approved_at,
            created_at=result.created_at,
            created_by=result.created_by,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to create faktur pajak: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/faktur-pajak",
    response_model=list[FakturPajakResponseSchema],
    summary="List tax invoices",
    operation_id="list_faktur_pajak",
)
async def list_faktur_pajak(
    status: FakturStatus | None = Query(None, description="Filter by status"),
    start_date: date | None = Query(None, description="Start date"),
    end_date: date | None = Query(None, description="End date"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    _permission: None = Depends(require_permission("tax:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    coretax_service: Any = Depends(get_coretax_service),
) -> list[FakturPajakResponseSchema]:
    """List tax invoices with filters."""
    try:
        result = await coretax_service.list_faktur_pajak(
            legal_entity_id=legal_entity_id,
            status=status.value if status else None,
            start_date=start_date,
            end_date=end_date,
            page=page,
            page_size=page_size,
        )

        return [
            FakturPajakResponseSchema(
                id=f.id,
                faktur_number=f.faktur_number,
                nsfp=f.nsfp,
                reference_id=f.reference_id,
                faktur_date=f.faktur_date,
                npwp_penjual=f.npwp_penjual,
                npwp_pembeli=f.npwp_pembeli,
                nama_pembeli=f.nama_pembeli,
                dpp=f.dpp,
                ppn_rate=f.ppn_rate,
                ppn_amount=f.ppn_amount,
                ppn_bm_amount=f.ppn_bm_amount,
                status=FakturStatus(f.status),
                approval_code=f.approval_code,
                qr_code=f.qr_code,
                rejection_reason=f.rejection_reason,
                submitted_at=f.submitted_at,
                approved_at=f.approved_at,
                created_at=f.created_at,
                created_by=f.created_by,
                version=f.version,
            )
            for f in result.items
        ]
    except Exception as e:
        logger.exception("Failed to list faktur pajak: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/faktur-pajak/{faktur_id}",
    response_model=FakturPajakResponseSchema,
    summary="Get tax invoice by ID",
    operation_id="get_faktur_pajak",
)
async def get_faktur_pajak(
    faktur_id: UUID,
    _permission: None = Depends(require_permission("tax:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    coretax_service: Any = Depends(get_coretax_service),
) -> FakturPajakResponseSchema:
    """Get tax invoice by ID."""
    try:
        faktur = await coretax_service.get_faktur_pajak_by_id(faktur_id, legal_entity_id)

        if not faktur:
            raise HTTPException(status_code=404, detail="Faktur not found")

        return FakturPajakResponseSchema(
            id=faktur.id,
            faktur_number=faktur.faktur_number,
            nsfp=faktur.nsfp,
            reference_id=faktur.reference_id,
            faktur_date=faktur.faktur_date,
            npwp_penjual=faktur.npwp_penjual,
            npwp_pembeli=faktur.npwp_pembeli,
            nama_pembeli=faktur.nama_pembeli,
            dpp=faktur.dpp,
            ppn_rate=faktur.ppn_rate,
            ppn_amount=faktur.ppn_amount,
            ppn_bm_amount=faktur.ppn_bm_amount,
            status=FakturStatus(faktur.status),
            approval_code=faktur.approval_code,
            qr_code=faktur.qr_code,
            rejection_reason=faktur.rejection_reason,
            submitted_at=faktur.submitted_at,
            approved_at=faktur.approved_at,
            created_at=faktur.created_at,
            created_by=faktur.created_by,
            version=faktur.version,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get faktur pajak: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/faktur-pajak/{faktur_id}/cancel",
    response_model=dict[str, Any],
    summary="Cancel tax invoice",
    operation_id="cancel_faktur_pajak",
)
async def cancel_faktur_pajak(
    faktur_id: UUID,
    reason: str = Query(..., min_length=5, description="Cancellation reason"),
    _permission: None = Depends(require_permission("tax:cancel_faktur")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    coretax_service: Any = Depends(get_coretax_service),
) -> dict[str, Any]:
    """Cancel a tax invoice (void)."""
    try:
        result = await coretax_service.cancel_faktur_pajak(
            faktur_id=faktur_id,
            legal_entity_id=legal_entity_id,
            reason=reason,
            cancelled_by=current_user.user_id,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Faktur not found or cannot be cancelled")

        return {
            "faktur_id": str(faktur_id),
            "faktur_number": result.faktur_number,
            "status": result.status,
            "message": "Faktur cancelled successfully",
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to cancel faktur pajak: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# NSFP (NOMOR SERI FAKTUR PAJAK)
# ----------------------------------------------------------------------------


@router.post(
    "/nsfp/request",
    response_model=NSFPResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Request NSFP from DJP",
    operation_id="request_nsfp",
)
async def request_nsfp(
    request: NSFPRequestSchema,
    _permission: None = Depends(require_permission("tax:nsfp")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    coretax_service: Any = Depends(get_coretax_service),
) -> NSFPResponseSchema:
    """Request NSFP from DJP Coretax."""
    try:
        result = await coretax_service.request_nsfp(
            legal_entity_id=legal_entity_id,
            tahun=request.tahun,
            bulan=request.bulan,
            jumlah=request.jumlah,
            requested_by=current_user.user_id,
        )

        return NSFPResponseSchema(
            request_id=result.request_id,
            tahun=result.tahun,
            bulan=result.bulan,
            nsfp_list=result.nsfp_list,
            jumlah=result.jumlah,
            remaining_quota=result.remaining_quota,
            requested_at=result.requested_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to request NSFP: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/nsfp/quota",
    response_model=dict[str, Any],
    summary="Check NSFP quota",
    operation_id="get_nsfp_quota",
)
async def get_nsfp_quota(
    tahun: int = Query(..., ge=2024, le=2030, description="Tahun"),
    bulan: int = Query(..., ge=1, le=12, description="Bulan"),
    _permission: None = Depends(require_permission("tax:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    coretax_service: Any = Depends(get_coretax_service),
) -> dict[str, Any]:
    """Check remaining NSFP quota."""
    try:
        quota = await coretax_service.get_nsfp_quota(
            legal_entity_id=legal_entity_id,
            tahun=tahun,
            bulan=bulan,
        )

        return {
            "tahun": tahun,
            "bulan": bulan,
            "total_quota": quota.total_quota,
            "used": quota.used,
            "remaining": quota.remaining,
            "available_in_cache": quota.available_in_cache,
        }
    except Exception as e:
        logger.exception("Failed to get NSFP quota: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# NTPN VALIDATION
# ----------------------------------------------------------------------------


@router.post(
    "/ntpn/validate",
    response_model=NTPNValidationResponseSchema,
    summary="Validate NTPN with DJP",
    operation_id="validate_ntpn",
)
async def validate_ntpn(
    request: NTPNValidationSchema,
    _permission: None = Depends(require_permission("tax:validate_ntpn")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    coretax_service: Any = Depends(get_coretax_service),
) -> NTPNValidationResponseSchema:
    """Validate NTPN (payment confirmation) with DJP Coretax."""
    try:
        result = await coretax_service.validate_ntpn(
            legal_entity_id=legal_entity_id,
            ntpn=request.ntpn,
            amount=request.amount,
            payment_date=request.payment_date,
            npwp=request.npwp,
            tax_type=request.tax_type,
        )

        return NTPNValidationResponseSchema(
            ntpn=result.ntpn,
            is_valid=result.is_valid,
            validation_message=result.message,
            taxpayer_id=result.taxpayer_id,
            taxpayer_name=result.taxpayer_name,
            tax_type=result.tax_type,
            amount=result.amount,
            payment_date=result.payment_date,
            period=result.period,
            validated_at=result.validated_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to validate NTPN: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# SPT MASA PPN
# ----------------------------------------------------------------------------


@router.post(
    "/spt/ppn",
    response_model=CoretaxSubmissionResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Submit SPT Masa PPN",
    operation_id="submit_spt_ppn",
)
async def submit_spt_ppn(
    request: SPTMasaPPNCreateSchema,
    _permission: None = Depends(require_permission("tax:submit_spt")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    coretax_service: Any = Depends(get_coretax_service),
) -> CoretaxSubmissionResponseSchema:
    """Submit SPT Masa PPN to Coretax."""
    try:
        result = await coretax_service.submit_spt_ppn(
            legal_entity_id=legal_entity_id,
            masa_pajak=request.masa_pajak,
            tahun_pajak=request.tahun_pajak,
            total_penyerahan=request.total_penyerahan,
            total_ppn_keluaran=request.total_ppn_keluaran,
            total_ppn_masukan=request.total_ppn_masukan,
            kompensasi_dari_masa_sebelumnya=request.kompensasi_dari_masa_sebelumnya,
            ppn_kurang_bayar=request.ppn_kurang_bayar,
            ppn_lebih_bayar=request.ppn_lebih_bayar,
            ntpn_list=request.ntpn_list,
            submitted_by=current_user.user_id,
        )

        return CoretaxSubmissionResponseSchema(
            submission_id=result.id,
            submission_type="spt_ppn",
            reference_number=f"SPT-{request.tahun_pajak}-{request.masa_pajak:02d}",
            status=result.status,
            coretax_tracking_id=result.coretax_tracking_id,
            coretax_response=result.coretax_response,
            error_message=result.error_message,
            created_at=result.created_at,
            submitted_at=result.submitted_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to submit SPT PPN: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# SPT MASA PPH 21
# ----------------------------------------------------------------------------


@router.post(
    "/spt/pph21",
    response_model=CoretaxSubmissionResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Submit SPT Masa PPh 21",
    operation_id="submit_spt_pph21",
)
async def submit_spt_pph21(
    request: SPTMasaPPH21CreateSchema,
    _permission: None = Depends(require_permission("tax:submit_spt")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    coretax_service: Any = Depends(get_coretax_service),
) -> CoretaxSubmissionResponseSchema:
    """Submit SPT Masa PPh 21 to Coretax."""
    try:
        result = await coretax_service.submit_spt_pph21(
            legal_entity_id=legal_entity_id,
            masa_pajak=request.masa_pajak,
            tahun_pajak=request.tahun_pajak,
            total_bruto=request.total_bruto,
            total_pph_terutang=request.total_pph_terutang,
            jumlah_bayar=request.jumlah_bayar,
            ntpn=request.ntpn,
            submitted_by=current_user.user_id,
        )

        return CoretaxSubmissionResponseSchema(
            submission_id=result.id,
            submission_type="spt_pph21",
            reference_number=f"SPT21-{request.tahun_pajak}-{request.masa_pajak:02d}",
            status=result.status,
            coretax_tracking_id=result.coretax_tracking_id,
            coretax_response=result.coretax_response,
            error_message=result.error_message,
            created_at=result.created_at,
            submitted_at=result.submitted_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to submit SPT PPh 21: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# SPT MASA PPH 23/26
# ----------------------------------------------------------------------------


@router.post(
    "/spt/pph23",
    response_model=CoretaxSubmissionResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Submit SPT Masa PPh 23/26",
    operation_id="submit_spt_pph23",
)
async def submit_spt_pph23(
    request: SPTMasaPPH23CreateSchema,
    _permission: None = Depends(require_permission("tax:submit_spt")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    coretax_service: Any = Depends(get_coretax_service),
) -> CoretaxSubmissionResponseSchema:
    """Submit SPT Masa PPh 23/26 to Coretax."""
    try:
        result = await coretax_service.submit_spt_pph23(
            legal_entity_id=legal_entity_id,
            masa_pajak=request.masa_pajak,
            tahun_pajak=request.tahun_pajak,
            jenis_pajak=request.jenis_pajak,
            total_dpp=request.total_dpp,
            total_pph_dipotong=request.total_pph_dipotong,
            total_bayar=request.total_bayar,
            kompensasi=request.kompensasi,
            ntpn=request.ntpn,
            submitted_by=current_user.user_id,
        )

        return CoretaxSubmissionResponseSchema(
            submission_id=result.id,
            submission_type=f"spt_pph{request.jenis_pajak}",
            reference_number=f"SPT{request.jenis_pajak}-{request.tahun_pajak}-{request.masa_pajak:02d}",
            status=result.status,
            coretax_tracking_id=result.coretax_tracking_id,
            coretax_response=result.coretax_response,
            error_message=result.error_message,
            created_at=result.created_at,
            submitted_at=result.submitted_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to submit SPT PPh 23: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# SPT TAHUNAN BADAN
# ----------------------------------------------------------------------------


@router.post(
    "/spt/tahunan-badan",
    response_model=CoretaxSubmissionResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Submit SPT Tahunan PPh Badan",
    operation_id="submit_spt_tahunan_badan",
)
async def submit_spt_tahunan_badan(
    request: SPTTahunanBadanCreateSchema,
    _permission: None = Depends(require_permission("tax:submit_spt")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    coretax_service: Any = Depends(get_coretax_service),
) -> CoretaxSubmissionResponseSchema:
    """Submit Annual Corporate Income Tax Return to Coretax."""
    try:
        result = await coretax_service.submit_spt_tahunan_badan(
            legal_entity_id=legal_entity_id,
            tahun_pajak=request.tahun_pajak,
            penghasilan_neto_komersial=request.penghasilan_neto_komersial,
            penghasilan_neto_fiskal=request.penghasilan_neto_fiskal,
            kompensasi_kerugian=request.kompensasi_kerugian,
            penghasilan_kena_pajak=request.penghasilan_kena_pajak,
            pph_terutang=request.pph_terutang,
            total_kredit_pajak=request.total_kredit_pajak,
            kurang_bayar=request.kurang_bayar,
            lebih_bayar=request.lebih_bayar,
            ntpn=request.ntpn,
            submitted_by=current_user.user_id,
        )

        return CoretaxSubmissionResponseSchema(
            submission_id=result.id,
            submission_type="spt_tahunan_badan",
            reference_number=f"SPT-B-{request.tahun_pajak}",
            status=result.status,
            coretax_tracking_id=result.coretax_tracking_id,
            coretax_response=result.coretax_response,
            error_message=result.error_message,
            created_at=result.created_at,
            submitted_at=result.submitted_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to submit SPT Tahunan Badan: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# E-BUPOT (PPh 23/26)
# ----------------------------------------------------------------------------


@router.post(
    "/e-bupot",
    response_model=EBupotResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create e-Bupot",
    operation_id="create_e_bupot",
)
async def create_e_bupot(
    request: EBupotCreateSchema,
    _permission: None = Depends(require_permission("tax:create_bupot")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    coretax_service: Any = Depends(get_coretax_service),
) -> EBupotResponseSchema:
    """Create and submit e-Bupot PPh 23/26 to Coretax."""
    try:
        result = await coretax_service.create_e_bupot(
            legal_entity_id=legal_entity_id,
            masa_pajak=request.masa_pajak,
            tahun_pajak=request.tahun_pajak,
            npwp_pemotong=request.npwp_pemotong,
            npwp_penerima=request.npwp_penerima,
            nama_penerima=request.nama_penerima,
            alamat_penerima=request.alamat_penerima,
            jenis_pajak=request.jenis_pajak,
            jenis_penghasilan_code=request.jenis_penghasilan_code,
            dpp=request.dpp,
            tarif=request.tarif,
            tanggal_pemotongan=request.tanggal_pemotongan,
            invoice_reference=request.invoice_reference,
            keterangan=request.keterangan,
            created_by=current_user.user_id,
        )

        return EBupotResponseSchema(
            id=result.id,
            bupot_number=result.bupot_number,
            official_number=result.official_number,
            coretax_id=result.coretax_id,
            status=EBupotStatus(result.status),
            created_at=result.created_at,
            submitted_at=result.submitted_at,
            approved_at=result.approved_at,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to create e-Bupot: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/e-bupot",
    response_model=list[EBupotResponseSchema],
    summary="List e-Bupot",
    operation_id="list_e_bupot",
)
async def list_e_bupot(
    masa_pajak: int | None = Query(None, ge=1, le=12),
    tahun_pajak: int | None = Query(None, ge=2024, le=2100),
    status: EBupotStatus | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _permission: None = Depends(require_permission("tax:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    coretax_service: Any = Depends(get_coretax_service),
) -> list[EBupotResponseSchema]:
    """List e-Bupot with filters."""
    try:
        result = await coretax_service.list_e_bupot(
            legal_entity_id=legal_entity_id,
            masa_pajak=masa_pajak,
            tahun_pajak=tahun_pajak,
            status=status.value if status else None,
            page=page,
            page_size=page_size,
        )

        return [
            EBupotResponseSchema(
                id=b.id,
                bupot_number=b.bupot_number,
                official_number=b.official_number,
                coretax_id=b.coretax_id,
                status=EBupotStatus(b.status),
                created_at=b.created_at,
                submitted_at=b.submitted_at,
                approved_at=b.approved_at,
                version=b.version,
            )
            for b in result.items
        ]
    except Exception as e:
        logger.exception("Failed to list e-Bupot: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# E-METERAI
# ----------------------------------------------------------------------------


@router.post(
    "/e-meterai/validate",
    response_model=dict[str, Any],
    summary="Validate e-Meterai",
    operation_id="validate_e_meterai",
)
async def validate_e_meterai(
    request: EMeteraiValidateSchema,
    _permission: None = Depends(require_permission("tax:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    coretax_service: Any = Depends(get_coretax_service),
) -> dict[str, Any]:
    """Validate e-Meterai with Coretax."""
    try:
        result = await coretax_service.validate_e_meterai(
            legal_entity_id=legal_entity_id,
            meterai_code=request.meterai_code,
            document_id=request.document_id,
        )

        return {
            "meterai_code": (request.meterai_code[:8] + "..." + request.meterai_code[-4:]
                             if request.meterai_code else None),
            "is_valid": result.is_valid,
            "status": result.status,
            "value": float(result.value),
            "used_at": result.used_at.isoformat() if result.used_at else None,
            "used_on_document": result.used_on_document,
            "message": result.message,
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to validate e-Meterai: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/e-meterai/purchase",
    response_model=dict[str, Any],
    status_code=status.HTTP_201_CREATED,
    summary="Purchase e-Meterai",
    operation_id="purchase_e_meterai",
)
async def purchase_e_meterai(
    request: EMeteraiPurchaseSchema,
    _permission: None = Depends(require_permission("tax:purchase_meterai")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    coretax_service: Any = Depends(get_coretax_service),
) -> dict[str, Any]:
    """Purchase e-Meterai from DJP Coretax."""
    try:
        result = await coretax_service.purchase_e_meterai(
            legal_entity_id=legal_entity_id,
            quantity=request.quantity,
            npwp=request.npwp,
            purpose=request.purpose,
            purchased_by=current_user.user_id,
        )

        return {
            "purchase_id": str(result.purchase_id),
            "transaction_id": result.transaction_id,
            "quantity": result.quantity,
            "total_amount": float(result.total_amount),
            "meterai_list": [c[:8] + "..." + c[-4:] for c in result.meterai_list],
            "status": result.status,
            "purchased_at": result.purchased_at.isoformat(),
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to purchase e-Meterai: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# BULK SUBMISSION
# ----------------------------------------------------------------------------


@router.post(
    "/bulk-submit/faktur",
    response_model=dict[str, Any],
    summary="Bulk submit tax invoices",
    operation_id="bulk_submit_faktur",
)
async def bulk_submit_faktur(
    faktur_ids: list[UUID] = Body(..., description="List of faktur IDs"),
    _permission: None = Depends(require_permission("tax:bulk_submit")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    bulk_use_case: Any = Depends(get_coretax_bulk_use_case),
) -> dict[str, Any]:
    """Bulk submit multiple tax invoices to Coretax."""
    try:
        result = await bulk_use_case.submit_faktur_batch(
            faktur_ids=faktur_ids,
            legal_entity_id=legal_entity_id,
            submitted_by=current_user.user_id,
        )

        return {
            "batch_id": str(result.batch_id),
            "total_submitted": result.total_submitted,
            "success_count": result.success_count,
            "failed_count": result.failed_count,
            "failed_ids": [str(fid) for fid in result.failed_ids],
            "errors": result.errors,
        }
    except Exception as e:
        logger.exception("Failed to bulk submit faktur: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# CORETAX DASHBOARD
# ----------------------------------------------------------------------------


@router.get(
    "/dashboard",
    response_model=CoretaxDashboardResponseSchema,
    summary="Get Coretax dashboard",
    operation_id="get_coretax_dashboard",
)
async def get_coretax_dashboard(
    _permission: None = Depends(require_permission("tax:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    coretax_service: Any = Depends(get_coretax_service),
) -> CoretaxDashboardResponseSchema:
    """Get Coretax integration dashboard with real-time status."""
    try:
        dashboard = await coretax_service.get_dashboard(legal_entity_id)

        return CoretaxDashboardResponseSchema(
            nsfp_quota_remaining=dashboard.nsfp_quota_remaining,
            nsfp_quota_used=dashboard.nsfp_quota_used,
            faktur_submitted_today=dashboard.faktur_submitted_today,
            faktur_approved_today=dashboard.faktur_approved_today,
            faktur_rejected_today=dashboard.faktur_rejected_today,
            spt_submitted_this_month=dashboard.spt_submitted_this_month,
            spt_approved_this_month=dashboard.spt_approved_this_month,
            spt_rejected_this_month=dashboard.spt_rejected_this_month,
            api_health=dashboard.api_health,
            last_sync_at=dashboard.last_sync_at,
            pending_faktur=dashboard.pending_faktur,
            pending_spt=dashboard.pending_spt,
            pending_bupot=dashboard.pending_bupot,
        )
    except Exception as e:
        logger.exception("Failed to get Coretax dashboard: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# TAX FILING STATUS
# ----------------------------------------------------------------------------


@router.get(
    "/filing-status",
    response_model=list[TaxFilingStatusSchema],
    summary="Get tax filing status",
    operation_id="get_tax_filing_status",
)
async def get_tax_filing_status(
    year: int = Query(..., ge=2024, le=2100, description="Tax year"),
    tax_type: TaxType | None = Query(None, description="Filter by tax type"),
    _permission: None = Depends(require_permission("tax:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    tax_service: Any = Depends(get_tax_service),
) -> list[TaxFilingStatusSchema]:
    """Get tax filing status for all periods in a year."""
    try:
        statuses = await tax_service.get_filing_status(
            legal_entity_id=legal_entity_id,
            year=year,
            tax_type=tax_type.value if tax_type else None,
        )

        return [
            TaxFilingStatusSchema(
                tax_type=TaxType(s.tax_type),
                period=s.period,
                due_date=s.due_date,
                status=s.status,
                submitted_at=s.submitted_at,
                approved_at=s.approved_at,
                is_late=s.is_late,
                days_overdue=s.days_overdue,
            )
            for s in statuses
        ]
    except Exception as e:
        logger.exception("Failed to get tax filing status: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# TAX DUE DATE
# ----------------------------------------------------------------------------


@router.get(
    "/due-dates",
    response_model=list[dict[str, Any]],
    summary="Get upcoming tax due dates",
    operation_id="get_tax_due_dates",
)
async def get_tax_due_dates(
    days_ahead: int = Query(30, ge=1, le=365, description="Days ahead to check"),
    _permission: None = Depends(require_permission("tax:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    tax_service: Any = Depends(get_tax_service),
) -> list[dict[str, Any]]:
    """Get upcoming tax due dates."""
    try:
        due_dates = await tax_service.get_upcoming_due_dates(
            legal_entity_id=legal_entity_id,
            days_ahead=days_ahead,
        )

        return [
            {
                "tax_type": d.tax_type,
                "period": d.period,
                "due_date": d.due_date.isoformat(),
                "is_overdue": d.is_overdue,
                "days_remaining": d.days_remaining,
                "estimated_amount": float(d.estimated_amount) if d.estimated_amount else None,
                "status": d.status,
            }
            for d in due_dates
        ]
    except Exception as e:
        logger.exception("Failed to get tax due dates: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# TAX SUMMARY REPORT
# ----------------------------------------------------------------------------


@router.get(
    "/summary",
    response_model=dict[str, Any],
    summary="Get tax summary report",
    operation_id="get_tax_summary",
)
async def get_tax_summary(
    start_date: date = Query(..., description="Start date"),
    end_date: date = Query(..., description="End date"),
    _permission: None = Depends(require_permission("tax:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    tax_service: Any = Depends(get_tax_service),
) -> dict[str, Any]:
    """Get tax summary report for a period."""
    try:
        summary = await tax_service.get_tax_summary(
            legal_entity_id=legal_entity_id,
            start_date=start_date,
            end_date=end_date,
        )

        return {
            "period_start": start_date.isoformat(),
            "period_end": end_date.isoformat(),
            "ppn": {
                "output": float(summary.ppn_output),
                "input": float(summary.ppn_input),
                "net": float(summary.ppn_net),
                "payable": float(summary.ppn_payable),
                "credited": float(summary.ppn_credited),
            },
            "pph": {
                "pph21": float(summary.pph21),
                "pph22": float(summary.pph22),
                "pph23": float(summary.pph23),
                "pph25": float(summary.pph25),
                "pph26": float(summary.pph26),
                "pph4_2": float(summary.pph4_2),
                "pph_badan": float(summary.pph_badan),
                "total": float(summary.pph_total),
            },
            "total_tax": float(summary.total_tax),
            "paid_amount": float(summary.paid_amount),
            "outstanding": float(summary.outstanding),
            "generated_at": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.exception("Failed to get tax summary: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# EXPORT TAX DATA
# ----------------------------------------------------------------------------


@router.get(
    "/export",
    summary="Export tax data",
    operation_id="export_tax_data",
)
async def export_tax_data(
    start_date: date = Query(..., description="Start date"),
    end_date: date = Query(..., description="End date"),
    format: str = Query("csv", pattern="^(csv|excel)$", description="Export format"),
    tax_type: TaxType | None = Query(None, description="Filter by tax type"),
    _permission: None = Depends(require_permission("tax:export")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    tax_service: Any = Depends(get_tax_service),
) -> Response:
    """Export tax data to CSV or Excel."""
    try:
        data = await tax_service.export_tax_data(
            legal_entity_id=legal_entity_id,
            start_date=start_date,
            end_date=end_date,
            format=format,
            tax_type=tax_type.value if tax_type else None,
        )

        media_type = (
            "text/csv"
            if format == "csv"
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        filename = f"tax_data_{legal_entity_id}_{start_date}_{end_date}.{format}"

        return Response(
            content=data,
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        logger.exception("Failed to export tax data: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# EXPORTS
# ----------------------------------------------------------------------------

__all__ = ["router"]
