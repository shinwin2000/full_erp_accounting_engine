#!/usr/bin/env python3
"""
Module: approval_entity_gateway_impl.py
Layer: Adapters (Secondary Impl)
Responsibility: Gateway sinkronisasi status approval ke tabel entity terkait
                (journal_header, ap_invoice, ar_invoice, ap_payment, ar_payment,
                purchase_order, sales_order, budget).

Aturan status per entity mengikuti CHECK constraint masing-masing tabel:
    journal_header : draft -> submitted -> approved -> posted -> reversed / cancelled
                     * approve  -> 'approved'
                     * reject   -> 'draft'   (bukan 'rejected')
                     * cancel   -> 'cancelled'
    entity lain    : status 'approved' / 'rejected' (dicek per tabel via _STATUS_MAP)

Design:
    - Constructor: ApprovalEntityGateway(session, container)
    - Best-effort: kegagalan sinkronisasi TIDAK menggagalkan approval utama;
      hanya dicatat sebagai warning.
    - Tidak commit; commit/rollback ditangani session request-scoped di router.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _EntityMeta:
    table: str
    status_col: str
    approved_value: str
    rejected_value: str
    cancelled_value: str


# Pemetaan entity_type -> meta tabel & nilai status.
# CATATAN: nilai disesuaikan dengan CHECK constraint tiap tabel. Untuk journal_header,
# reject mengembalikan status ke 'draft' (lihat journal_header_table.py baris 274-276).
_ENTITY_TABLE_MAP: dict[str, _EntityMeta] = {
    "journal": _EntityMeta(
        table="journal_header",
        status_col="status",
        approved_value="approved",
        rejected_value="draft",
        cancelled_value="cancelled",
    ),
    "ap_invoice": _EntityMeta(
        table="ap_invoice",
        status_col="status",
        approved_value="approved",
        rejected_value="rejected",
        cancelled_value="cancelled",
    ),
    "ar_invoice": _EntityMeta(
        table="ar_invoice",
        status_col="status",
        approved_value="approved",
        rejected_value="rejected",
        cancelled_value="cancelled",
    ),
    # 'payment' ambigu: ap_payment vs ar_payment. Default ke ap_payment.
    # Bila perlu membedakan, tambahkan entity_type baru di ENTITY_TYPES + CHECK constraint.
    "payment": _EntityMeta(
        table="ap_payment",
        status_col="status",
        approved_value="approved",
        rejected_value="rejected",
        cancelled_value="cancelled",
    ),
    "purchase_order": _EntityMeta(
        table="purchase_order",
        status_col="status",
        approved_value="approved",
        rejected_value="rejected",
        cancelled_value="cancelled",
    ),
    "sales_order": _EntityMeta(
        table="sales_order",
        status_col="status",
        approved_value="approved",
        rejected_value="rejected",
        cancelled_value="cancelled",
    ),
    "budget": _EntityMeta(
        table="budget",
        status_col="status",
        approved_value="approved",
        rejected_value="rejected",
        cancelled_value="cancelled",
    ),
    # 'master_data' tidak punya tabel tunggal; sinkronisasi dilewati (warning).
}


class ApprovalEntityGateway:
    """Gateway sinkronisasi status approval ke entity terkait."""

    def __init__(self, session: AsyncSession, container: Any | None = None) -> None:
        self._session = session
        self._container = container

    # ------------------------------------------------------------------ #
    # API publik yang dipanggil ApprovalService
    # ------------------------------------------------------------------ #

    async def on_approved(
        self,
        *,
        entity_type: str,
        entity_id: UUID,
        approval_request_id: UUID | None = None,
        actor_id: UUID | None = None,
        notes: str | None = None,
    ) -> bool:
        meta = self._lookup(entity_type)
        if meta is None:
            return False
        return await self._apply_status(
            meta=meta,
            entity_type=entity_type,
            entity_id=entity_id,
            new_status=meta.approved_value,
            approval_request_id=approval_request_id,
            actor_id=actor_id,
            notes=notes,
        )

    async def on_rejected(
        self,
        *,
        entity_type: str,
        entity_id: UUID,
        approval_request_id: UUID | None = None,
        actor_id: UUID | None = None,
        notes: str | None = None,
    ) -> bool:
        meta = self._lookup(entity_type)
        if meta is None:
            return False
        return await self._apply_status(
            meta=meta,
            entity_type=entity_type,
            entity_id=entity_id,
            new_status=meta.rejected_value,
            approval_request_id=approval_request_id,
            actor_id=actor_id,
            notes=notes,
        )

    async def on_cancelled(
        self,
        *,
        entity_type: str,
        entity_id: UUID,
        approval_request_id: UUID | None = None,
        actor_id: UUID | None = None,
        notes: str | None = None,
    ) -> bool:
        meta = self._lookup(entity_type)
        if meta is None:
            return False
        return await self._apply_status(
            meta=meta,
            entity_type=entity_type,
            entity_id=entity_id,
            new_status=meta.cancelled_value,
            approval_request_id=approval_request_id,
            actor_id=actor_id,
            notes=notes,
        )

    async def sync_entity_status(
        self,
        *,
        entity_type: str,
        entity_id: UUID,
        status: str,
        approval_request_id: UUID | None = None,
        actor_id: UUID | None = None,
        notes: str | None = None,
    ) -> bool:
        """Entry point generik bila pemanggil ingin menulis status spesifik."""
        meta = self._lookup(entity_type)
        if meta is None:
            return False
        return await self._apply_status(
            meta=meta,
            entity_type=entity_type,
            entity_id=entity_id,
            new_status=status,
            approval_request_id=approval_request_id,
            actor_id=actor_id,
            notes=notes,
        )

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #

    def _lookup(self, entity_type: str) -> _EntityMeta | None:
        meta = _ENTITY_TABLE_MAP.get(entity_type)
        if meta is None:
            logger.warning(
                "ApprovalEntityGateway: entity_type '%s' tidak punya tabel target, "
                "sinkronisasi dilewati",
                entity_type,
            )
        return meta

    async def _apply_status(
        self,
        *,
        meta: _EntityMeta,
        entity_type: str,
        entity_id: UUID,
        new_status: str,
        approval_request_id: UUID | None,
        actor_id: UUID | None,
        notes: str | None,
    ) -> bool:
        stmt = text(
            f"UPDATE {meta.table} "
            f"SET {meta.status_col} = :status "
            f"WHERE id = :entity_id"
        )
        try:
            result = await self._session.execute(
                stmt, {"status": new_status, "entity_id": str(entity_id)}
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "ApprovalEntityGateway: gagal update %s id=%s -> %s: %s",
                meta.table, entity_id, new_status, exc,
            )
            return False

        if result.rowcount == 0:
            logger.warning(
                "ApprovalEntityGateway: %s id=%s tidak ditemukan (rowcount=0)",
                meta.table, entity_id,
            )
            return False

        logger.info(
            "ApprovalEntityGateway: %s id=%s -> %s (entity_type=%s, request=%s, actor=%s)",
            meta.table, entity_id, new_status, entity_type,
            approval_request_id, actor_id,
        )
        return True
    