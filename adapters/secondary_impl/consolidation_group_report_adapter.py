#!/usr/bin/env python3
"""
Adapter: Consolidation Group Report
Layer: Adapters (Secondary Implementation)

Adapter untuk menghasilkan laporan konsolidasi grup perusahaan.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional
from uuid import UUID

from infrastructure.telemetry.structured_json_logging import get_logger
from ports.primary.consolidation_group_report import ConsolidationGroupReportPort

logger = get_logger(__name__)


class ConsolidationGroupReportAdapter(ConsolidationGroupReportPort):
    """
    Adapter untuk laporan konsolidasi.
    Menerima service melalui konstruktor (dependency injection).
    """

    def __init__(self, consolidation_service: Optional[Any] = None):
        """
        Args:
            consolidation_service: Instance service konsolidasi (dari application layer).
                                   Jika None, akan diambil dari container yang diinjeksi.
        """
        self._service = consolidation_service

    def set_service(self, service: Any) -> None:
        """Set service setelah konstruksi (untuk kasus where container not available)."""
        self._service = service

    async def _get_service(self):
        """Ambil service yang sudah diinjeksi. Jika belum ada, raise error jelas."""
        if self._service is None:
            raise RuntimeError(
                "ConsolidationService belum di-set. "
                "Pastikan untuk memanggil set_service() atau memberikan service di konstruktor."
            )
        return self._service

    async def get_nci_breakdown(self, group_id: UUID) -> dict[str, Any]:
        service = await self._get_service()
        if hasattr(service, "get_nci_breakdown"):
            return await service.get_nci_breakdown(group_id)
        return {"group_id": str(group_id), "nci": []}

    async def get_elimination_entries(self, group_id: UUID) -> list[dict[str, Any]]:
        service = await self._get_service()
        if hasattr(service, "get_elimination_entries"):
            return await service.get_elimination_entries(group_id)
        return []

    async def get_consolidated_balance_sheet(self, group_id: UUID) -> dict[str, Any]:
        service = await self._get_service()
        if hasattr(service, "get_consolidated_balance_sheet"):
            return await service.get_consolidated_balance_sheet(group_id)
        return {"group_id": str(group_id), "balance_sheet": {}}

    async def get_entity_contribution(self, group_id: UUID) -> dict[str, Any]:
        service = await self._get_service()
        if hasattr(service, "get_entity_contribution"):
            return await service.get_entity_contribution(group_id)
        return {"group_id": str(group_id), "contributions": []}

    async def get_consolidated_income_statement(self, group_id: UUID) -> dict[str, Any]:
        service = await self._get_service()
        if hasattr(service, "get_consolidated_income_statement"):
            return await service.get_consolidated_income_statement(group_id)
        return {"group_id": str(group_id), "income_statement": {}}

    async def get_consolidation_summary(self, group_id: UUID) -> dict[str, Any]:
        service = await self._get_service()
        if hasattr(service, "get_consolidation_summary"):
            return await service.get_consolidation_summary(group_id)
        return {"group_id": str(group_id), "summary": {}}

    async def get_consolidated_cash_flow(self, group_id: UUID) -> dict[str, Any]:
        service = await self._get_service()
        if hasattr(service, "get_consolidated_cash_flow"):
            return await service.get_consolidated_cash_flow(group_id)
        return {"group_id": str(group_id), "cash_flow": {}}

    async def validate_consolidation(self, group_id: UUID) -> dict[str, Any]:
        service = await self._get_service()
        if hasattr(service, "validate_consolidation"):
            return await service.validate_consolidation(group_id)
        return {"valid": True, "errors": []}

    # Method tambahan
    async def generate_report(
        self,
        group_id: UUID,
        period_start: date,
        period_end: date,
        include_intercompany: bool = True,
        include_nci: bool = True,
    ) -> dict[str, Any]:
        service = await self._get_service()
        if hasattr(service, "get_consolidated_report"):
            return await service.get_consolidated_report(
                group_id=group_id,
                start_date=period_start,
                end_date=period_end,
                include_intercompany=include_intercompany,
                include_nci=include_nci,
            )
        return {"group_id": str(group_id), "report": {}}

    async def get_intercompany_balances(self, group_id: UUID, as_of_date: date) -> list[dict]:
        service = await self._get_service()
        if hasattr(service, "get_intercompany_balances"):
            return await service.get_intercompany_balances(group_id, as_of_date)
        return []


__all__ = ["ConsolidationGroupReportAdapter"]