#!/usr/bin/env python3
"""
Module: pph_withholding_summary.py
Layer: Projections (Tax)
Responsibility: Membangun read model ringkasan pemotongan PPh (Pajak Penghasilan)
                untuk setiap masa pajak. Menampilkan PPh 21, PPh 23, PPh 26, PPh 4(2),
                dan PPh Final lainnya. Digunakan untuk pengisian SPT Masa PPh dan
                pelaporan ke DJP.
Dependencies:
- asyncio, logging, datetime, decimal
- sqlalchemy.ext.asyncio
- infrastructure.database.session_factory_sqlalchemy
- infrastructure.telemetry.structured_json_logging
- infrastructure.telemetry.alert_manager_router
Audit: Ringkasan pemotongan PPh digunakan untuk compliance dan pelaporan.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, ClassVar
from uuid import UUID, uuid4

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    delete,
    insert,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeMeta, declarative_base

# Internal dependencies (hanya untuk session factory, karena kita sudah buat tabel sendiri)
from infrastructure.database.session_factory_sqlalchemy import get_session_factory
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# DEFINE OUR OWN TABLES (with explicit String lengths and PGUUID)
# ============================================================================

Base: DeclarativeMeta = declarative_base()


class TaxTransactionTable(Base):
    """Tabel transaksi pajak (redefined locally with explicit String lengths)."""

    __tablename__: ClassVar[str] = "tax_transaction"
    __table_args__: ClassVar[dict] = {"schema": "public"}

    id = Column(PGUUID(as_uuid=True), primary_key=True)
    legal_entity_id = Column(PGUUID(as_uuid=True), nullable=False)
    reference_type = Column(String(50), nullable=False)
    tax_type = Column(String(20), nullable=False)
    tax_period_year = Column(Integer, nullable=False)
    tax_period_month = Column(Integer, nullable=False)
    ntpn = Column(String(16), nullable=True)
    payment_date = Column(Date, nullable=True)
    spt_number = Column(String(50), nullable=True)
    status = Column(String(20), nullable=False, default="draft")
    created_at = Column(DateTime(timezone=True), nullable=False)


class CoretaxBupotTable(Base):
    """Tabel bukti potong Coretax (redefined locally)."""

    __tablename__: ClassVar[str] = "coretax_bupot"
    __table_args__: ClassVar[dict] = {"schema": "public"}

    id = Column(PGUUID(as_uuid=True), primary_key=True)
    npwp_pemotong = Column(String(20), nullable=False)
    npwp_penerima = Column(String(20), nullable=False)
    nama_penerima = Column(String(200), nullable=False)
    jenis_pajak = Column(String(10), nullable=False)
    masa_pajak = Column(Integer, nullable=False)
    tahun_pajak = Column(Integer, nullable=False)
    bupot_number = Column(String(50), nullable=True)
    dasar_pemotongan = Column(Numeric(20, 2), nullable=False)
    tarif = Column(Numeric(10, 2), nullable=False)
    pph_dipotong = Column(Numeric(20, 2), nullable=False)
    invoice_reference = Column(String(100), nullable=True)
    status = Column(String(20), nullable=False, default="draft")
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)


class PPhWithholdingSummaryTable(Base):
    __tablename__ = "pph_withholding_summary"
    __table_args__ = (
        Index("idx_pph_summary_npwp", "npwp_pemotong"),
        Index("idx_pph_summary_period", "tahun_pajak", "masa_pajak", "pph_type"),
        Index("idx_pph_summary_legal_entity", "legal_entity_id"),
        {"schema": "projections"},
    )
    id = Column(PGUUID(as_uuid=True), primary_key=True)
    npwp_pemotong = Column(String(20), nullable=False)
    pph_type = Column(String(10), nullable=False)
    masa_pajak = Column(Integer, nullable=False)
    tahun_pajak = Column(Integer, nullable=False)
    legal_entity_id = Column(PGUUID(as_uuid=True), nullable=False)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    total_dpp = Column(Numeric(20, 2), nullable=False, default=0)
    total_pph_dipotong = Column(Numeric(20, 2), nullable=False, default=0)
    kompensasi = Column(Numeric(20, 2), nullable=False, default=0)
    kurang_bayar = Column(Numeric(20, 2), nullable=False, default=0)
    lebih_bayar = Column(Numeric(20, 2), nullable=False, default=0)
    payment_status = Column(String(20), nullable=False, default="unpaid")
    ntpn = Column(String(16), nullable=True)
    payment_date = Column(Date, nullable=True)
    spt_number = Column(String(50), nullable=True)
    spt_status = Column(String(20), nullable=False, default="draft")
    bupot_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=True)


# ============================================================================
# CONSTANTS
# ============================================================================

PROJECTION_NAME = "pph_withholding_summary"

# Jenis PPh
PPh_TYPES = {
    "21": "PPh Pasal 21",
    "22": "PPh Pasal 22",
    "23": "PPh Pasal 23",
    "26": "PPh Pasal 26",
    "4_2": "PPh Pasal 4 ayat 2",
    "25": "PPh Pasal 25 (angsuran)",
    "29": "PPh Pasal 29 (kurang bayar)",
    "final": "PPh Final",
}

# Status pembayaran
PAYMENT_STATUS_UNPAID = "unpaid"
PAYMENT_STATUS_PAID = "paid"
PAYMENT_STATUS_OVERPAID = "overpaid"

# Status SPT
SPT_STATUS_DRAFT = "draft"
SPT_STATUS_SUBMITTED = "submitted"
SPT_STATUS_APPROVED = "approved"

# ============================================================================
# EXCEPTIONS
# ============================================================================


class PPhWithholdingError(Exception):
    """Base exception untuk PPh withholding summary projection."""

    pass


# ============================================================================
# PPH WITHHOLDING SUMMARY PROJECTION
# ============================================================================


class PPhWithholdingSummary:
    """
    Read model ringkasan pemotongan PPh per masa pajak.
    """

    def __init__(self):
        self._session_factory = None

    async def _get_session(self) -> AsyncSession:
        if self._session_factory is None:
            self._session_factory = await get_session_factory()
        return self._session_factory.get_session()

    async def compute_withholding_summary(
        self,
        npwp_pemotong: str,
        masa_pajak: int,
        tahun_pajak: int,
        legal_entity_id: UUID,
        pph_type: str = "23",
    ) -> dict[str, Any]:
        """
        Menghitung ringkasan pemotongan PPh untuk satu masa pajak.
        """
        async with await self._get_session() as session:
            start_date = date(tahun_pajak, masa_pajak, 1)
            if masa_pajak == 12:
                end_date = date(tahun_pajak + 1, 1, 1) - timedelta(days=1)
            else:
                end_date = date(tahun_pajak, masa_pajak + 1, 1) - timedelta(days=1)

            bupot_stmt = select(CoretaxBupotTable).where(
                CoretaxBupotTable.npwp_pemotong == npwp_pemotong,
                CoretaxBupotTable.jenis_pajak == pph_type,
                CoretaxBupotTable.masa_pajak == masa_pajak,
                CoretaxBupotTable.tahun_pajak == tahun_pajak,
                CoretaxBupotTable.status.in_(["approved", "submitted"]),
                CoretaxBupotTable.deleted_at.is_(None),
            )
            bupot_result = await session.execute(bupot_stmt)
            bupots = bupot_result.scalars().all()

            total_pph = Decimal(0)
            total_dpp = Decimal(0)
            bupot_list = []

            for bupot in bupots:
                total_pph += bupot.pph_dipotong
                total_dpp += bupot.dasar_pemotongan
                bupot_list.append(
                    {
                        "bupot_id": str(bupot.id),
                        "bupot_number": bupot.bupot_number,
                        "npwp_penerima": bupot.npwp_penerima,
                        "nama_penerima": bupot.nama_penerima,
                        "dasar_pemotongan": float(bupot.dasar_pemotongan),
                        "tarif": float(bupot.tarif),
                        "pph_dipotong": float(bupot.pph_dipotong),
                        "invoice_reference": bupot.invoice_reference,
                    }
                )

            kompensasi = Decimal(0)
            if masa_pajak > 1:
                prev_summary = await self.get_summary(
                    npwp_pemotong,
                    masa_pajak - 1,
                    tahun_pajak,
                    legal_entity_id,
                    pph_type,
                    session=session,
                )
                if prev_summary and prev_summary.get("lebih_bayar", 0) > 0:
                    kompensasi = Decimal(str(prev_summary["lebih_bayar"]))

            payment_stmt = (
                select(TaxTransactionTable)
                .where(
                    TaxTransactionTable.reference_type == "spt_pph",
                    TaxTransactionTable.tax_period_year == tahun_pajak,
                    TaxTransactionTable.tax_period_month == masa_pajak,
                    TaxTransactionTable.tax_type == f"pph{pph_type}",
                    TaxTransactionTable.legal_entity_id == legal_entity_id,
                )
                .order_by(TaxTransactionTable.created_at.desc())
                .limit(1)
            )
            payment_result = await session.execute(payment_stmt)
            payment = payment_result.scalar_one_or_none()

            kurang_bayar = max(Decimal(0), total_pph - kompensasi)
            lebih_bayar = max(Decimal(0), kompensasi - total_pph)

            spt_stmt = (
                select(TaxTransactionTable)
                .where(
                    TaxTransactionTable.reference_type == "spt_pph",
                    TaxTransactionTable.tax_period_year == tahun_pajak,
                    TaxTransactionTable.tax_period_month == masa_pajak,
                    TaxTransactionTable.tax_type == f"pph{pph_type}",
                    TaxTransactionTable.spt_number.isnot(None),
                )
                .order_by(TaxTransactionTable.created_at.desc())
                .limit(1)
            )
            spt_result = await session.execute(spt_stmt)
            spt = spt_result.scalar_one_or_none()

            return {
                "npwp_pemotong": npwp_pemotong,
                "pph_type": pph_type,
                "pph_type_name": PPh_TYPES.get(pph_type, "PPh Lainnya"),
                "masa_pajak": masa_pajak,
                "tahun_pajak": tahun_pajak,
                "legal_entity_id": str(legal_entity_id),
                "period_start": start_date.isoformat(),
                "period_end": end_date.isoformat(),
                "total_dpp": float(total_dpp),
                "total_pph_dipotong": float(total_pph),
                "kompensasi": float(kompensasi),
                "kurang_bayar": float(kurang_bayar),
                "lebih_bayar": float(lebih_bayar),
                "payment_status": PAYMENT_STATUS_PAID
                if payment and payment.ntpn
                else PAYMENT_STATUS_UNPAID,
                "ntpn": payment.ntpn if payment else None,
                "payment_date": payment.payment_date.isoformat()
                if payment and payment.payment_date
                else None,
                "spt_number": spt.spt_number if spt else None,
                "spt_status": spt.status if spt else SPT_STATUS_DRAFT,
                "bupot_count": len(bupot_list),
                "bupots": bupot_list[:100],
                "computed_at": datetime.now(UTC).isoformat(),
            }

    async def save_summary(self, summary_data: dict[str, Any]) -> None:
        """
        Menyimpan ringkasan PPh ke tabel materialized.
        """
        async with await self._get_session() as session, session.begin():
            await session.execute(
                delete(PPhWithholdingSummaryTable).where(
                    PPhWithholdingSummaryTable.npwp_pemotong == summary_data["npwp_pemotong"],
                    PPhWithholdingSummaryTable.pph_type == summary_data["pph_type"],
                    PPhWithholdingSummaryTable.masa_pajak == summary_data["masa_pajak"],
                    PPhWithholdingSummaryTable.tahun_pajak == summary_data["tahun_pajak"],
                    PPhWithholdingSummaryTable.legal_entity_id
                    == UUID(summary_data["legal_entity_id"]),
                )
            )

            stmt = insert(PPhWithholdingSummaryTable).values(
                id=uuid4(),
                npwp_pemotong=summary_data["npwp_pemotong"],
                pph_type=summary_data["pph_type"],
                masa_pajak=summary_data["masa_pajak"],
                tahun_pajak=summary_data["tahun_pajak"],
                legal_entity_id=UUID(summary_data["legal_entity_id"]),
                period_start=date.fromisoformat(summary_data["period_start"]),
                period_end=date.fromisoformat(summary_data["period_end"]),
                total_dpp=Decimal(str(summary_data["total_dpp"])),
                total_pph_dipotong=Decimal(str(summary_data["total_pph_dipotong"])),
                kompensasi=Decimal(str(summary_data["kompensasi"])),
                kurang_bayar=Decimal(str(summary_data["kurang_bayar"])),
                lebih_bayar=Decimal(str(summary_data["lebih_bayar"])),
                payment_status=summary_data["payment_status"],
                ntpn=summary_data.get("ntpn"),
                payment_date=date.fromisoformat(summary_data["payment_date"])
                if summary_data.get("payment_date")
                else None,
                spt_number=summary_data.get("spt_number"),
                spt_status=summary_data["spt_status"],
                bupot_count=summary_data["bupot_count"],
                created_at=datetime.now(UTC),
            )
            await session.execute(stmt)

    async def get_summary(
        self,
        npwp_pemotong: str,
        masa_pajak: int,
        tahun_pajak: int,
        legal_entity_id: UUID,
        pph_type: str = "23",
        session: AsyncSession | None = None,
    ) -> dict | None:
        """
        Mendapatkan ringkasan yang sudah tersimpan.
        """
        is_internal_session = False
        if session is None:
            session = await self._get_session()
            is_internal_session = True

        try:
            stmt = select(PPhWithholdingSummaryTable).where(
                PPhWithholdingSummaryTable.npwp_pemotong == npwp_pemotong,
                PPhWithholdingSummaryTable.pph_type == pph_type,
                PPhWithholdingSummaryTable.masa_pajak == masa_pajak,
                PPhWithholdingSummaryTable.tahun_pajak == tahun_pajak,
                PPhWithholdingSummaryTable.legal_entity_id == legal_entity_id,
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if not row:
                return None
            return {
                "npwp_pemotong": row.npwp_pemotong,
                "pph_type": row.pph_type,
                "masa_pajak": row.masa_pajak,
                "tahun_pajak": row.tahun_pajak,
                "period_start": row.period_start.isoformat(),
                "period_end": row.period_end.isoformat(),
                "total_dpp": float(row.total_dpp),
                "total_pph_dipotong": float(row.total_pph_dipotong),
                "kompensasi": float(row.kompensasi),
                "kurang_bayar": float(row.kurang_bayar),
                "lebih_bayar": float(row.lebih_bayar),
                "payment_status": row.payment_status,
                "ntpn": row.ntpn,
                "payment_date": row.payment_date.isoformat() if row.payment_date else None,
                "spt_number": row.spt_number,
                "spt_status": row.spt_status,
                "bupot_count": row.bupot_count,
                "created_at": row.created_at.isoformat(),
            }
        finally:
            if is_internal_session:
                await session.close()

    async def generate_all_periods(
        self, npwp_pemotong: str, legal_entity_id: UUID, tahun_pajak: int, pph_type: str = "23"
    ) -> list[dict]:
        summaries = []
        for masa in range(1, 13):
            summary = await self.compute_withholding_summary(
                npwp_pemotong, masa, tahun_pajak, legal_entity_id, pph_type
            )
            await self.save_summary(summary)
            summaries.append(summary)
        return summaries

    async def update_payment(
        self,
        npwp_pemotong: str,
        masa_pajak: int,
        tahun_pajak: int,
        legal_entity_id: UUID,
        pph_type: str,
        ntpn: str,
        payment_date: date,
    ) -> None:
        async with await self._get_session() as session:
            async with session.begin():
                stmt = (
                    update(PPhWithholdingSummaryTable)
                    .where(
                        PPhWithholdingSummaryTable.npwp_pemotong == npwp_pemotong,
                        PPhWithholdingSummaryTable.pph_type == pph_type,
                        PPhWithholdingSummaryTable.masa_pajak == masa_pajak,
                        PPhWithholdingSummaryTable.tahun_pajak == tahun_pajak,
                        PPhWithholdingSummaryTable.legal_entity_id == legal_entity_id,
                    )
                    .values(
                        payment_status=PAYMENT_STATUS_PAID,
                        ntpn=ntpn,
                        payment_date=payment_date,
                        updated_at=datetime.now(UTC),
                    )
                )
                await session.execute(stmt)
            logger.info(
                f"PPh payment recorded for {npwp_pemotong} {pph_type} masa {masa_pajak}/{tahun_pajak}"
            )

    async def mark_spt_submitted(
        self,
        npwp_pemotong: str,
        masa_pajak: int,
        tahun_pajak: int,
        legal_entity_id: UUID,
        pph_type: str,
        spt_number: str,
    ) -> None:
        async with await self._get_session() as session:
            async with session.begin():
                stmt = (
                    update(PPhWithholdingSummaryTable)
                    .where(
                        PPhWithholdingSummaryTable.npwp_pemotong == npwp_pemotong,
                        PPhWithholdingSummaryTable.pph_type == pph_type,
                        PPhWithholdingSummaryTable.masa_pajak == masa_pajak,
                        PPhWithholdingSummaryTable.tahun_pajak == tahun_pajak,
                        PPhWithholdingSummaryTable.legal_entity_id == legal_entity_id,
                    )
                    .values(
                        spt_status=SPT_STATUS_SUBMITTED,
                        spt_number=spt_number,
                        updated_at=datetime.now(UTC),
                    )
                )
                await session.execute(stmt)
            logger.info(
                f"SPT PPh {spt_number} submitted for {npwp_pemotong} {pph_type} masa {masa_pajak}/{tahun_pajak}"
            )

    async def get_ytd_summary(
        self, npwp_pemotong: str, tahun_pajak: int, legal_entity_id: UUID, pph_type: str = "23"
    ) -> dict[str, Any]:
        tasks = [
            self.get_summary(npwp_pemotong, masa, tahun_pajak, legal_entity_id, pph_type)
            for masa in range(1, 13)
        ]
        results = await asyncio.gather(*tasks)

        summaries = []
        total_pph = Decimal(0)
        total_dpp = Decimal(0)

        for summary in results:
            if summary:
                summaries.append(summary)
                total_pph += Decimal(str(summary["total_pph_dipotong"]))
                total_dpp += Decimal(str(summary["total_dpp"]))

        return {
            "npwp_pemotong": npwp_pemotong,
            "pph_type": pph_type,
            "tahun_pajak": tahun_pajak,
            "total_dpp_ytd": float(total_dpp),
            "total_pph_ytd": float(total_pph),
            "summaries": summaries,
        }

    async def rebuild_all(
        self, legal_entity_id: UUID, npwp_pemotong: str, tahun_pajak: int, pph_type: str = "23"
    ) -> dict:
        await self.generate_all_periods(npwp_pemotong, legal_entity_id, tahun_pajak, pph_type)
        return {
            "npwp_pemotong": npwp_pemotong,
            "tahun_pajak": tahun_pajak,
            "pph_type": pph_type,
            "status": "completed",
        }


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_pph_summary: PPhWithholdingSummary | None = None


async def get_pph_summary() -> PPhWithholdingSummary:
    global _pph_summary
    if _pph_summary is None:
        _pph_summary = PPhWithholdingSummary()
    return _pph_summary


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ["PPhWithholdingError", "PPhWithholdingSummary", "get_pph_summary"]
