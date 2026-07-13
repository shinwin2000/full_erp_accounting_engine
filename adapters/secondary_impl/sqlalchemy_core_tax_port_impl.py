#!/usr/bin/env python3
"""
Module: sqlalchemy_core_tax_port_impl.py
Adapter for CoreTaxPort using SQLAlchemy.
Fully implements CoreTaxPort with correct signatures.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime, String, Text, select
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base

# Import domain value objects (if needed)
from ports.primary.core_tax_port import CoreTaxPort

logger = logging.getLogger(__name__)

Base = declarative_base()


class CoreTaxSubmissionTable(Base):
    """ORM model untuk menyimpan submission pajak ke CoreTax."""
    __tablename__ = "coretax_submissions"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    legal_entity_id = Column(PGUUID(as_uuid=True), nullable=False)
    tax_type = Column(String(50), nullable=False)
    period = Column(String(10), nullable=False)
    submission_data = Column(Text, nullable=False)
    status = Column(String(50), nullable=False, default="PENDING")
    response = Column(Text, nullable=True)
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=lambda: datetime.now(UTC))


class SQLAlchemyCoreTaxAdapter(CoreTaxPort):
    """
    Implementasi CoreTaxPort dengan SQLAlchemy.
    Semua method mengikuti port signature.
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
                from adapters.secondary_impl.coretax_authority_adapter import (
                    CoretaxAuthorityAdapter,
                )
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
    # PORT METHODS (CoreTaxPort)
    # ========================================================================

    async def submit_tax(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        Submit data pajak ke otoritas pajak.
        Data harus berisi: legal_entity_id, tax_type, period, dan data pajak lainnya.
        """
        session = await self._get_session()

        # Ekstrak field yang diperlukan dari data
        legal_entity_id = data.get("legal_entity_id")
        tax_type = data.get("tax_type", "UNKNOWN")
        period = data.get("period", "")
        submission_data = data.get("submission_data", data)  # fallback

        if not legal_entity_id:
            raise ValueError("Missing 'legal_entity_id' in data")

        # Simpan submission
        submission = CoreTaxSubmissionTable(
            id=uuid4(),
            legal_entity_id=UUID(str(legal_entity_id)),
            tax_type=tax_type,
            period=period,
            submission_data=json.dumps(submission_data, default=str, ensure_ascii=False),
            status="PENDING",
            created_at=datetime.now(UTC),
        )
        session.add(submission)
        await session.flush()

        # Kirim ke otoritas jika adapter tersedia
        response_data = None
        error = None
        status = "PENDING"

        if self._authority_adapter is not None:
            try:
                response_data = await self._authority_adapter.submit(data)
                status = "SUBMITTED"
                submission.status = "SUBMITTED"
                submission.submitted_at = datetime.now(UTC)
                submission.response = json.dumps(response_data, default=str, ensure_ascii=False)
                logger.info("CoreTax submission successful for %s period %s", tax_type, period)
            except Exception as e:
                error = str(e)
                status = "FAILED"
                submission.status = "FAILED"
                submission.response = json.dumps({"error": error}, ensure_ascii=False)
                logger.error("CoreTax submission failed: %s", e)
        else:
            status = "PENDING"
            logger.info("No authority adapter, submission saved as PENDING")

        await session.commit()

        result = {
            "submission_id": str(submission.id),
            "status": status,
            "submitted_at": submission.submitted_at.isoformat() if submission.submitted_at else None,
        }
        if response_data:
            result["response"] = response_data
        if error:
            result["error"] = error
        return result

    async def get_status(self, submission_id: str) -> dict[str, Any]:
        """
        Mendapatkan status submission berdasarkan submission_id (string UUID).
        """
        session = await self._get_session()
        try:
            stmt = select(CoreTaxSubmissionTable).where(CoreTaxSubmissionTable.id == UUID(submission_id))
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if not row:
                return {"status": "NOT_FOUND", "message": f"Submission {submission_id} not found"}
            return {
                "submission_id": str(row.id),
                "tax_type": row.tax_type,
                "period": row.period,
                "status": row.status,
                "response": json.loads(row.response) if row.response else None,
                "submitted_at": row.submitted_at.isoformat() if row.submitted_at else None,
                "created_at": row.created_at.isoformat(),
            }
        except ValueError:
            return {"status": "ERROR", "message": f"Invalid submission_id format: {submission_id}"}
        except Exception as e:
            logger.error("Error getting status: %s", e)
            return {"status": "ERROR", "message": str(e)}

    async def calculate_tax(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        Menghitung pajak berdasarkan data transaksi.
        Data minimal: amount (Decimal), tax_code (str), date (str YYYY-MM-DD).
        """
        amount = data.get("amount")
        tax_code = data.get("tax_code")
        effective_date = data.get("date")

        if amount is None or tax_code is None:
            raise ValueError("Missing 'amount' or 'tax_code' in data")

        # Dapatkan tarif
        rate = await self.get_tax_rate(tax_code, effective_date)
        tax_amount = Decimal(str(amount)) * rate / Decimal(100)

        return {
            "tax_amount": str(tax_amount),
            "tax_base": str(amount),
            "tax_rate": str(rate),
            "currency": data.get("currency", "IDR"),
            "tax_code": tax_code,
            "effective_date": effective_date,
            "status": "calculated",
        }

    async def validate_tax_id(self, tax_id: str) -> bool:
        """
        Memvalidasi NPWP / tax ID.
        Contoh sederhana: NPWP harus 15 digit dengan checksum.
        """
        if not tax_id or len(tax_id) != 15:
            return False
        try:
            digits = [int(c) for c in tax_id]
            # Checksum sederhana: modulo 9 dari 14 digit pertama
            sum_digits = sum(digits[:14])
            expected = sum_digits % 9
            return expected == digits[14]
        except ValueError:
            return False

    async def get_tax_rate(self, tax_code: str, date: str) -> Decimal:
        """
        Mendapatkan tarif pajak untuk kode dan tanggal tertentu.
        """
        # Contoh tarif statis; bisa diperluas dengan lookup database/API
        rates = {
            "PPN": Decimal("11.0"),
            "PPH21": Decimal("5.0"),
            "PPH23": Decimal("2.0"),
            "PPH22": Decimal("1.5"),
            "PPH4": Decimal("0.5"),
        }
        return rates.get(tax_code, Decimal("0.0"))

    # ========================================================================
    # METODE TAMBAHAN (opsional, tidak mengganggu kontrak)
    # ========================================================================

    async def get_submissions_by_legal_entity(
        self,
        legal_entity_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
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

    async def get_submission_by_id(self, submission_id: UUID) -> dict[str, Any] | None:
        """Ambil detail submission berdasarkan ID (tanpa raise jika tidak ditemukan)."""
        result = await self.get_status(str(submission_id))
        if result.get("status") == "NOT_FOUND":
            return None
        return result


# Alias untuk backward compatibility
__all__ = [
    "CoreTaxSubmissionTable",
    "SQLAlchemyCoreTaxAdapter",
]
