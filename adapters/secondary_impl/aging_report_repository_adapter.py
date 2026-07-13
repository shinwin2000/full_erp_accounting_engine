#!/usr/bin/env python3
"""
Module: aging_report_repository_adapter.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi AgingReportRepositoryPort untuk laporan aging AR/AP.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from ports.primary.report_repository_port import AgingReportRepositoryPort

logger = logging.getLogger(__name__)


class AgingReportRepositoryAdapter(AgingReportRepositoryPort):
    """
    Implementasi AgingReportRepositoryPort yang mengembalikan dict[str, Any]
    sesuai kontrak port.
    """

    def __init__(self, session=None):
        self._session = session

    # ========================================================================
    # AgingReportRepositoryPort methods
    # ========================================================================

    async def get_ar_aging(self, legal_entity_id: UUID, as_of_date: date) -> dict[str, Any]:
        """
        Menghasilkan laporan aging untuk Account Receivable.
        Port signature: get_ar_aging(legal_entity_id: UUID, as_of_date: date) -> dict[str, Any]
        """
        # Real implementation would query invoices from DB.
        # Placeholder dengan data mock.
        mock_invoices = [
            {"due_date": date(2026, 5, 15), "outstanding": Decimal("1000")},
            {"due_date": date(2026, 4, 10), "outstanding": Decimal("500")},
            {"due_date": date(2026, 3, 1), "outstanding": Decimal("750")},
            {"due_date": date(2026, 1, 20), "outstanding": Decimal("300")},
        ]
        buckets = {
            "0-30": Decimal(0),
            "31-60": Decimal(0),
            "61-90": Decimal(0),
            ">90": Decimal(0),
        }
        for inv in mock_invoices:
            due = inv["due_date"]
            days = (as_of_date - due).days
            amount = inv["outstanding"]
            if 0 <= days <= 30:
                buckets["0-30"] += amount
            elif 31 <= days <= 60:
                buckets["31-60"] += amount
            elif 61 <= days <= 90:
                buckets["61-90"] += amount
            else:
                buckets[">90"] += amount

        return {
            "legal_entity_id": str(legal_entity_id),
            "as_of_date": as_of_date.isoformat(),
            "buckets": {k: float(v) for k, v in buckets.items()},
            "total_outstanding": float(sum(buckets.values())),
            "generated_at": datetime.utcnow().isoformat(),
        }

    async def get_ap_aging(self, legal_entity_id: UUID, as_of_date: date) -> dict[str, Any]:
        """
        Menghasilkan laporan aging untuk Account Payable.
        Port signature: get_ap_aging(legal_entity_id: UUID, as_of_date: date) -> dict[str, Any]
        """
        mock_invoices = [
            {"due_date": date(2026, 5, 15), "outstanding": Decimal("2000")},
            {"due_date": date(2026, 4, 10), "outstanding": Decimal("1200")},
            {"due_date": date(2026, 3, 1), "outstanding": Decimal("800")},
            {"due_date": date(2026, 1, 20), "outstanding": Decimal("500")},
        ]
        buckets = {
            "0-30": Decimal(0),
            "31-60": Decimal(0),
            "61-90": Decimal(0),
            ">90": Decimal(0),
        }
        for inv in mock_invoices:
            due = inv["due_date"]
            days = (as_of_date - due).days
            amount = inv["outstanding"]
            if 0 <= days <= 30:
                buckets["0-30"] += amount
            elif 31 <= days <= 60:
                buckets["31-60"] += amount
            elif 61 <= days <= 90:
                buckets["61-90"] += amount
            else:
                buckets[">90"] += amount

        return {
            "legal_entity_id": str(legal_entity_id),
            "as_of_date": as_of_date.isoformat(),
            "buckets": {k: float(v) for k, v in buckets.items()},
            "total_outstanding": float(sum(buckets.values())),
            "generated_at": datetime.utcnow().isoformat(),
        }


__all__ = ["AgingReportRepositoryAdapter"]
