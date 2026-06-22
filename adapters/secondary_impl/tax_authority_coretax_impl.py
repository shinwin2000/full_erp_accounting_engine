#!/usr/bin/env python3
"""
Module: tax_authority_coretax_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi CoreTaxPort menggunakan API Core Tax (stub untuk development).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from ports.primary.core_tax_port import CoreTaxPort

logger = logging.getLogger(__name__)


class CoretaxAuthorityAdapter(CoreTaxPort):
    """
    Stub adapter untuk Core Tax API.
    Konfigurasi dapat diberikan melalui constructor.
    """
    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self._submissions: dict[str, dict[str, Any]] = {}  # Untuk menyimpan status submission

    async def calculate_tax(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        Menghitung pajak berdasarkan data transaksi.
        """
        logger.info(f"CoreTax calculate_tax called with data: {data}")
        amount = data.get("amount", 0)
        tax_code = data.get("tax_code", "PPN")
        rate = await self.get_tax_rate(tax_code, data.get("date", "2025-01-01"))
        tax_amount = amount * rate
        return {
            "tax_amount": tax_amount,
            "tax_base": amount,
            "tax_rate": rate,
            "tax_code": tax_code,
            "status": "success",
            "message": "Stub calculation",
        }

    async def validate_tax_id(self, tax_id: str) -> bool:
        """
        Validasi NPWP atau tax ID.
        """
        logger.info(f"CoreTax validate_tax_id called with tax_id: {tax_id}")
        return bool(tax_id and len(tax_id) >= 5)

    async def get_tax_rate(self, tax_code: str, date: str) -> float:
        """
        Mendapatkan tarif pajak untuk kode pajak dan tanggal tertentu.
        """
        logger.info(f"CoreTax get_tax_rate called with tax_code: {tax_code}, date: {date}")
        rates = {
            "PPN": 0.11,
            "PPH21": 0.05,
            "PPH23": 0.02,
            "PPH25": 0.25,
        }
        return rates.get(tax_code, 0.11)

    # ========================================================================
    # METODE TAMBAHAN YANG DIBUTUHKAN OLEH PORT (CoreTaxPort)
    # ========================================================================

    async def submit_tax(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        Submit data pajak ke otoritas pajak.
        Menerima data dan mengembalikan ID submission.
        """
        logger.info(f"CoreTax submit_tax called with data: {data}")
        submission_id = str(uuid.uuid4())
        self._submissions[submission_id] = {
            "data": data,
            "status": "pending",
            "submitted_at": data.get("date", "2025-01-01"),
        }
        return {
            "status": "accepted",
            "id": submission_id,
            "message": "Tax data submitted successfully (stub)",
        }

    async def get_status(self, submission_id: str) -> dict[str, Any]:
        """
        Mendapatkan status submission pajak berdasarkan ID.
        """
        logger.info(f"CoreTax get_status called with submission_id: {submission_id}")
        record = self._submissions.get(submission_id)
        if record:
            return {
                "status": record["status"],
                "submission_id": submission_id,
                "data": record["data"],
            }
        return {
            "status": "not_found",
            "submission_id": submission_id,
            "message": "Submission ID not found",
        }


# ============================================================================
# ALIAS untuk kompatibilitas dengan ioc_container.py
# ============================================================================

CoreTaxImpl = CoretaxAuthorityAdapter

__all__ = [
    "CoretaxAuthorityAdapter",
    "CoreTaxImpl",
]