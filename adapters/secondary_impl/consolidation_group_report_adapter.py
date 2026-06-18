#!/usr/bin/env python3
"""
Adapter: Consolidation Group Report
Layer: Adapters (Secondary Implementation)

Adapter untuk menghasilkan laporan konsolidasi grup perusahaan.
Menggunakan service_consolidation dan repository yang sudah ada.
"""
from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from application.service_layer.service_consolidation import ConsolidationService

from infrastructure.telemetry.structured_json_logging import get_logger
from ports.primary.consolidation_group_report import ConsolidationGroupReportPort

logger = get_logger(__name__)

class ConsolidationGroupReportAdapter(ConsolidationGroupReportPort):
    """
    Adapter untuk laporan konsolidasi menggunakan service ConsolidationService.
    """
    def __init__(self):
        self._service: ConsolidationService | None = None

    async def _get_service(self) -> ConsolidationService:
        if self._service is None:
            container = __import__('bootstrap.dependency_container.ioc_container', fromlist=['get_container']).get_container()
            self._service = container.resolve(ConsolidationService)
        return self._service

    async def generate_report(
        self,
        group_id: UUID,
        period_start: date,
        period_end: date,
        include_intercompany: bool = True,
        include_nci: bool = True,
    ) -> dict[str, Any]:
        """
        Menghasilkan laporan konsolidasi.
        """
        service = await self._get_service()
        result = await service.get_consolidated_report(
            group_id=group_id,
            start_date=period_start,
            end_date=period_end,
            include_intercompany=include_intercompany,
            include_nci=include_nci,
        )
        logger.info(f"Consolidation report generated for group {group_id}")
        return result

    async def get_intercompany_balances(self, group_id: UUID, as_of_date: date) -> list[dict]:
        service = await self._get_service()
        return await service.get_intercompany_balances(group_id, as_of_date)

__all__ = ["ConsolidationGroupReportAdapter"]
