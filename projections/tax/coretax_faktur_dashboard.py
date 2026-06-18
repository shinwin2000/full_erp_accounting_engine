#!/usr/bin/env python3
"""
Module: coretax_faktur_dashboard.py
Layer: Projections (Tax)
Responsibility: Membangun read model dashboard untuk monitoring faktur pajak
                dari Coretax DJP. Menyediakan ringkasan real-time: jumlah faktur
                keluaran/masukan, status (approved, rejected, pending), total PPN,
                NSFP usage, dan aktivitas harian. Digunakan untuk monitoring compliance
                dan deteksi anomali.
Dependencies:
- asyncio, logging, datetime, decimal
- sqlalchemy.ext.asyncio
- infrastructure.database.session_factory_sqlalchemy
- infrastructure.telemetry.structured_json_logging
- infrastructure.telemetry.alert_manager_router
Audit: Dashboard metrics digunakan untuk monitoring dan alerting.
       Anomali dalam jumlah faktur atau PPN memicu alert.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Column,
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    case,
    delete,
    func,
    insert,
    select,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base

# Internal dependencies (hanya untuk session factory)
from infrastructure.database.session_factory_sqlalchemy import get_session_factory
from infrastructure.telemetry.alert_manager_router import trigger_alert
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# DEFINE OUR OWN TABLES (with explicit String lengths and PGUUID)
# ============================================================================

Base = declarative_base()


class CoretaxFakturTable(Base):
    """Tabel faktur Coretax (redefined locally)."""

    __tablename__ = "coretax_faktur"
    __table_args__ = {"schema": "public"}

    id = Column(PGUUID(as_uuid=True), primary_key=True)
    npwp_penjual = Column(String(20), nullable=False)
    npwp_pembeli = Column(String(20), nullable=False)
    faktur_type = Column(String(10), nullable=False)
    faktur_number = Column(String(30), nullable=False)
    faktur_date = Column(Date, nullable=False)
    dpp = Column(Numeric(20, 2), nullable=False)
    ppn = Column(Numeric(20, 2), nullable=False)
    status = Column(String(20), nullable=False)
    rejection_reason = Column(String(500), nullable=True)
    nama_pembeli = Column(String(200), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)


class CoretaxNSFPTable(Base):
    """Tabel NSFP Coretax."""

    __tablename__ = "coretax_nsfp"
    __table_args__ = {"schema": "public"}

    id = Column(PGUUID(as_uuid=True), primary_key=True)
    npwp = Column(String(20), nullable=False)
    tahun = Column(Integer, nullable=False)
    bulan = Column(Integer, nullable=False)
    start_number = Column(String(20), nullable=False)
    end_number = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)


class CoretaxDashboardSnapshotTable(Base):
    __tablename__ = "coretax_dashboard_snapshot"
    __table_args__ = (
        Index("idx_coretax_dash_npwp", "npwp"),
        Index("idx_coretax_dash_legal_entity", "legal_entity_id"),
        Index("idx_coretax_dash_generated", "generated_at"),
        {"schema": "projections"},
    )
    id = Column(PGUUID(as_uuid=True), primary_key=True)
    npwp = Column(String(20), nullable=False)
    legal_entity_id = Column(PGUUID(as_uuid=True), nullable=False)
    generated_at = Column(DateTime(timezone=True), nullable=False)
    data = Column(JSON, nullable=False)


# ============================================================================
# CONSTANTS
# ============================================================================

PROJECTION_NAME = "coretax_faktur_dashboard"

# Alert thresholds
ALERT_FAKTUR_REJECTED_THRESHOLD = 5  # Alert if >5 rejected in a day
ALERT_PPN_LARGE_TRANSACTION = 100000000  # Rp 100 million
ALERT_NSFP_LOW_THRESHOLD = 20  # Alert if remaining NSFP < 20

# Dashboard refresh interval (seconds)
DASHBOARD_REFRESH_INTERVAL = 300  # 5 minutes

# ============================================================================
# EXCEPTIONS
# ============================================================================


class CoretaxDashboardError(Exception):
    """Base exception untuk Coretax faktur dashboard projection."""

    pass


# ============================================================================
# CORETAX FAKTUR DASHBOARD PROJECTION
# ============================================================================


class CoretaxFakturDashboard:
    """
    Read model dashboard faktur Coretax.

    Fitur:
    - Ringkasan faktur keluaran dan masukan per status
    - Total PPN keluaran dan masukan per periode
    - NSFP quota dan usage monitoring
    - Rejected faktur tracking
    - Daily activity summary
    - Alerting untuk anomali
    """

    def __init__(self):
        self._session_factory = None
        self._dashboard_cache: dict[str, Any] = {}
        self._last_refresh: datetime | None = None

    async def _get_session(self) -> AsyncSession:
        if self._session_factory is None:
            self._session_factory = await get_session_factory()
        return self._session_factory.get_session()

    async def compute_dashboard(
        self, npwp: str, legal_entity_id: UUID, date_range_days: int = 30
    ) -> dict[str, Any]:
        """
        Menghitung dashboard Coretax faktur.

        Args:
            npwp: NPWP PKP
            legal_entity_id: Legal entity ID
            date_range_days: Rentang hari untuk aktivitas terkini (default 30)

        Returns:
            Dashboard data
        """
        async with await self._get_session() as session:
            end_date = date.today()
            start_date = end_date - timedelta(days=date_range_days)

            statuses = ["draft", "submitted", "approved", "rejected", "cancelled", "expired"]

            # 1. Summary by status - Faktur Keluaran (Optimasi: Single Query Group By)
            output_by_status = dict.fromkeys(statuses, 0)
            out_status_stmt = (
                select(CoretaxFakturTable.status, func.count())
                .where(
                    CoretaxFakturTable.npwp_penjual == npwp,
                    CoretaxFakturTable.faktur_type == "keluaran",
                    CoretaxFakturTable.status.in_(statuses),
                    CoretaxFakturTable.deleted_at.is_(None),
                )
                .group_by(CoretaxFakturTable.status)
            )

            out_status_result = await session.execute(out_status_stmt)
            for row in out_status_result:
                output_by_status[row[0]] = row[1]

            # 2. Summary by status - Faktur Masukan (Optimasi: Single Query Group By)
            input_by_status = dict.fromkeys(statuses, 0)
            in_status_stmt = (
                select(CoretaxFakturTable.status, func.count())
                .where(
                    CoretaxFakturTable.npwp_pembeli == npwp,
                    CoretaxFakturTable.faktur_type == "masukan",
                    CoretaxFakturTable.status.in_(statuses),
                    CoretaxFakturTable.deleted_at.is_(None),
                )
                .group_by(CoretaxFakturTable.status)
            )

            in_status_result = await session.execute(in_status_stmt)
            for row in in_status_result:
                input_by_status[row[0]] = row[1]

            # 3. Total PPN - Faktur Keluaran (approved only)
            output_ppn_stmt = select(func.coalesce(func.sum(CoretaxFakturTable.ppn), 0)).where(
                CoretaxFakturTable.npwp_penjual == npwp,
                CoretaxFakturTable.faktur_type == "keluaran",
                CoretaxFakturTable.status == "approved",
                CoretaxFakturTable.deleted_at.is_(None),
            )
            output_ppn_result = await session.execute(output_ppn_stmt)
            total_ppn_keluaran = Decimal(str(output_ppn_result.scalar() or 0))

            # 4. Total PPN - Faktur Masukan (approved only)
            input_ppn_stmt = select(func.coalesce(func.sum(CoretaxFakturTable.ppn), 0)).where(
                CoretaxFakturTable.npwp_pembeli == npwp,
                CoretaxFakturTable.faktur_type == "masukan",
                CoretaxFakturTable.status == "approved",
                CoretaxFakturTable.deleted_at.is_(None),
            )
            input_ppn_result = await session.execute(input_ppn_stmt)
            total_ppn_masukan = Decimal(str(input_ppn_result.scalar() or 0))

            # 5. NSFP quota info for current month
            today = date.today()
            current_month = today.month
            current_year = today.year

            nsfp_stmt = select(
                func.count().label("total_requested"),
                func.sum(case((CoretaxNSFPTable.status == "used", 1), else_=0)).label("used"),
            ).where(
                CoretaxNSFPTable.npwp == npwp,
                CoretaxNSFPTable.tahun == current_year,
                CoretaxNSFPTable.bulan == current_month,
                CoretaxNSFPTable.deleted_at.is_(None),
            )
            nsfp_result = await session.execute(nsfp_stmt)
            nsfp_row = nsfp_result.first()
            total_requested = nsfp_row[0] or 0 if nsfp_row else 0
            used = nsfp_row[1] or 0 if nsfp_row else 0
            remaining = total_requested - used

            # 6. Daily activity (last 30 days)
            daily_stmt = (
                select(
                    func.date(CoretaxFakturTable.faktur_date).label("date"),
                    func.count().label("count"),
                    func.sum(CoretaxFakturTable.ppn).label("total_ppn"),
                )
                .where(
                    CoretaxFakturTable.npwp_penjual == npwp,
                    CoretaxFakturTable.faktur_type == "keluaran",
                    CoretaxFakturTable.faktur_date >= start_date,
                    CoretaxFakturTable.faktur_date <= end_date,
                    CoretaxFakturTable.deleted_at.is_(None),
                )
                .group_by(func.date(CoretaxFakturTable.faktur_date))
                .order_by(func.date(CoretaxFakturTable.faktur_date))
            )
            daily_result = await session.execute(daily_stmt)
            daily_activity = [
                {
                    "date": row[0].isoformat() if hasattr(row[0], "isoformat") else str(row[0]),
                    "count": row[1],
                    "total_ppn": float(row[2] or 0),
                }
                for row in daily_result
            ]

            # 7. Rejected faktur (last 30 days)
            rejected_stmt = (
                select(
                    CoretaxFakturTable.faktur_number,
                    CoretaxFakturTable.faktur_date,
                    CoretaxFakturTable.rejection_reason,
                    CoretaxFakturTable.nama_pembeli,
                )
                .where(
                    CoretaxFakturTable.npwp_penjual == npwp,
                    CoretaxFakturTable.faktur_type == "keluaran",
                    CoretaxFakturTable.status == "rejected",
                    CoretaxFakturTable.faktur_date >= start_date,
                    CoretaxFakturTable.deleted_at.is_(None),
                )
                .order_by(CoretaxFakturTable.faktur_date.desc())
                .limit(20)
            )
            rejected_result = await session.execute(rejected_stmt)
            rejected_fakturs = [
                {
                    "faktur_number": row[0],
                    "date": row[1].isoformat() if hasattr(row[1], "isoformat") else str(row[1]),
                    "reason": row[2],
                    "customer": row[3],
                }
                for row in rejected_result
            ]

            # 8. Large transactions (high PPN value)
            large_stmt = (
                select(
                    CoretaxFakturTable.faktur_number,
                    CoretaxFakturTable.faktur_date,
                    CoretaxFakturTable.dpp,
                    CoretaxFakturTable.ppn,
                    CoretaxFakturTable.nama_pembeli,
                )
                .where(
                    CoretaxFakturTable.npwp_penjual == npwp,
                    CoretaxFakturTable.faktur_type == "keluaran",
                    CoretaxFakturTable.status == "approved",
                    CoretaxFakturTable.ppn >= ALERT_PPN_LARGE_TRANSACTION,
                    CoretaxFakturTable.faktur_date >= start_date,
                    CoretaxFakturTable.deleted_at.is_(None),
                )
                .order_by(CoretaxFakturTable.ppn.desc())
                .limit(10)
            )
            large_result = await session.execute(large_stmt)
            large_transactions = [
                {
                    "faktur_number": row[0],
                    "date": row[1].isoformat() if hasattr(row[1], "isoformat") else str(row[1]),
                    "dpp": float(row[2]),
                    "ppn": float(row[3]),
                    "customer": row[4],
                }
                for row in large_result
            ]

            # Check thresholds and trigger alerts
            if output_by_status.get("rejected", 0) > ALERT_FAKTUR_REJECTED_THRESHOLD:
                await trigger_alert(
                    title="High Number of Rejected Faktur",
                    message=f"Total rejected faktur: {output_by_status['rejected']} (threshold: {ALERT_FAKTUR_REJECTED_THRESHOLD})",
                    severity="warning",
                    source="CoretaxFakturDashboard",
                )

            if remaining <= ALERT_NSFP_LOW_THRESHOLD:
                await trigger_alert(
                    title="NSFP Quota Running Low",
                    message=f"Only {remaining} NSFP remaining for month {current_month}/{current_year}",
                    severity="warning",
                    source="CoretaxFakturDashboard",
                )

            return {
                "npwp": npwp,
                "legal_entity_id": str(legal_entity_id),
                "generated_at": datetime.now(UTC).isoformat(),
                "date_range": {"start": start_date.isoformat(), "end": end_date.isoformat()},
                "faktur_keluaran": {
                    "total": output_by_status,
                    "total_ppn": float(total_ppn_keluaran),
                },
                "faktur_masukan": {"total": input_by_status, "total_ppn": float(total_ppn_masukan)},
                "nsfp": {
                    "total_requested": total_requested,
                    "used": used,
                    "remaining": remaining,
                    "month": current_month,
                    "year": current_year,
                },
                "daily_activity": daily_activity,
                "rejected_fakturs": rejected_fakturs,
                "large_transactions": large_transactions,
                "alerts": {
                    "rejected_threshold": ALERT_FAKTUR_REJECTED_THRESHOLD,
                    "nsfp_low_threshold": ALERT_NSFP_LOW_THRESHOLD,
                    "large_transaction_threshold": ALERT_PPN_LARGE_TRANSACTION,
                },
            }

    async def save_dashboard_snapshot(self, dashboard_data: dict[str, Any]) -> None:
        """
        Menyimpan snapshot dashboard ke tabel materialized.
        """
        async with await self._get_session() as session, session.begin():
            # Delete previous snapshot for same NPWP (keep latest)
            await session.execute(
                delete(CoretaxDashboardSnapshotTable).where(
                    CoretaxDashboardSnapshotTable.npwp == dashboard_data["npwp"],
                    CoretaxDashboardSnapshotTable.legal_entity_id
                    == UUID(dashboard_data["legal_entity_id"]),
                )
            )

            stmt = insert(CoretaxDashboardSnapshotTable).values(
                id=uuid4(),
                npwp=dashboard_data["npwp"],
                legal_entity_id=UUID(dashboard_data["legal_entity_id"]),
                generated_at=datetime.now(UTC),
                data=dashboard_data,
            )
            await session.execute(stmt)
            # Catatan: session.begin() otomatis menangani commit secara aman saat blok berakhir.

    async def get_dashboard_snapshot(self, npwp: str, legal_entity_id: UUID) -> dict | None:
        """
        Mendapatkan snapshot dashboard terakhir.
        """
        async with await self._get_session() as session:
            stmt = (
                select(CoretaxDashboardSnapshotTable)
                .where(
                    CoretaxDashboardSnapshotTable.npwp == npwp,
                    CoretaxDashboardSnapshotTable.legal_entity_id == legal_entity_id,
                )
                .order_by(CoretaxDashboardSnapshotTable.generated_at.desc())
                .limit(1)
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if not row:
                return None
            return row.data

    async def refresh_dashboard(self, npwp: str, legal_entity_id: UUID) -> dict:
        """
        Menghitung dan menyimpan dashboard terbaru.
        """
        dashboard = await self.compute_dashboard(npwp, legal_entity_id)
        await self.save_dashboard_snapshot(dashboard)
        self._dashboard_cache[f"{npwp}:{legal_entity_id}"] = dashboard
        self._last_refresh = datetime.now(UTC)
        logger.info(f"Coretax dashboard refreshed for {npwp}")
        return dashboard

    async def get_dashboard(
        self, npwp: str, legal_entity_id: UUID, force_refresh: bool = False
    ) -> dict:
        """
        Mendapatkan dashboard (dari cache atau refresh).
        """
        cache_key = f"{npwp}:{legal_entity_id}"
        if not force_refresh and cache_key in self._dashboard_cache:
            # Check if cache is stale (older than DASHBOARD_REFRESH_INTERVAL)
            if (
                self._last_refresh
                and (datetime.now(UTC) - self._last_refresh).total_seconds()
                < DASHBOARD_REFRESH_INTERVAL
            ):
                return self._dashboard_cache[cache_key]

        return await self.refresh_dashboard(npwp, legal_entity_id)

    async def get_monthly_summary(
        self, npwp: str, tahun: int, bulan: int, legal_entity_id: UUID
    ) -> dict:
        """
        Mendapatkan ringkasan bulanan faktur.
        """
        async with await self._get_session() as session:
            # Faktur Keluaran bulan ini
            output_stmt = select(
                func.count().label("count"),
                func.coalesce(func.sum(CoretaxFakturTable.ppn), 0).label("total_ppn"),
            ).where(
                CoretaxFakturTable.npwp_penjual == npwp,
                CoretaxFakturTable.faktur_type == "keluaran",
                CoretaxFakturTable.status == "approved",
                func.extract("year", CoretaxFakturTable.faktur_date) == tahun,
                func.extract("month", CoretaxFakturTable.faktur_date) == bulan,
                CoretaxFakturTable.deleted_at.is_(None),
            )
            output_result = await session.execute(output_stmt)
            output_row = output_result.first()

            # Faktur Masukan bulan ini
            input_stmt = select(
                func.count().label("count"),
                func.coalesce(func.sum(CoretaxFakturTable.ppn), 0).label("total_ppn"),
            ).where(
                CoretaxFakturTable.npwp_pembeli == npwp,
                CoretaxFakturTable.faktur_type == "masukan",
                CoretaxFakturTable.status == "approved",
                func.extract("year", CoretaxFakturTable.faktur_date) == tahun,
                func.extract("month", CoretaxFakturTable.faktur_date) == bulan,
                CoretaxFakturTable.deleted_at.is_(None),
            )
            input_result = await session.execute(input_stmt)
            input_row = input_result.first()

            out_count = output_row[0] or 0 if output_row else 0
            out_ppn = output_row[1] or 0 if output_row else 0
            in_count = input_row[0] or 0 if input_row else 0
            in_ppn = input_row[1] or 0 if input_row else 0

            return {
                "tahun": tahun,
                "bulan": bulan,
                "npwp": npwp,
                "faktur_keluaran": {"jumlah": out_count, "total_ppn": float(out_ppn)},
                "faktur_masukan": {"jumlah": in_count, "total_ppn": float(in_ppn)},
                "net_ppn": float(out_ppn - in_ppn),
            }

    async def get_yearly_summary(self, npwp: str, tahun: int, legal_entity_id: UUID) -> list[dict]:
        """
        Mendapatkan ringkasan tahunan per bulan secara paralel menggunakan asyncio.gather.
        """
        tasks = [
            self.get_monthly_summary(npwp, tahun, bulan, legal_entity_id) for bulan in range(1, 13)
        ]
        return list(await asyncio.gather(*tasks))

    async def get_nsfp_usage_report(
        self, npwp: str, tahun: int, legal_entity_id: UUID
    ) -> list[dict]:
        """
        Mendapatkan laporan penggunaan NSFP per bulan.
        """
        async with await self._get_session() as session:
            stmt = (
                select(
                    CoretaxNSFPTable.bulan,
                    func.count().label("total_requested"),
                    func.sum(case((CoretaxNSFPTable.status == "used", 1), else_=0)).label("used"),
                )
                .where(
                    CoretaxNSFPTable.npwp == npwp,
                    CoretaxNSFPTable.tahun == tahun,
                    CoretaxNSFPTable.deleted_at.is_(None),
                )
                .group_by(CoretaxNSFPTable.bulan)
                .order_by(CoretaxNSFPTable.bulan)
            )
            result = await session.execute(stmt)
            rows = result.all()

            return [
                {"bulan": row[0], "requested": row[1], "used": row[2], "remaining": row[1] - row[2]}
                for row in rows
            ]


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_coretax_dashboard: CoretaxFakturDashboard | None = None


async def get_coretax_dashboard() -> CoretaxFakturDashboard:
    """Get singleton instance of CoretaxFakturDashboard."""
    global _coretax_dashboard
    if _coretax_dashboard is None:
        _coretax_dashboard = CoretaxFakturDashboard()
    return _coretax_dashboard


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ["CoretaxDashboardError", "CoretaxFakturDashboard", "get_coretax_dashboard"]
