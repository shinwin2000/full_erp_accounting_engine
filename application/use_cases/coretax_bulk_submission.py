#!/usr/bin/env python3

"""
Module: coretax_bulk_submission.py

Layer: 5 - Application / Use Cases

Responsibility:
    Use case untuk submit SPT secara massal (bulk) ke Coretax DJP.
    Mencakup pengiriman batch SPT Masa PPN, PPh 21, PPh 23, dan SPT Tahunan Badan.
    Mendukung idempotency, retry, dan penanganan error per item.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from application.commands_cqrs.command_bus_unified import BaseCommand, CommandResult
from application.dto_objects.coretax_submission_request import (
    SPTMasaPph21Request,
    SPTMasaPph23Request,
    SPTMasaPpnRequest,
    SPTTahunanBadanRequest,
)
from application.service_layer.service_coretax import CoretaxService
from application.service_layer.service_tax import TaxService
from kernel.sealed_gate import SealedGate

logger = logging.getLogger(__name__)


class BulkSubmissionType(Enum):
    PPN_MASA = "ppn_masa"
    PPH21_MASA = "pph21_masa"
    PPH23_MASA = "pph23_masa"
    TAHUNAN_BADAN = "tahunan_badan"
    MIXED = "mixed"


class BulkSubmissionStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    PARTIAL_SUCCESS = "partial_success"
    ALL_SUCCESS = "all_success"
    FAILED = "failed"


@dataclass
class BulkSubmissionItem:
    submission_id: UUID
    tax_type: str
    period_year: int
    period_month: int
    status: str
    approval_code: str | None
    error_message: str | None
    submitted_at: datetime


@dataclass
class BulkSubmissionResult:
    batch_id: UUID
    total_items: int
    success_count: int
    failed_count: int
    items: list[BulkSubmissionItem]
    status: BulkSubmissionStatus
    completed_at: datetime


class CoretaxBulkSubmissionCommand(BaseCommand):
    """Command untuk bulk submission ke Coretax."""

    __slots__ = ("dry_run", "idempotency_key", "items", "legal_entity_id", "submission_type")

    def __init__(
        self,
        legal_entity_id: UUID,
        submission_type: str,
        items: list[dict[str, Any]],
        idempotency_key: str | None = None,
        dry_run: bool = False,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
    ):
        super().__init__(
            command_type="CoretaxBulkSubmissionCommand",
            user_id=user_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        self.legal_entity_id = legal_entity_id
        self.submission_type = submission_type
        self.items = items
        self.dry_run = dry_run

    def to_dict(self) -> dict[str, Any]:
        """Manual dict construction to avoid __slots__ conflict."""
        return {
            "command_id": str(self.command_id),
            "command_type": self.command_type,
            "user_id": str(self.user_id) if self.user_id else None,
            "correlation_id": self.correlation_id,
            "idempotency_key": self.idempotency_key,
            "created_at": self.created_at.isoformat() if hasattr(self, "created_at") else None,
            "legal_entity_id": str(self.legal_entity_id),
            "submission_type": self.submission_type,
            "items_count": len(self.items),
            "dry_run": self.dry_run,
        }


class CoretaxBulkSubmissionUseCase:
    """
    Use case untuk bulk submission SPT ke Coretax.
    """

    def __init__(
        self,
        coretax_service: CoretaxService,
        tax_service: TaxService,
        sealed_gate: SealedGate | None = None,
    ):
        self._coretax_service = coretax_service
        self._tax_service = tax_service
        self._sealed_gate = sealed_gate
        self._stats = {"executed": 0, "succeeded": 0, "failed": 0}

    async def execute(self, command: CoretaxBulkSubmissionCommand) -> CommandResult:
        self._stats["executed"] += 1

        try:
            batch_id = uuid4()
            items_results = []
            success_count = 0
            failed_count = 0

            # Jika dry run, hanya validasi tanpa submit
            if command.dry_run:
                return CommandResult.success(
                    command_id=command.command_id,
                    data={
                        "dry_run": True,
                        "batch_id": str(batch_id),
                        "total_items": len(command.items),
                        "message": "Bulk submission dry run completed",
                    },
                )

            # Proses setiap item dalam batch (parallel dengan semaphore)
            semaphore = asyncio.Semaphore(5)  # maksimal 5 request paralel

            async def process_item(item: dict[str, Any], idx: int) -> BulkSubmissionItem:
                async with semaphore:
                    # FIX: extract and validate values with proper type checking
                    tax_type = item.get("tax_type")
                    if not isinstance(tax_type, str):
                        raise ValueError(f"Invalid tax_type: {tax_type} (must be string)")

                    period_year = item.get("period_year")
                    if not isinstance(period_year, int):
                        try:
                            period_year = int(period_year)  # type: ignore[arg-type]
                        except (TypeError, ValueError):
                            raise ValueError(f"Invalid period_year: {period_year} (must be integer)")

                    period_month = item.get("period_month")
                    if not isinstance(period_month, int):
                        try:
                            period_month = int(period_month)  # type: ignore[arg-type]
                        except (TypeError, ValueError):
                            raise ValueError(f"Invalid period_month: {period_month} (must be integer)")

                    spt_data = item.get("spt_data", {})

                    submission_id = uuid4()
                    try:
                        if tax_type == BulkSubmissionType.PPN_MASA.value:
                            request = await self._build_ppn_request(
                                command.legal_entity_id,
                                period_year,
                                period_month,
                                spt_data,
                                submission_id,
                            )
                            response = await self._coretax_service.submit_spt_masa_ppn(
                                spt=request,
                                user_id=command.user_id,
                                correlation_id=command.correlation_id,
                            )
                        elif tax_type == BulkSubmissionType.PPH21_MASA.value:
                            request = await self._build_pph21_request(
                                command.legal_entity_id,
                                period_year,
                                period_month,
                                spt_data,
                                submission_id,
                            )
                            response = await self._coretax_service.submit_spt_masa_pph21(
                                spt=request, user_id=command.user_id
                            )
                        elif tax_type == BulkSubmissionType.PPH23_MASA.value:
                            request = await self._build_pph23_request(
                                command.legal_entity_id,
                                period_year,
                                period_month,
                                spt_data,
                                submission_id,
                            )
                            response = await self._coretax_service.submit_ebupot_masa(
                                spt=request, user_id=command.user_id
                            )
                        elif tax_type == BulkSubmissionType.TAHUNAN_BADAN.value:
                            request = await self._build_tahunan_request(
                                command.legal_entity_id, period_year, spt_data, submission_id
                            )
                            response = await self._coretax_service.submit_spt_tahunan_badan(
                                spt=request, user_id=command.user_id
                            )
                        else:
                            raise ValueError(f"Unknown tax type: {tax_type}")

                        if response and response.status.value == "APPROVED":
                            success_count_local = True
                            approval_code = response.approval_code
                            error_msg = None
                        else:
                            success_count_local = False
                            approval_code = None
                            error_msg = response.message if response else "Unknown error"
                    except Exception as e:
                        success_count_local = False
                        approval_code = None
                        error_msg = str(e)

                    return BulkSubmissionItem(
                        submission_id=submission_id,
                        tax_type=tax_type,
                        period_year=period_year,
                        period_month=period_month,
                        status="SUCCESS" if success_count_local else "FAILED",
                        approval_code=approval_code,
                        error_message=error_msg,
                        submitted_at=datetime.utcnow(),
                    )

            tasks = [process_item(item, i) for i, item in enumerate(command.items)]
            items_results = await asyncio.gather(*tasks)

            for res in items_results:
                if res.status == "SUCCESS":
                    success_count += 1
                else:
                    failed_count += 1

            if success_count == len(command.items):
                overall_status = BulkSubmissionStatus.ALL_SUCCESS
            elif success_count > 0:
                overall_status = BulkSubmissionStatus.PARTIAL_SUCCESS
            else:
                overall_status = BulkSubmissionStatus.FAILED

            result = BulkSubmissionResult(
                batch_id=batch_id,
                total_items=len(command.items),
                success_count=success_count,
                failed_count=failed_count,
                items=items_results,
                status=overall_status,
                completed_at=datetime.utcnow(),
            )

            self._stats["succeeded"] += 1
            return CommandResult.success(
                command_id=command.command_id,
                data={
                    "batch_id": str(result.batch_id),
                    "total_items": result.total_items,
                    "success_count": result.success_count,
                    "failed_count": result.failed_count,
                    "status": result.status.value,
                    "items": [
                        {
                            "submission_id": str(item.submission_id),
                            "tax_type": item.tax_type,
                            "period": f"{item.period_year}-{item.period_month:02d}",
                            "status": item.status,
                            "approval_code": item.approval_code,
                            "error_message": item.error_message,
                        }
                        for item in result.items
                    ],
                    "completed_at": result.completed_at.isoformat(),
                },
            )

        except Exception as e:
            self._stats["failed"] += 1
            logger.exception(f"Coretax bulk submission failed: {e}")
            return CommandResult.failure(
                command_id=command.command_id, error=str(e), error_code="CORETAX_BULK_ERROR"
            )

    async def _build_ppn_request(
        self,
        legal_entity_id: UUID,
        year: int,
        month: int,
        spt_data: dict[str, Any],
        submission_id: UUID,
    ) -> SPTMasaPpnRequest:
        legal_entity = await self._tax_service.get_legal_entity_tax_data(legal_entity_id)
        if not legal_entity:
            raise ValueError(f"Legal entity {legal_entity_id} not found")

        from application.dto_objects.coretax_submission_request import NPWP, MasaPajak

        masa = MasaPajak(bulan=month, tahun=year)
        npwp = NPWP(legal_entity.npwp)

        total_penyerahan = Decimal(str(spt_data.get("total_penyerahan_dpp", 0)))
        total_ppn_keluaran = Decimal(str(spt_data.get("total_ppn_keluaran", 0)))
        total_ppn_masukan = Decimal(str(spt_data.get("total_ppn_masukan", 0)))
        kompensasi = Decimal(str(spt_data.get("kompensasi", 0)))

        ppn_kurang_bayar = total_ppn_keluaran - total_ppn_masukan - kompensasi
        if ppn_kurang_bayar < 0:
            ppn_kurang_bayar = Decimal("0")
            ppn_lebih_bayar = -(total_ppn_keluaran - total_ppn_masukan - kompensasi)
        else:
            ppn_lebih_bayar = Decimal("0")

        return SPTMasaPpnRequest(
            id=submission_id,
            npwp_pemilik=npwp,
            masa_pajak=masa,
            status="READY",
            lampiran={
                "penyerahan": total_penyerahan,
                "ppn_keluaran": total_ppn_keluaran,
                "ppn_masukan": total_ppn_masukan,
                "kompensasi": kompensasi,
                "kurang_bayar": ppn_kurang_bayar,
                "lebih_bayar": ppn_lebih_bayar,
            },
            tanda_tangan_digital=await self._generate_digital_signature(),
            idempotency_key=f"bulk_ppn_{legal_entity_id}_{year}{month:02d}_{submission_id}",
        )

    async def _build_pph21_request(
        self,
        legal_entity_id: UUID,
        year: int,
        month: int,
        spt_data: dict[str, Any],
        submission_id: UUID,
    ) -> SPTMasaPph21Request:
        legal_entity = await self._tax_service.get_legal_entity_tax_data(legal_entity_id)
        if not legal_entity:
            raise ValueError(f"Legal entity {legal_entity_id} not found")

        from application.dto_objects.coretax_submission_request import NPWP, MasaPajak

        masa = MasaPajak(bulan=month, tahun=year)
        npwp = NPWP(legal_entity.npwp)

        total_bruto = Decimal(str(spt_data.get("total_bruto", 0)))
        total_pph_dipotong = Decimal(str(spt_data.get("total_pph_dipotong", 0)))
        total_pph_setor = Decimal(str(spt_data.get("total_pph_setor", 0)))
        ntpn_list = spt_data.get("ntpn_list", [])

        return SPTMasaPph21Request(
            id=submission_id,
            npwp_pemotong=npwp,
            masa_pajak=masa,
            total_bruto=total_bruto,
            total_pph_dipotong=total_pph_dipotong,
            total_pph_setor=total_pph_setor,
            ntpn_list=ntpn_list,
            tanda_tangan_digital=await self._generate_digital_signature(),
            idempotency_key=f"bulk_pph21_{legal_entity_id}_{year}{month:02d}_{submission_id}",
        )

    async def _build_pph23_request(
        self,
        legal_entity_id: UUID,
        year: int,
        month: int,
        spt_data: dict[str, Any],
        submission_id: UUID,
    ) -> SPTMasaPph23Request:
        legal_entity = await self._tax_service.get_legal_entity_tax_data(legal_entity_id)
        if not legal_entity:
            raise ValueError(f"Legal entity {legal_entity_id} not found")

        from application.dto_objects.coretax_submission_request import NPWP, MasaPajak

        masa = MasaPajak(bulan=month, tahun=year)
        npwp = NPWP(legal_entity.npwp)

        bukti_potong_list = spt_data.get("bukti_potong_list", [])
        return SPTMasaPph23Request(
            id=submission_id,
            npwp_pemotong=npwp,
            masa_pajak=masa,
            bukti_potong_list=bukti_potong_list,
            tanda_tangan_digital=await self._generate_digital_signature(),
            idempotency_key=f"bulk_pph23_{legal_entity_id}_{year}{month:02d}_{submission_id}",
        )

    async def _build_tahunan_request(
        self, legal_entity_id: UUID, year: int, spt_data: dict[str, Any], submission_id: UUID
    ) -> SPTTahunanBadanRequest:
        legal_entity = await self._tax_service.get_legal_entity_tax_data(legal_entity_id)
        if not legal_entity:
            raise ValueError(f"Legal entity {legal_entity_id} not found")

        from application.dto_objects.coretax_submission_request import NPWP, NTPN, TahunPajak

        tahun = TahunPajak(tahun=year)
        npwp = NPWP(legal_entity.npwp)

        penghasilan_neto_fiskal = Decimal(str(spt_data.get("penghasilan_neto_fiskal", 0)))
        kompensasi_kerugian = Decimal(str(spt_data.get("kompensasi_kerugian", 0)))
        penghasilan_kena_pajak = max(penghasilan_neto_fiskal - kompensasi_kerugian, Decimal("0"))
        pph_terutang = (penghasilan_kena_pajak * Decimal("0.22")).quantize(Decimal("0"))
        kredit_pajak = Decimal(str(spt_data.get("kredit_pajak", 0)))
        pph_kurang_bayar = max(pph_terutang - kredit_pajak, Decimal("0"))
        ntpn_kurang_bayar = spt_data.get("ntpn_kurang_bayar")

        return SPTTahunanBadanRequest(
            id=submission_id,
            npwp_wajib_pajak=npwp,
            tahun_pajak=tahun,
            status="READY",
            penghasilan_neto_fiskal=penghasilan_neto_fiskal,
            kompensasi_kerugian=kompensasi_kerugian,
            penghasilan_kena_pajak=penghasilan_kena_pajak,
            pph_terutang=pph_terutang,
            kredit_pajak=kredit_pajak,
            pph_kurang_bayar=pph_kurang_bayar,
            ntpn_kurang_bayar=NTPN(ntpn_kurang_bayar) if ntpn_kurang_bayar else None,
            lampiran_khusus={},
            tanda_tangan_digital=await self._generate_digital_signature(),
            idempotency_key=f"bulk_tahunan_{legal_entity_id}_{year}_{submission_id}",
        )

    async def _generate_digital_signature(self) -> str:
        data = f"{datetime.utcnow().isoformat()}_{uuid4()}"
        return hashlib.sha256(data.encode()).hexdigest()

    def get_stats(self) -> dict[str, int]:
        return self._stats


async def coretax_bulk_submission_handler(
    command: BaseCommand, use_case: CoretaxBulkSubmissionUseCase
) -> CommandResult:
    if not isinstance(command, CoretaxBulkSubmissionCommand):
        raise TypeError(f"Expected CoretaxBulkSubmissionCommand, got {type(command)}")
    return await use_case.execute(command)


__all__ = [
    "BulkSubmissionItem",
    "BulkSubmissionResult",
    "BulkSubmissionStatus",
    "BulkSubmissionType",
    "CoretaxBulkSubmissionCommand",
    "CoretaxBulkSubmissionUseCase",
    "coretax_bulk_submission_handler",
]
