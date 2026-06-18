#!/usr/bin/env python3
"""
Module: ap_aging_buckets.py
Layer: Projections (Subledger)
Responsibility: Membangun read model aging buckets untuk Account Payable.
               Mengkategorikan hutang berdasarkan jatuh tempo (0-30 hari, 31-60,
               61-90, 91-120, >120 hari) dan menyediakan query cepat untuk
               laporan aging, analisis likuiditas, dan perencanaan pembayaran.
Dependencies:
- asyncio, logging, datetime, decimal
- sqlalchemy.ext.asyncio
- infrastructure.database.session_factory_sqlalchemy
- infrastructure.persistence_orm.ap_invoice_table
- infrastructure.persistence_orm.supplier_table
- infrastructure.persistence_orm.legal_entity_table
Audit: Aging buckets di-build secara periodik atau on-demand.
       Hasil digunakan untuk manajemen kas dan perencanaan pembayaran.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, insert, select
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession

# Internal dependencies
from infrastructure.database.session_factory_sqlalchemy import get_session_factory
from infrastructure.persistence_orm.ap_invoice_table import APInvoiceTable
from infrastructure.persistence_orm.supplier_table import SupplierTable
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

PROJECTION_NAME = "ap_aging_buckets"

# Aging bucket definitions (days overdue)
BUCKETS = [
    {"name": "0-30 days", "min_days": 0, "max_days": 30, "order": 1},
    {"name": "31-60 days", "min_days": 31, "max_days": 60, "order": 2},
    {"name": "61-90 days", "min_days": 61, "max_days": 90, "order": 3},
    {"name": "91-120 days", "min_days": 91, "max_days": 120, "order": 4},
    {"name": "120+ days", "min_days": 121, "max_days": None, "order": 5},
]

# ============================================================================
# EXCEPTIONS
# ============================================================================


class APAgingBucketsError(Exception):
    """Base exception untuk AP aging buckets projection."""

    pass


# ============================================================================
# AP AGING BUCKETS PROJECTION
# ============================================================================


class APAgingBuckets:
    """
    Read model aging buckets untuk Account Payable.

    Fitur:
    - Kategorisasi invoice berdasarkan hari overdue
    - Agregasi per supplier dan per bucket
    - Query untuk laporan aging summary dan detail
    - Support multiple as_of_date (historical snapshots)
    """

    def __init__(self):
        self._session_factory = None
        self._buckets = BUCKETS

    async def _get_session(self) -> AsyncSession:
        if self._session_factory is None:
            self._session_factory = await get_session_factory()
        return self._session_factory.get_session()

    def _calculate_bucket(self, due_date: date, as_of_date: date) -> dict | None:
        """
        Menentukan bucket berdasarkan hari overdue.
        """
        if due_date >= as_of_date:
            # Not yet due
            return None

        days_overdue = (as_of_date - due_date).days

        for bucket in self._buckets:
            min_days = bucket["min_days"]
            max_days = bucket["max_days"]
            if max_days is None:
                if days_overdue >= min_days:
                    return bucket
            elif min_days <= days_overdue <= max_days:
                return bucket
        return None

    async def compute_aging(self, legal_entity_id: UUID, as_of_date: date) -> dict[str, Any]:
        """
        Menghitung aging AP pada tanggal tertentu.

        Args:
            legal_entity_id: Legal entity
            as_of_date: Tanggal aging (biasanya period end)

        Returns:
            Aging summary per bucket dan per supplier
        """
        async with await self._get_session() as session:
            # Get all AP invoices that are not fully paid and not cancelled
            invoice_stmt = select(APInvoiceTable).where(
                APInvoiceTable.legal_entity_id == legal_entity_id,
                APInvoiceTable.status.in_(["approved", "partially_paid"]),
                APInvoiceTable.deleted_at.is_(None),
                APInvoiceTable.total_amount > APInvoiceTable.paid_amount,
            )
            invoice_result = await session.execute(invoice_stmt)
            invoices = invoice_result.scalars().all()

            # Initialize bucket totals
            bucket_totals = {}
            for bucket in self._buckets:
                bucket_totals[bucket["name"]] = Decimal(0)

            # Initialize per-supplier totals
            supplier_totals = {}

            for invoice in invoices:
                outstanding = invoice.total_amount - invoice.paid_amount
                if outstanding <= 0:
                    continue

                bucket = self._calculate_bucket(invoice.due_date, as_of_date)
                if bucket:
                    bucket_name = bucket["name"]
                    bucket_totals[bucket_name] += outstanding

                    # Per-supplier aggregation
                    supplier_id = str(invoice.vendor_id)
                    if supplier_id not in supplier_totals:
                        supplier_totals[supplier_id] = {
                            "supplier_id": supplier_id,
                            "supplier_name": "",
                            "buckets": {},
                            "total_outstanding": Decimal(0),
                        }
                    supplier_totals[supplier_id]["buckets"][bucket_name] = (
                        supplier_totals[supplier_id]["buckets"].get(bucket_name, Decimal(0))
                        + outstanding
                    )
                    supplier_totals[supplier_id]["total_outstanding"] += outstanding

            # Get supplier names
            if supplier_totals:
                supplier_ids = [UUID(sid) for sid in supplier_totals]
                supp_stmt = select(SupplierTable.id, SupplierTable.supplier_name).where(
                    SupplierTable.id.in_(supplier_ids)
                )
                supp_result = await session.execute(supp_stmt)
                for row in supp_result:
                    sid = str(row[0])
                    if sid in supplier_totals:
                        supplier_totals[sid]["supplier_name"] = row[1]

            total_outstanding = sum(bucket_totals.values())

            return {
                "as_of_date": as_of_date.isoformat(),
                "legal_entity_id": str(legal_entity_id),
                "total_outstanding": float(total_outstanding),
                "buckets": [
                    {
                        "bucket_name": bucket["name"],
                        "amount": float(bucket_totals[bucket["name"]]),
                        "percentage": float(bucket_totals[bucket["name"]] / total_outstanding * 100)
                        if total_outstanding > 0
                        else 0,
                    }
                    for bucket in self._buckets
                ],
                "suppliers": [
                    {
                        "supplier_id": supp["supplier_id"],
                        "supplier_name": supp["supplier_name"],
                        "total_outstanding": float(supp["total_outstanding"]),
                        "buckets": {k: float(v) for k, v in supp["buckets"].items()},
                    }
                    for supp in supplier_totals.values()
                ],
                "generated_at": datetime.now(UTC).isoformat(),
            }

    async def save_aging_snapshot(self, aging_data: dict[str, Any]) -> None:
        """
        Menyimpan snapshot aging ke tabel materialized.
        """
        async with await self._get_session() as session, session.begin():
            # Delete existing snapshot for same as_of_date
            await session.execute(
                delete(APAgingSnapshotTable).where(
                    APAgingSnapshotTable.legal_entity_id == UUID(aging_data["legal_entity_id"]),
                    APAgingSnapshotTable.as_of_date == date.fromisoformat(aging_data["as_of_date"]),
                )
            )

            # Insert snapshot
            stmt = insert(APAgingSnapshotTable).values(
                id=uuid4(),
                legal_entity_id=UUID(aging_data["legal_entity_id"]),
                as_of_date=date.fromisoformat(aging_data["as_of_date"]),
                total_outstanding=Decimal(str(aging_data["total_outstanding"])),
                buckets_data=aging_data["buckets"],
                suppliers_data=aging_data["suppliers"],
                generated_at=datetime.now(UTC),
            )
            await session.execute(stmt)
            await session.commit()

    async def get_aging_snapshot(self, legal_entity_id: UUID, as_of_date: date) -> dict | None:
        """
        Mendapatkan aging snapshot yang sudah tersimpan.
        """
        async with await self._get_session() as session:
            stmt = select(APAgingSnapshotTable).where(
                APAgingSnapshotTable.legal_entity_id == legal_entity_id,
                APAgingSnapshotTable.as_of_date == as_of_date,
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if not row:
                return None
            return {
                "as_of_date": row.as_of_date.isoformat(),
                "total_outstanding": float(row.total_outstanding),
                "buckets": row.buckets_data,
                "suppliers": row.suppliers_data,
                "generated_at": row.generated_at.isoformat(),
            }

    async def generate_all_snapshots(self, legal_entity_id: UUID) -> list[dict]:
        """
        Menghasilkan snapshot untuk semua period end dates yang tersedia.
        """
        async with await self._get_session() as session:
            # Get all period end dates where period is closed
            from infrastructure.persistence_orm.fiscal_period_table import FiscalPeriodTable

            stmt = (
                select(FiscalPeriodTable.end_date)
                .where(
                    FiscalPeriodTable.legal_entity_id == legal_entity_id,
                    FiscalPeriodTable.status == "closed",
                )
                .order_by(FiscalPeriodTable.end_date)
            )
            result = await session.execute(stmt)
            end_dates = result.scalars().all()

        snapshots = []
        for end_date in end_dates:
            aging = await self.compute_aging(legal_entity_id, end_date)
            await self.save_aging_snapshot(aging)
            snapshots.append(aging)
            logger.info(f"AP Aging snapshot saved for {end_date}")

        return snapshots

    async def get_supplier_aging(
        self, legal_entity_id: UUID, supplier_id: UUID, as_of_date: date | None = None
    ) -> dict:
        """
        Mendapatkan aging untuk supplier tertentu.
        """
        if as_of_date is None:
            as_of_date = date.today()

        # Get snapshot or compute on the fly
        snapshot = await self.get_aging_snapshot(legal_entity_id, as_of_date)
        if snapshot:
            for supp in snapshot.get("suppliers", []):
                if supp["supplier_id"] == str(supplier_id):
                    return supp

        # Compute fresh if not in snapshot
        aging = await self.compute_aging(legal_entity_id, as_of_date)
        for supp in aging["suppliers"]:
            if supp["supplier_id"] == str(supplier_id):
                return supp

        return {"supplier_id": str(supplier_id), "total_outstanding": 0, "buckets": {}}

    async def get_aging_summary_for_report(self, legal_entity_id: UUID, as_of_date: date) -> dict:
        """
        Mendapatkan ringkasan aging untuk laporan.
        """
        aging = await self.compute_aging(legal_entity_id, as_of_date)
        return aging

    async def get_cash_requirements(
        self, legal_entity_id: UUID, as_of_date: date, horizon_days: int = 30
    ) -> dict[str, Any]:
        """
        Mendapatkan proyeksi kebutuhan kas berdasarkan aging.

        Args:
            legal_entity_id: Legal entity
            as_of_date: Tanggal dasar perhitungan
            horizon_days: Jumlah hari ke depan untuk proyeksi
        """
        aging = await self.compute_aging(legal_entity_id, as_of_date)

        # Invoices due within horizon
        due_soon = Decimal(0)
        for bucket in aging["buckets"]:
            bucket_name = bucket["bucket_name"]
            # For simplicity, assume 0-30 day bucket is due within horizon
            if "0-30" in bucket_name:
                due_soon += Decimal(str(bucket["amount"]))

        # Already overdue (should be paid immediately)
        overdue = Decimal(0)
        for bucket in aging["buckets"]:
            if "120+" in bucket["bucket_name"] or "91-120" in bucket["bucket_name"]:
                overdue += Decimal(str(bucket["amount"]))

        return {
            "legal_entity_id": str(legal_entity_id),
            "as_of_date": as_of_date.isoformat(),
            "total_outstanding": aging["total_outstanding"],
            "overdue_amount": float(overdue),
            "due_within_30_days": float(due_soon),
            "cash_required_total": float(overdue + due_soon),
            "horizon_days": horizon_days,
        }


# ============================================================================
# ORM MODEL (tambahan)
# ============================================================================

from sqlalchemy import JSON, Column, Date, DateTime, Index, Numeric
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class APAgingSnapshotTable(Base):
    __tablename__ = "ap_aging_snapshot"
    __table_args__ = (
        Index("idx_ap_aging_legal_entity", "legal_entity_id"),
        Index("idx_ap_aging_as_of_date", "as_of_date"),
        {"schema": "projections"},
    )

    id = Column(PGUUID(as_uuid=True), primary_key=True)
    legal_entity_id = Column(PGUUID(as_uuid=True), nullable=False)
    as_of_date = Column(Date, nullable=False)
    total_outstanding = Column(Numeric(20, 2), nullable=False, default=0)
    buckets_data = Column(JSON, nullable=True)
    suppliers_data = Column(JSON, nullable=True)
    generated_at = Column(DateTime(timezone=True), nullable=False)


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_ap_aging_buckets: APAgingBuckets | None = None


async def get_ap_aging_buckets() -> APAgingBuckets:
    """Get singleton instance of APAgingBuckets."""
    global _ap_aging_buckets
    if _ap_aging_buckets is None:
        _ap_aging_buckets = APAgingBuckets()
    return _ap_aging_buckets


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ["APAgingBuckets", "APAgingBucketsError", "get_ap_aging_buckets"]
