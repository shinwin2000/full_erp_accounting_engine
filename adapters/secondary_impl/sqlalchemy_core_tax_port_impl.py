#!/usr/bin/env python3
"""
Module: sqlalchemy_core_tax_port_impl.py
Adapter for CoreTaxPort using SQLAlchemy with full implementation.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime, String, Text, select
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base

from ports.primary.core_tax_port import CoreTaxPort

logger = logging.getLogger(__name__)

Base = declarative_base()


class CoreTaxSubmissionTable(Base):
    """ORM model untuk menyimpan submission pajak ke CoreTax."""
    __tablename__ = "coretax_submissions"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    legal_entity_id = Column(PGUUID(as_uuid=True), nullable=False)
    tax_type = Column(String(50), nullable=False)  # e.g., "PPN", "PPh21", "PPh23"
    period = Column(String(10), nullable=False)    # e.g., "2024-01"
    submission_data = Column(Text, nullable=False)  # JSON string
    status = Column(String(50), nullable=False, default="PENDING")
    response = Column(Text, nullable=True)         # JSON response from authority
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=datetime.utcnow)


class SQLAlchemyCoreTaxAdapter(CoreTaxPort):
    """
    Implementasi CoreTaxPort dengan SQLAlchemy.
    Menggunakan CoretaxAuthorityAdapter untuk komunikasi eksternal (opsional).
    """

    def __init__(
        self,
        session: AsyncSession | None = None,
        authority_adapter: Any = None,
    ):
        self._session = session
        self._authority_adapter = authority_adapter
        # Jika authority_adapter tidak diberikan, coba import
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
    # PORT METHODS (CoreTaxPort)
    # ========================================================================

    async def submit_tax(
        self,
        legal_entity_id: UUID,
        tax_type: str,
        period: str,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Submit data pajak ke CoreTax (otoritas) dan simpan status.
        """
        session = await self._get_session()

        # Serialize data ke JSON
        data_json = json.dumps(data, default=str, ensure_ascii=False)

        # Buat record submission
        submission = CoreTaxSubmissionTable(
            id=uuid4(),
            legal_entity_id=legal_entity_id,
            tax_type=tax_type,
            period=period,
            submission_data=data_json,
            status="PENDING",
            created_at=datetime.utcnow(),
        )

        session.add(submission)
        await session.flush()

        # Jika ada authority adapter, submit ke eksternal
        response_data = None
        status = "SUBMITTED"
        error = None

        if self._authority_adapter is not None:
            try:
                # Asumsikan authority adapter memiliki method submit(data)
                response_data = await self._authority_adapter.submit(data)
                submission.status = "SUBMITTED"
                submission.submitted_at = datetime.utcnow()
                submission.response = json.dumps(response_data, default=str, ensure_ascii=False)
                logger.info(f"CoreTax submission successful for {tax_type} period {period}")
            except Exception as e:
                error = str(e)
                submission.status = "FAILED"
                submission.response = json.dumps({"error": error}, ensure_ascii=False)
                logger.error(f"CoreTax submission failed: {e}")
                # Jangan raise, karena kita masih ingin menyimpan record
        else:
            # Tanpa authority, kita hanya simpan sebagai PENDING (mock)
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
        """
        Periksa status submission berdasarkan ID.
        """
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
    # ADDITIONAL HELPER METHODS (opsional)
    # ========================================================================

    async def get_submissions_by_legal_entity(
        self,
        legal_entity_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Dict[str, Any]]:
        """
        Ambil semua submission untuk legal entity tertentu.
        """
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
        """
        Ambil detail submission berdasarkan ID (mirip check_status, tapi tidak raise).
        """
        try:
            return await self.check_status(submission_id)
        except ValueError:
            return None


# Untuk backward compatibility, alias dengan nama lama jika diperlukan
SQLAlchemyCoreTaxAdapter = SQLAlchemyCoreTaxAdapter

__all__ = [
    "SQLAlchemyCoreTaxAdapter",
    "CoreTaxSubmissionTable",
]