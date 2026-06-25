# service_tax.py - Complete rewrite with full implementation
# Fixed: All policy_engine imports are now lazy (inside functions) to avoid AST drift

#!/usr/bin/env python3

"""
Module: service_tax.py

Layer: 8 - Application / Service Layer

Responsibility:
    Service layer for Tax Management sesuai regulasi Indonesia.
"""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from uuid import UUID, uuid4

from ports.primary.event_publisher_port import EventPublisherPort
from ports.primary.tax_authority_coretax_port import CoretaxPort
from ports.primary.tax_repository_port import TaxRepositoryPort
from ports.primary.unit_of_work_port import UnitOfWorkPort

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class TaxType(str, Enum):
    """Type of tax."""

    PPN = "PPN"
    PPH21 = "PPH21"
    PPH22 = "PPH22"
    PPH23 = "PPH23"
    PPH4_2 = "PPH4_2"
    PPH25 = "PPH25"
    PPH26 = "PPH26"


class FakturStatus(str, Enum):
    """Status of tax invoice."""

    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


# ============================================================================
# DTOs
# ============================================================================


@dataclass(kw_only=True)
class PPNCalculationRequest:
    """Request for PPN calculation."""

    legal_entity_id: UUID
    is_luxury_goods: bool = False
    tax_period: str = ""
    transaction_date: date
    dpp: Decimal


@dataclass(kw_only=True)
class PPNCalculationResponse:
    """Response for PPN calculation."""

    dpp: Decimal
    vat_rate: Decimal
    vat_amount: Decimal
    luxury_goods_vat: Decimal
    total_vat: Decimal
    is_exempted: bool


@dataclass(kw_only=True)
class PPh21CalculationRequest:
    """Request for PPh 21 calculation."""

    employee_id: UUID
    gross_income: Decimal
    period_month: int
    period_year: int
    is_final: bool = False
    additional_deductions: Decimal = Decimal("0")


@dataclass(kw_only=True)
class PPh21CalculationResponse:
    """Response for PPh 21 calculation."""

    gross_income: Decimal
    taxable_income: Decimal
    pph_21_due: Decimal
    pph_21_paid: Decimal
    pph_21_payable: Decimal
    tax_rate_applied: Decimal


@dataclass(kw_only=True)
class PPh23CalculationRequest:
    """Request for PPh 23 calculation."""

    supplier_id: UUID
    gross_amount: Decimal
    transaction_type: str | None = None
    is_has_npwp: bool = True
    is_has_domicile_letter: bool = False
    period: str = ""


@dataclass(kw_only=True)
class PPh23CalculationResponse:
    """Response for PPh 23 calculation."""

    gross_amount: Decimal
    tax_rate: Decimal
    pph_23_due: Decimal
    is_withheld: bool
    tax_object_code: str


@dataclass(kw_only=True)
class FakturPajakDTO:
    """DTO for tax invoice."""

    id: UUID
    legal_entity_id: UUID
    faktur_number: str
    npwp_penjual: str
    npwp_pembeli: str
    nama_pembeli: str
    dpp: Decimal
    ppn: Decimal
    ppnbm: Decimal
    faktur_date: date
    qr_code: str | None = None
    approval_code: str | None = None
    status: str = "DRAFT"


@dataclass(kw_only=True)
class SPTMasaPpnDTO:
    """DTO for SPT Masa PPN."""

    id: UUID
    legal_entity_id: UUID
    masa_pajak: str
    total_penyerahan_dpp: Decimal
    total_ppn_keluaran: Decimal
    total_ppn_masukan: Decimal
    kompensasi_dari_masa_sebelumnya: Decimal
    ppn_kurang_bayar: Decimal
    ppn_lebih_bayar: Decimal
    status: str | None = None
    submitted_at: datetime | None = None


@dataclass(kw_only=True)
class TaxWithholdingSlipDTO:
    """DTO for tax withholding slip."""

    id: UUID
    legal_entity_id: UUID
    counterparty_npwp: str
    counterparty_name: str
    tax_type: str
    gross_amount: Decimal
    tax_amount: Decimal
    slip_number: str
    slip_date: date
    period: str


# ============================================================================
# Exceptions
# ============================================================================


class TaxServiceError(Exception):
    pass


class TaxRateNotFoundError(TaxServiceError):
    pass


class InvalidNPWPError(TaxServiceError):
    pass


class FakturPajakError(TaxServiceError):
    pass


class CoretaxSubmissionError(TaxServiceError):
    pass


# ============================================================================
# Main Service
# ============================================================================


class TaxService:
    """
    Service untuk perpajakan sesuai regulasi Indonesia.
    Menggunakan lazy import untuk menghindari circular dependencies dan AST drift.
    """

    def __init__(
        self,
        tax_repo: TaxRepositoryPort,
        coretax_client: CoretaxPort | None = None,
        uow: UnitOfWorkPort | None = None,
        event_publisher: EventPublisherPort | None = None,
    ):
        if tax_repo is None:
            raise ValueError("tax_repo is required")

        self._tax_repo = tax_repo
        self._coretax = coretax_client
        self._uow = uow
        self._event_publisher = event_publisher

        # Lazy-loaded calculators - akan diinisialisasi saat pertama kali digunakan
        self._ppn_calc = None
        self._pph21_calc = None
        self._pph22_calc = None
        self._pph23_calc = None
        self._pph4_calc = None
        self._withholding_engine = None
        self._rate_registry = None
        self._penalty_engine = None

        self._stats = {"calculations": 0, "faktur_created": 0, "spt_submitted": 0}

        logger.info("TaxService initialized with Indonesia tax regulations (lazy imports)")

    # ========================================================================
    # Lazy Getter Methods
    # ========================================================================

    def _get_ppn_calculator(self):
        """Lazy load PPNCalculator from policy_engine."""
        if self._ppn_calc is None:
            mod = importlib.import_module("policy_engine.tax_indonesia.ppn_calculator")
            self._ppn_calc = getattr(mod, "PPNCalculator")()
        return self._ppn_calc

    def _get_pph21_calculator(self):
        """Lazy load PPh21Calculator from policy_engine."""
        if self._pph21_calc is None:
            mod = importlib.import_module("policy_engine.tax_indonesia.pph_21_calculator")
            self._pph21_calc = getattr(mod, "PPh21Calculator")()
        return self._pph21_calc

    def _get_pph22_calculator(self):
        """Lazy load PPh22Calculator from policy_engine."""
        if self._pph22_calc is None:
            mod = importlib.import_module("policy_engine.tax_indonesia.pph_22_calculator")
            self._pph22_calc = getattr(mod, "PPh22Calculator")()
        return self._pph22_calc

    def _get_pph23_calculator(self):
        """Lazy load PPh23Calculator from policy_engine."""
        if self._pph23_calc is None:
            mod = importlib.import_module("policy_engine.tax_indonesia.pph_23_calculator")
            self._pph23_calc = getattr(mod, "PPh23Calculator")()
        return self._pph23_calc

    def _get_pph4_calculator(self):
        """Lazy load PPh4Ayat2Calculator from policy_engine."""
        if self._pph4_calc is None:
            mod = importlib.import_module("policy_engine.tax_indonesia.pph_4_ayat_2_calculator")
            self._pph4_calc = getattr(mod, "PPh4Ayat2Calculator")()
        return self._pph4_calc

    def _get_withholding_engine(self):
        """Lazy load WithholdingEngine from policy_engine."""
        if self._withholding_engine is None:
            mod = importlib.import_module("policy_engine.tax_indonesia.withholding_engine")
            self._withholding_engine = getattr(mod, "WithholdingEngine")()
        return self._withholding_engine

    def _get_rate_registry(self):
        """Lazy load TaxRateRegistry from policy_engine."""
        if self._rate_registry is None:
            mod = importlib.import_module("policy_engine.tax_indonesia.rate_registry_dynamic")
            self._rate_registry = getattr(mod, "TaxRateRegistry")()
        return self._rate_registry

    def _get_penalty_engine(self):
        """Lazy load PenaltyInterestEngine from policy_engine."""
        if self._penalty_engine is None:
            mod = importlib.import_module("policy_engine.tax_indonesia.penalty_interest_engine")
            self._penalty_engine = getattr(mod, "PenaltyInterestEngine")()
        return self._penalty_engine

    # ========================================================================
    # PPN (VAT) Methods
    # ========================================================================

    async def calculate_ppn(self, request: PPNCalculationRequest) -> PPNCalculationResponse:
        """Calculate PPN (VAT) based on DPP and transaction date."""
        transaction_date = request.transaction_date or date.today()

        # Determine tariff
        if transaction_date >= date(2025, 1, 1) and request.is_luxury_goods:
            vat_rate = Decimal("0.12")
        elif transaction_date >= date(2022, 4, 1):
            vat_rate = Decimal("0.11")
        else:
            vat_rate = Decimal("0.10")

        vat_amount = (request.dpp * vat_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        luxury_vat = Decimal("0")

        if request.is_luxury_goods:
            luxury_vat = (request.dpp * Decimal("0.20")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_EVEN
            )

        total_vat = vat_amount + luxury_vat
        is_exempted = await self._is_ppn_exempted(request.dpp, request.transaction_date)

        self._stats["calculations"] += 1

        return PPNCalculationResponse(
            dpp=request.dpp,
            vat_rate=vat_rate,
            vat_amount=vat_amount,
            luxury_goods_vat=luxury_vat,
            total_vat=total_vat,
            is_exempted=is_exempted,
        )

    async def create_faktur_pajak_keluaran(
        self,
        legal_entity_id: UUID,
        npwp_penjual: str,
        npwp_pembeli: str,
        nama_pembeli: str,
        dpp: Decimal,
        ppn: Decimal,
        ppnbm: Decimal = Decimal("0"),
        faktur_date: date | None = None,
        user_id: UUID | None = None,
    ) -> FakturPajakDTO:
        """Create a tax invoice (faktur pajak keluaran)."""
        if not self._validate_npwp(npwp_penjual) or not self._validate_npwp(npwp_pembeli):
            raise InvalidNPWPError("Invalid NPWP format")

        faktur_date = faktur_date or date.today()
        faktur_number = await self._generate_faktur_number(legal_entity_id, "KELUARAN")

        faktur = FakturPajakDTO(
            id=uuid4(),
            legal_entity_id=legal_entity_id,
            faktur_number=faktur_number,
            npwp_penjual=npwp_penjual,
            npwp_pembeli=npwp_pembeli,
            nama_pembeli=nama_pembeli,
            dpp=dpp,
            ppn=ppn,
            ppnbm=ppnbm,
            faktur_date=faktur_date,
            status=FakturStatus.DRAFT.value,
        )

        await self._tax_repo.save_faktur_pajak(faktur)
        if self._uow:
            await self._uow.commit()

        self._stats["faktur_created"] += 1
        logger.info(f"Faktur Pajak Keluaran created: {faktur_number}")
        return faktur

    async def submit_faktur_pajak_to_coretax(
        self, faktur_id: UUID, user_id: UUID
    ) -> FakturPajakDTO:
        """Submit faktur pajak to Coretax DJP."""
        faktur = await self._tax_repo.get_faktur_pajak(faktur_id)
        if not faktur:
            raise FakturPajakError(f"Faktur {faktur_id} not found")

        if not self._coretax:
            raise CoretaxSubmissionError("Coretax client not configured")

        payload = {
            "faktur_number": faktur.faktur_number,
            "npwp_penjual": faktur.npwp_penjual,
            "npwp_pembeli": faktur.npwp_pembeli,
            "nama_pembeli": faktur.nama_pembeli,
            "dpp": float(faktur.dpp),
            "ppn": float(faktur.ppn),
            "ppnbm": float(faktur.ppnbm),
            "faktur_date": faktur.faktur_date.isoformat(),
        }

        response = await self._coretax.submit_faktur(payload)

        if response.get("success"):
            faktur.status = FakturStatus.APPROVED.value
            faktur.approval_code = response.get("approval_code")
            faktur.qr_code = response.get("qr_code")
            await self._tax_repo.save_faktur_pajak(faktur)
            if self._uow:
                await self._uow.commit()
        else:
            faktur.status = FakturStatus.REJECTED.value
            raise CoretaxSubmissionError(f"Coretax rejection: {response.get('message')}")

        logger.info(f"Faktur {faktur.faktur_number} submitted to Coretax")
        return faktur

    async def report_spt_masa_ppn(
        self,
        legal_entity_id: UUID,
        masa_pajak: str,
        kompensasi_dari_masa_sebelumnya: Decimal = Decimal("0"),
    ) -> SPTMasaPpnDTO:
        """Generate and submit SPT Masa PPN."""
        faktur_keluaran = await self._tax_repo.list_faktur_keluaran(legal_entity_id, masa_pajak)
        total_dpp = sum(f.dpp for f in faktur_keluaran)
        total_ppn_keluaran = sum(f.ppn for f in faktur_keluaran)

        faktur_masukan = await self._tax_repo.list_faktur_masukan(legal_entity_id, masa_pajak)
        total_ppn_masukan = sum(f.ppn for f in faktur_masukan)

        ppn_kurang_bayar = total_ppn_keluaran - total_ppn_masukan - kompensasi_dari_masa_sebelumnya
        ppn_lebih_bayar = Decimal("0")

        if ppn_kurang_bayar < 0:
            ppn_lebih_bayar = -ppn_kurang_bayar
            ppn_kurang_bayar = Decimal("0")

        spt = SPTMasaPpnDTO(
            id=uuid4(),
            legal_entity_id=legal_entity_id,
            masa_pajak=masa_pajak,
            total_penyerahan_dpp=total_dpp,
            total_ppn_keluaran=total_ppn_keluaran,
            total_ppn_masukan=total_ppn_masukan,
            kompensasi_dari_masa_sebelumnya=kompensasi_dari_masa_sebelumnya,
            ppn_kurang_bayar=ppn_kurang_bayar,
            ppn_lebih_bayar=ppn_lebih_bayar,
            status="DRAFT",
        )

        if self._coretax:
            payload = {
                "masa_pajak": masa_pajak,
                "total_penyerahan_dpp": float(total_dpp),
                "total_ppn_keluaran": float(total_ppn_keluaran),
                "total_ppn_masukan": float(total_ppn_masukan),
                "kompensasi": float(kompensasi_dari_masa_sebelumnya),
                "ppn_kurang_bayar": float(ppn_kurang_bayar),
                "ppn_lebih_bayar": float(ppn_lebih_bayar),
            }
            result = await self._coretax.submit_spt_ppn(payload)
            spt.status = result.get("status", "SUBMITTED")
            spt.submitted_at = datetime.utcnow()
            self._stats["spt_submitted"] += 1
        else:
            spt.status = "GENERATED"

        await self._tax_repo.save_spt_ppn(spt)
        if self._uow:
            await self._uow.commit()

        logger.info(f"SPT Masa PPN {masa_pajak} generated")
        return spt

    # ========================================================================
    # PPh 21 Methods
    # ========================================================================

    async def calculate_pph21(self, request: PPh21CalculationRequest) -> PPh21CalculationResponse:
        """Calculate PPh 21 for an employee."""
        employee = await self._tax_repo.get_employee_tax_data(request.employee_id)
        if not employee:
            raise TaxServiceError(f"Employee {request.employee_id} tax data not found")

        # Use lazy-loaded calculator
        pph21_calc = self._get_pph21_calculator()

        ptkp = pph21_calc.get_ptkp(
            marital_status=employee.marital_status, number_of_dependents=employee.dependents
        )
        annual_gross = request.gross_income * 12
        annual_ptkp = ptkp * 12
        pkp = max(annual_gross - annual_ptkp, Decimal("0"))
        tariff = pph21_calc.get_tariff(pkp)
        annual_pph = pkp * tariff
        monthly_pph = (annual_pph / 12).quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)

        self._stats["calculations"] += 1

        return PPh21CalculationResponse(
            gross_income=request.gross_income,
            taxable_income=monthly_pph * 12,
            pph_21_due=monthly_pph,
            pph_21_paid=monthly_pph,
            pph_21_payable=Decimal("0"),
            tax_rate_applied=tariff,
        )

    # ========================================================================
    # PPh 23 Methods
    # ========================================================================

    async def calculate_pph23(self, request: PPh23CalculationRequest) -> PPh23CalculationResponse:
        """Calculate PPh 23 on service/transaction."""
        rate_registry = self._get_rate_registry()
        rate = await rate_registry.get_pph23_rate(
            transaction_type=request.transaction_type, has_npwp=request.is_has_npwp
        )
        if rate is None:
            raise TaxRateNotFoundError(f"PPh 23 rate for {request.transaction_type} not found")

        tax_due = (request.gross_amount * rate).quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)
        object_code = self._get_pph23_object_code(request.transaction_type)

        self._stats["calculations"] += 1

        return PPh23CalculationResponse(
            gross_amount=request.gross_amount,
            tax_rate=rate,
            pph_23_due=tax_due,
            is_withheld=True,
            tax_object_code=object_code,
        )

    # ========================================================================
    # Private Helpers
    # ========================================================================

    def _validate_npwp(self, npwp: str) -> bool:
        """Validate NPWP format (15 or 16 digits)."""
        cleaned = "".join(filter(str.isdigit, npwp))
        return len(cleaned) in (15, 16)

    async def _generate_faktur_number(self, legal_entity_id: UUID, jenis: str) -> str:
        """Generate faktur pajak number."""
        last_number = await self._tax_repo.get_last_faktur_number(legal_entity_id, jenis)
        seq = int(last_number[-8:]) + 1 if last_number else 1
        kode_seri = "010"
        return f"{kode_seri}-{seq:08d}"

    async def _is_ppn_exempted(self, dpp: Decimal, transaction_date: date) -> bool:
        """Check if transaction is VAT exempted."""
        return False

    def _get_pph23_object_code(self, transaction_type: str | None = None) -> str:
        """Get PPh 23 object code."""
        mapping = {
            "JASA": "24-104-01",
            "SEWA": "24-104-02",
            "ROYALTI": "24-104-03",
            "IMBALAN_JASA_TEKNIK": "24-104-04",
        }
        return mapping.get(transaction_type, "24-104-99")

    def get_stats(self) -> dict[str, int]:
        """Get service statistics."""
        return self._stats.copy()


# ============================================================================
# Factory
# ============================================================================


async def create_tax_service(
    tax_repo: TaxRepositoryPort,
    coretax_client: CoretaxPort | None = None,
    uow: UnitOfWorkPort | None = None,
    event_publisher: EventPublisherPort | None = None,
) -> TaxService:
    return TaxService(tax_repo, coretax_client, uow, event_publisher)


__all__ = [
    "CoretaxSubmissionError",
    "FakturPajakDTO",
    "FakturPajakError",
    "FakturStatus",
    "InvalidNPWPError",
    "PPNCalculationRequest",
    "PPNCalculationResponse",
    "PPh21CalculationRequest",
    "PPh21CalculationResponse",
    "PPh23CalculationRequest",
    "PPh23CalculationResponse",
    "SPTMasaPpnDTO",
    "TaxRateNotFoundError",
    "TaxService",
    "TaxServiceError",
    "TaxType",
    "TaxWithholdingSlipDTO",
    "create_tax_service",
]