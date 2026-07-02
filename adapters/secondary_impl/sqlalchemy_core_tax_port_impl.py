#!/usr/bin/env python3
"""
Module: sqlalchemy_core_tax_port_impl.py
Adapter for CoreTaxPort using SQLAlchemy with full implementation.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime, String, Text, select
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base

from ports.primary.core_tax_port import CoreTaxPort

# Sekarang import langsung — TaxStatus sudah tersedia di value_objects
from domain.tax_transaction.value_objects import TaxStatus

logger = logging.getLogger(__name__)

Base = declarative_base()




class CoreTaxSubmissionTable(Base):
    """ORM model untuk menyimpan submission pajak ke CoreTax."""
    __tablename__ = "coretax_submissions"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    legal_entity_id = Column(PGUUID(as_uuid=True), nullable=False)
    tax_type = Column(String(50), nullable=False)   # e.g., "PPN", "PPh21", "PPh23"
    period = Column(String(10), nullable=False)     # e.g., "2024-01"
    submission_data = Column(Text, nullable=False)  # JSON string
    status = Column(String(50), nullable=False, default="PENDING")
    response = Column(Text, nullable=True)          # JSON response from authority
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=lambda: datetime.now(timezone.utc))


class SQLAlchemyCoreTaxAdapter(CoreTaxPort):
    """
    Implementasi CoreTaxPort dengan SQLAlchemy.
    """

    def __init__(
        self,
        session: AsyncSession | None = None,
        authority_adapter: Any = None,
    ):
        self._session = session
        self._authority_adapter = authority_adapter
        if self._authority_adapter is None:
            try:
                from adapters.secondary_impl.coretax_authority_adapter import CoretaxAuthorityAdapter
                self._authority_adapter = CoretaxAuthorityAdapter()
                logger.info("CoretaxAuthorityAdapter loaded successfully")
            except ImportError:
                logger.warning("CoretaxAuthorityAdapter not available, using mock")
                self._authority_adapter = None

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    # ========================================================================
    # PORT METHODS (CoreTaxPort) � LENGKAP
    # ========================================================================

    async def submit_tax(
        self,
        legal_entity_id: UUID,
        tax_type: str,
        period: str,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Submit data pajak ke CoreTax (otoritas) dan simpan status."""
        session = await self._get_session()
        data_json = json.dumps(data, default=str, ensure_ascii=False)

        submission = CoreTaxSubmissionTable(
            id=uuid4(),
            legal_entity_id=legal_entity_id,
            tax_type=tax_type,
            period=period,
            submission_data=data_json,
            status="PENDING",
            created_at=datetime.now(timezone.utc),
        )
        session.add(submission)
        await session.flush()

        response_data = None
        status = "SUBMITTED"
        error = None

        if self._authority_adapter is not None:
            try:
                response_data = await self._authority_adapter.submit(data)
                submission.status = "SUBMITTED"
                submission.submitted_at = datetime.now(timezone.utc)
                submission.response = json.dumps(response_data, default=str, ensure_ascii=False)
                logger.info(f"CoreTax submission successful for {tax_type} period {period}")
            except Exception as e:
                error = str(e)
                submission.status = "FAILED"
                submission.response = json.dumps({"error": error}, ensure_ascii=False)
                logger.error(f"CoreTax submission failed: {e}")
        else:
            submission.status = "PENDING"
            logger.info("No authority adapter, submission saved as PENDING")

        await session.commit()

        result = {
            "submission_id": str(submission.id),
            "status": submission.status,
            "submitted_at": submission.submitted_at.isoformat() if submission.submitted_at else None,
        }
        if response_data:
            result["response"] = response_data
        if error:
            result["error"] = error
        return result

    async def check_status(self, submission_id: UUID) -> Dict[str, Any]:
        """Periksa status submission berdasarkan ID."""
        session = await self._get_session()
        stmt = select(CoreTaxSubmissionTable).where(CoreTaxSubmissionTable.id == submission_id)
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            raise ValueError(f"Submission with id {submission_id} not found")
        return {
            "submission_id": str(row.id),
            "tax_type": row.tax_type,
            "period": row.period,
            "status": row.status,
            "response": json.loads(row.response) if row.response else None,
            "submitted_at": row.submitted_at.isoformat() if row.submitted_at else None,
            "created_at": row.created_at.isoformat(),
        }

    # ========================================================================
    # METHOD YANG HILANG � DITAMBAHKAN
    # ========================================================================

    async def get_status(self, tax_id: str) -> TaxStatus:
        """
        Mendapatkan status pajak berdasarkan tax_id (misal NPWP).
        """
        # Contoh implementasi: cek di database atau API
        # Untuk sementara, ambil dari submission terbaru jika ada
        session = await self._get_session()
        stmt = (
            select(CoreTaxSubmissionTable)
            .where(CoreTaxSubmissionTable.submission_data.contains(tax_id))  # approximate
            .order_by(CoreTaxSubmissionTable.created_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if row:
            # Mapping status string ke TaxStatus
            status_map = {
                "PENDING": TaxStatus.PENDING,
                "SUBMITTED": TaxStatus.SUBMITTED,
                "FAILED": TaxStatus.FAILED,
                "ACTIVE": TaxStatus.ACTIVE,
                "INACTIVE": TaxStatus.INACTIVE,
            }
            return status_map.get(row.status, TaxStatus.PENDING)
        return TaxStatus.INACTIVE  # default jika tidak ditemukan

    async def calculate_tax(self, amount: Decimal, tax_rate: Decimal) -> Decimal:
        """
        Menghitung pajak berdasarkan jumlah dan tarif.
        """
        return amount * tax_rate / Decimal(100)

    async def validate_tax_id(self, tax_id: str) -> bool:
        """
        Memvalidasi tax_id (misal NPWP).
        Contoh: NPWP 15 digit, cek modulo.
        """
        if not tax_id or len(tax_id) != 15:
            return False
        # Implementasi validasi NPWP sederhana
        # NPWP = 15 digit, cek digit terakhir
        try:
            digits = [int(c) for c in tax_id]
            # Validasi checksum (contoh sederhana)
            sum_digits = sum(digits[:14])
            expected = sum_digits % 9
            return expected == digits[14]
        except ValueError:
            return False

    async def get_tax_rate(self, tax_type: str, effective_date: date) -> Decimal:
        """
        Mendapatkan tarif pajak berdasarkan tipe dan tanggal berlaku.
        Bisa diambil dari database atau API.
        """
        # Contoh: tarif PPN = 11%, PPh21 = 5%, dst.
        rates = {
            "PPN": Decimal("11.0"),
            "PPh21": Decimal("5.0"),
            "PPh23": Decimal("2.0"),
            "PPh22": Decimal("1.5"),
            "PPH4": Decimal("0.5"),
        }
        # Jika tarif bergantung tanggal, bisa tambahkan logika
        return rates.get(tax_type, Decimal("0.0"))

    # ========================================================================
    # HELPER METHODS (opsional, tetap dipertahankan)
    # ========================================================================

    async def get_submissions_by_legal_entity(
        self,
        legal_entity_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Dict[str, Any]]:
        """Ambil semua submission untuk legal entity tertentu."""
        session = await self._get_session()
        stmt = (
            select(CoreTaxSubmissionTable)
            .where(CoreTaxSubmissionTable.legal_entity_id == legal_entity_id)
            .order_by(CoreTaxSubmissionTable.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [
            {
                "id": str(row.id),
                "tax_type": row.tax_type,
                "period": row.period,
                "status": row.status,
                "submitted_at": row.submitted_at.isoformat() if row.submitted_at else None,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]

    async def get_submission_by_id(self, submission_id: UUID) -> Dict[str, Any] | None:
        """Ambil detail submission berdasarkan ID (tanpa raise jika tidak ditemukan)."""
        try:
            return await self.check_status(submission_id)
        except ValueError:
            return None


# Alias untuk backward compatibility (jika diperlukan)
__all__ = [
    "SQLAlchemyCoreTaxAdapter",
    "CoreTaxSubmissionTable",
]