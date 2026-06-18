# service_coretax.py - Complete rewrite with fixes

#!/usr/bin/env python3

"""
Module: service_coretax.py

Layer: 8 - Application / Service Layer

Responsibility:
    Service layer for Coretax DJP integration.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from application.dto_objects.coretax_submission_request import (
    NPWP,
    BuktiPotongPPh23DTO,
    CoretaxSubmissionResponse,
    FakturPajakKeluaranDTO,
    FakturPajakMasukanDTO,
    MasaPajak,
    SPTMasaPph21Request,
    SPTMasaPpnRequest,
    SPTTahunanBadanRequest,
)
from ports.primary.event_publisher_port import EventPublisherPort
from ports.primary.tax_authority_coretax_port import CoretaxPort
from ports.primary.tax_repository_port import TaxRepositoryPort
from ports.primary.unit_of_work_port import UnitOfWorkPort

logger = logging.getLogger(__name__)


# ============================================================================
# Exceptions
# ============================================================================


class CoretaxServiceError(Exception):
    pass


class CoretaxAuthenticationError(CoretaxServiceError):
    pass


class CoretaxSubmissionError(CoretaxServiceError):
    pass


class FakturPajakNotFoundError(CoretaxServiceError):
    pass


class NSFPExhaustedError(CoretaxServiceError):
    pass


# ============================================================================
# Main Service
# ============================================================================


class CoretaxService:
    """
    Service untuk integrasi dengan Coretax DJP.
    """

    def __init__(
        self,
        coretax_client: CoretaxPort,
        tax_repo: TaxRepositoryPort,
        uow: UnitOfWorkPort | None = None,
        event_publisher: EventPublisherPort | None = None,
    ):
        self._coretax = coretax_client
        self._tax_repo = tax_repo
        self._uow = uow
        self._event_publisher = event_publisher
        self._nsfp_range: tuple[str, str] | None = None
        self._nsfp_current: str | None = None
        self._stats = {"faktur_submitted": 0, "spt_submitted": 0, "errors": 0}

        logger.info("CoretaxService initialized")

    # ========================================================================
    # NSFP Management
    # ========================================================================

    async def request_nsfp(self, legal_entity_id: UUID, jumlah: int = 100) -> tuple[str, str]:
        """Request Nomor Seri Faktur Pajak (NSFP) from Coretax."""
        response = await self._coretax.request_nsfp(legal_entity_id, jumlah)
        if response.get("success"):
            start = response["start_number"]
            end = response["end_number"]
            self._nsfp_range = (start, end)
            self._nsfp_current = start
            await self._tax_repo.save_nsfp_range(legal_entity_id, start, end, datetime.now(UTC))
            logger.info(f"NSFP range obtained: {start} - {end}")
            return start, end
        else:
            raise CoretaxSubmissionError(f"NSFP request failed: {response.get('message')}")

    async def get_next_nsfp(self, legal_entity_id: UUID) -> str:
        """Get next available NSFP number."""
        if not self._nsfp_range or not self._nsfp_current:
            saved = await self._tax_repo.get_current_nsfp_range(legal_entity_id)
            if saved:
                self._nsfp_range = (saved.start, saved.end)
                self._nsfp_current = saved.current
            else:
                await self.request_nsfp(legal_entity_id)

        if (
            self._nsfp_current
            and self._nsfp_range
            and int(self._nsfp_current) < int(self._nsfp_range[1])
        ):
            next_num = str(int(self._nsfp_current) + 1).zfill(16)
            self._nsfp_current = next_num
            await self._tax_repo.update_nsfp_current(legal_entity_id, next_num)
            return next_num
        else:
            await self.request_nsfp(legal_entity_id, 100)
            return await self.get_next_nsfp(legal_entity_id)

    # ========================================================================
    # Faktur Pajak Keluaran
    # ========================================================================

    async def submit_faktur_keluaran(
        self, faktur: FakturPajakKeluaranDTO, user_id: UUID, correlation_id: str | None = None
    ) -> CoretaxSubmissionResponse:
        """Submit faktur pajak keluaran to Coretax."""
        if not faktur.seri_faktur:
            nsfp = await self.get_next_nsfp(faktur.npwp_penjual.value)
            faktur.seri_faktur = nsfp

        payload = faktur.to_coretax_payload()
        response = await self._coretax.submit_faktur(payload)

        if response.get("success"):
            faktur.status = "APPROVED"
            faktur.approval_code = response.get("approval_code")
            faktur.qr_code = response.get("qr_code")
            await self._tax_repo.save_faktur_keluaran(faktur)
            if self._uow:
                await self._uow.commit()

            self._stats["faktur_submitted"] += 1
            logger.info(f"Faktur {faktur.seri_faktur} submitted successfully")
            return CoretaxSubmissionResponse(
                success=True,
                submission_id=uuid4(),
                status="APPROVED",
                message="Faktur approved",
                timestamp=datetime.now(UTC),
                approval_code=faktur.approval_code,
            )
        else:
            faktur.status = "REJECTED"
            await self._tax_repo.save_faktur_keluaran(faktur)
            self._stats["errors"] += 1
            raise CoretaxSubmissionError(f"Submission failed: {response.get('message')}")

    async def cancel_faktur_keluaran(self, faktur_id: UUID, reason: str, user_id: UUID) -> bool:
        """Cancel existing faktur pajak keluaran."""
        faktur = await self._tax_repo.get_faktur_keluaran(faktur_id)
        if not faktur:
            raise FakturPajakNotFoundError(f"Faktur {faktur_id} not found")

        response = await self._coretax.cancel_faktur(faktur.seri_faktur, reason)
        if response.get("success"):
            faktur.status = "CANCELLED"
            await self._tax_repo.save_faktur_keluaran(faktur)
            if self._uow:
                await self._uow.commit()
            return True
        return False

    # ========================================================================
    # Faktur Pajak Masukan
    # ========================================================================

    async def import_faktur_masukan(
        self, npwp: str, masa_pajak: str
    ) -> list[FakturPajakMasukanDTO]:
        """Import faktur pajak masukan from Coretax."""
        response = await self._coretax.get_faktur_masukan(npwp, masa_pajak)
        fakturs = []

        for item in response.get("data", []):
            faktur = FakturPajakMasukanDTO(
                id=uuid4(),
                npwp_penjual=NPWP(item["npwp_penjual"]),
                npwp_pembeli=NPWP(item["npwp_pembeli"]),
                nomor_faktur=item["nomor_faktur"],
                tanggal_faktur=datetime.strptime(item["tanggal"], "%Y-%m-%d").date(),
                dpp=Decimal(str(item["dpp"])),
                ppn=Decimal(str(item["ppn"])),
                is_pengusaha_kecil_tertentu=item.get("is_pengusaha_kecil_tertentu", False),
                status_kredit="BELUM_KREDIT",
                masa_pajak_pengakuan=MasaPajak(
                    bulan=int(masa_pajak.split("-")[1]), tahun=int(masa_pajak.split("-")[0])
                ),
            )
            await self._tax_repo.save_faktur_masukan(faktur)
            fakturs.append(faktur)

        if self._uow:
            await self._uow.commit()
        return fakturs

    # ========================================================================
    # e-Bupot (PPh 23/26)
    # ========================================================================

    async def submit_ebupot(
        self, bukti_potong: BuktiPotongPPh23DTO, user_id: UUID
    ) -> CoretaxSubmissionResponse:
        """Submit e-Bupot PPh 23 to Coretax."""
        payload = {
            "id": str(bukti_potong.id),
            "npwp_pemotong": bukti_potong.npwp_pemotong.value,
            "npwp_penerima": bukti_potong.npwp_penerima.value,
            "nama_penerima": bukti_potong.nama_penerima,
            "tanggal": bukti_potong.tanggal_pemotongan.isoformat(),
            "kode_objek": bukti_potong.kode_objek_pajak.value,
            "dasar_pemotongan": float(bukti_potong.dasar_pemotongan),
            "tarif": float(bukti_potong.tarif_persen),
            "pph_dipotong": float(bukti_potong.pph_dipotong),
            "idempotency_key": bukti_potong.idempotency_key,
        }
        response = await self._coretax.submit_ebupot(payload)

        if response.get("success"):
            bukti_potong.status = "APPROVED"
            bukti_potong.nomor_bukpot = response.get("nomor_bukpot")
            await self._tax_repo.save_bukti_potong(bukti_potong)
            if self._uow:
                await self._uow.commit()

            self._stats["spt_submitted"] += 1
            return CoretaxSubmissionResponse(
                success=True,
                submission_id=bukti_potong.id,
                status="APPROVED",
                message="e-Bupot approved",
                timestamp=datetime.now(UTC),
                approval_code=bukti_potong.nomor_bukpot,
            )
        else:
            self._stats["errors"] += 1
            raise CoretaxSubmissionError(f"e-Bupot submission failed: {response.get('message')}")

    # ========================================================================
    # SPT Masa PPN
    # ========================================================================

    async def submit_spt_masa_ppn(
        self, spt: SPTMasaPpnRequest, user_id: UUID
    ) -> CoretaxSubmissionResponse:
        """Submit SPT Masa PPN to Coretax."""
        payload = spt.to_coretax_payload()
        response = await self._coretax.submit_spt_ppn(payload)

        if response.get("success"):
            spt.status = "APPROVED"
            await self._tax_repo.save_spt_ppn(spt)
            if self._uow:
                await self._uow.commit()

            self._stats["spt_submitted"] += 1
            return CoretaxSubmissionResponse(
                success=True,
                submission_id=spt.id,
                status="APPROVED",
                message="SPT PPN submitted",
                timestamp=datetime.now(UTC),
            )
        else:
            self._stats["errors"] += 1
            raise CoretaxSubmissionError(f"SPT PPN failed: {response.get('message')}")

    # ========================================================================
    # SPT Masa PPh 21
    # ========================================================================

    async def submit_spt_masa_pph21(
        self, spt: SPTMasaPph21Request, user_id: UUID
    ) -> CoretaxSubmissionResponse:
        """Submit SPT Masa PPh 21 to Coretax."""
        payload = {
            "id": str(spt.id),
            "npwp": spt.npwp_pemotong.value,
            "masa_pajak": spt.masa_pajak.to_str(),
            "total_bruto": float(spt.total_bruto),
            "total_pph_dipotong": float(spt.total_pph_dipotong),
            "total_pph_setor": float(spt.total_pph_setor),
            "ntpn_list": [
                {"ntpn": ref.ntpn.value, "amount": float(ref.amount)} for ref in spt.ntpn_list
            ],
            "tanda_tangan_digital": spt.tanda_tangan_digital,
            "idempotency_key": spt.idempotency_key,
        }
        response = await self._coretax.submit_spt_pph21(payload)

        if response.get("success"):
            spt.status = "APPROVED"
            await self._tax_repo.save_spt_pph21(spt)
            if self._uow:
                await self._uow.commit()

            self._stats["spt_submitted"] += 1
            return CoretaxSubmissionResponse(
                success=True,
                submission_id=spt.id,
                status="APPROVED",
                message="SPT PPh 21 submitted",
                timestamp=datetime.now(UTC),
            )
        else:
            self._stats["errors"] += 1
            raise CoretaxSubmissionError(f"SPT PPh 21 failed: {response.get('message')}")

    # ========================================================================
    # SPT Tahunan Badan
    # ========================================================================

    async def submit_spt_tahunan_badan(
        self, spt: SPTTahunanBadanRequest, user_id: UUID
    ) -> CoretaxSubmissionResponse:
        """Submit SPT Tahunan Badan (1771) to Coretax."""
        payload = {
            "id": str(spt.id),
            "npwp": spt.npwp_wajib_pajak.value,
            "tahun_pajak": spt.tahun_pajak.tahun,
            "penghasilan_neto_fiskal": float(spt.penghasilan_neto_fiskal),
            "kompensasi_kerugian": float(spt.kompensasi_kerugian),
            "penghasilan_kena_pajak": float(spt.penghasilan_kena_pajak),
            "pph_terutang": float(spt.pph_terutang),
            "kredit_pajak": float(spt.kredit_pajak),
            "pph_kurang_bayar": float(spt.pph_kurang_bayar),
            "ntpn_kurang_bayar": spt.ntpn_kurang_bayar.value if spt.ntpn_kurang_bayar else None,
            "lampiran_khusus": spt.lampiran_khusus,
        }
        response = await self._coretax.submit_spt_tahunan(payload)

        if response.get("success"):
            spt.status = "APPROVED"
            await self._tax_repo.save_spt_tahunan(spt)
            if self._uow:
                await self._uow.commit()

            self._stats["spt_submitted"] += 1
            return CoretaxSubmissionResponse(
                success=True,
                submission_id=spt.id,
                status="APPROVED",
                message="SPT Tahunan submitted",
                timestamp=datetime.now(UTC),
            )
        else:
            self._stats["errors"] += 1
            raise CoretaxSubmissionError(f"SPT Tahunan failed: {response.get('message')}")

    # ========================================================================
    # NTPN Validation
    # ========================================================================

    async def validate_ntpn(self, ntpn: str, amount: Decimal, payment_date: date) -> bool:
        """Validate NTPN with Coretax."""
        response = await self._coretax.validate_ntpn(ntpn, float(amount), payment_date.isoformat())
        return response.get("valid", False)

    # ========================================================================
    # Health Check Dashboard
    # ========================================================================

    async def get_health_dashboard(self, legal_entity_id: UUID) -> dict[str, Any]:
        """Get Coretax submission health status."""
        pending_faktur = await self._tax_repo.count_faktur_by_status(legal_entity_id, "DRAFT")
        pending_spt_ppn = await self._tax_repo.count_spt_by_status(legal_entity_id, "DRAFT", "PPN")
        pending_spt_pph21 = await self._tax_repo.count_spt_by_status(
            legal_entity_id, "DRAFT", "PPH21"
        )

        nsfp_info = await self._tax_repo.get_current_nsfp_range(legal_entity_id)
        remaining_nsfp = 0
        if nsfp_info:
            remaining_nsfp = max(0, int(nsfp_info.end) - int(nsfp_info.current))

        return {
            "legal_entity_id": str(legal_entity_id),
            "pending_faktur_keluaran": pending_faktur,
            "pending_spt_ppn": pending_spt_ppn,
            "pending_spt_pph21": pending_spt_pph21,
            "remaining_nsfp": remaining_nsfp,
            "coretax_api_status": "UP" if await self._coretax.health_check() else "DOWN",
            "last_submission": await self._tax_repo.get_last_submission_date(legal_entity_id),
        }

    def get_stats(self) -> dict[str, int]:
        return self._stats.copy()


# ============================================================================
# Factory
# ============================================================================


async def create_coretax_service(
    coretax_client: CoretaxPort,
    tax_repo: TaxRepositoryPort,
    uow: UnitOfWorkPort | None = None,
    event_publisher: EventPublisherPort | None = None,
) -> CoretaxService:
    return CoretaxService(coretax_client, tax_repo, uow, event_publisher)


__all__ = [
    "CoretaxAuthenticationError",
    "CoretaxService",
    "CoretaxServiceError",
    "CoretaxSubmissionError",
    "FakturPajakNotFoundError",
    "NSFPExhaustedError",
    "create_coretax_service",
]
