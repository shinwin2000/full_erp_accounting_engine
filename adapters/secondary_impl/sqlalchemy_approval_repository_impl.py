#!/usr/bin/env python3
"""
Module: sqlalchemy_approval_repository_impl.py
Layer: Infrastructure (Secondary Adapter)
Responsibility: Implementasi repository Approval (workflow persetujuan) menggunakan SQLAlchemy.

Catatan transaksi:
    Repository ini HANYA melakukan flush (tidak commit). Commit/rollback dilakukan oleh
    pemilik session -- pada request HTTP itu adalah dependency ``get_async_session()``
    (lihat ``get_approval_svc`` di fastapi_approval_router.py).

Catatan soft-delete:
    Query ``select()`` gaya 2.0 TIDAK terkena listener auto-filter ``deleted_at`` di
    base_model (listener itu hanya untuk legacy ``Query``), sehingga setiap query di
    sini memfilter ``deleted_at IS NULL`` secara eksplisit.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import bindparam, func, select, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.persistence_orm.approval_delegation_table import ApprovalDelegationTable
from infrastructure.persistence_orm.approval_matrix_table import ApprovalMatrixTable
from infrastructure.persistence_orm.approval_request_table import ApprovalRequestTable
from infrastructure.persistence_orm.approval_rule_table import ApprovalRuleTable
from ports.primary.approval_repository_port import ApprovalRepositoryPort


def _date_conditions(column: Any, start: date | datetime | None, end: date | datetime | None) -> list[Any]:
    """Bangun kondisi rentang waktu untuk kolom timestamptz.

    - ``date``     : start = awal hari (UTC), end = AKHIR hari (eksklusif hari berikutnya),
                     sehingga hari terakhir ikut terhitung.
    - ``datetime`` : dipakai apa adanya (naive dianggap UTC); end inklusif.
    """
    conditions: list[Any] = []
    if start is not None:
        if isinstance(start, datetime):
            lower = start if start.tzinfo else start.replace(tzinfo=UTC)
        else:
            lower = datetime.combine(start, time.min, tzinfo=UTC)
        conditions.append(column >= lower)
    if end is not None:
        if isinstance(end, datetime):
            upper = end if end.tzinfo else end.replace(tzinfo=UTC)
            conditions.append(column <= upper)
        else:
            upper = datetime.combine(end + timedelta(days=1), time.min, tzinfo=UTC)
            conditions.append(column < upper)
    return conditions


class SQLAlchemyApprovalRepository(ApprovalRepositoryPort):
    """Repository implementation for approval workflows using SQLAlchemy async session."""

    __slots__ = ("_session",)

    def __init__(self, session: AsyncSession | None = None) -> None:
        self._session = session

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session_direct

            self._session = await get_async_session_direct()
        return self._session

    async def get_active_user_ids(self, user_ids: list[uuid.UUID]) -> set[uuid.UUID]:
        if not user_ids:
            return set()
        session = await self._get_session()
        stmt = text(
            "SELECT id FROM iam_user "
            "WHERE id = ANY(:ids) AND is_active IS TRUE AND deleted_at IS NULL"
        ).bindparams(bindparam("ids", value=list(user_ids), type_=ARRAY(PGUUID(as_uuid=True))))
        result = await session.execute(stmt)
        return {row[0] for row in result.all()}

    async def lock_entity_for_submit(
        self, entity_type: str, entity_id: uuid.UUID, legal_entity_id: uuid.UUID
    ) -> None:
        session = await self._get_session()
        # Advisory lock level-transaksi (PostgreSQL >= 11). Submit paralel untuk entity yang
        # sama diserialkan; yang kedua baru lanjut setelah yang pertama commit/rollback.
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"approval-submit:{legal_entity_id}:{entity_type}:{entity_id}"},
        )

    async def flush_and_refresh(self, obj: Any) -> Any:
        session = await self._get_session()
        await session.flush()
        await session.refresh(obj)
        return obj

    # ========== Approval Request ==========

    async def save_request(self, request: ApprovalRequestTable) -> ApprovalRequestTable:
        """Persist a new approval request (flush + refresh agar kolom server-default terisi)."""
        session = await self._get_session()
        session.add(request)
        await session.flush()
        await session.refresh(request)
        return request

    async def get_request_by_id(
        self, request_id: uuid.UUID, for_update: bool = False
    ) -> ApprovalRequestTable | None:
        session = await self._get_session()
        stmt = select(ApprovalRequestTable).where(
            ApprovalRequestTable.id == request_id,
            ApprovalRequestTable.deleted_at.is_(None),
        )
        if for_update:
            # Kunci baris + paksa baca ulang state terbaru dari DB.
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_requests_by_entity(
        self,
        entity_type: str,
        entity_id: uuid.UUID,
        legal_entity_id: uuid.UUID | None = None,
    ) -> list[ApprovalRequestTable]:
        session = await self._get_session()
        stmt = select(ApprovalRequestTable).where(
            ApprovalRequestTable.entity_type == entity_type,
            ApprovalRequestTable.entity_id == entity_id,
            ApprovalRequestTable.deleted_at.is_(None),
        )
        if legal_entity_id is not None:
            stmt = stmt.where(ApprovalRequestTable.legal_entity_id == legal_entity_id)
        stmt = stmt.order_by(ApprovalRequestTable.created_at.desc())
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_pending_requests_for_user(
        self,
        user_id: uuid.UUID,
        legal_entity_id: uuid.UUID | None = None,
        extra_approver_ids: list[uuid.UUID] | None = None,
    ) -> list[ApprovalRequestTable]:
        session = await self._get_session()
        approver_ids = [user_id, *(extra_approver_ids or [])]
        stmt = select(ApprovalRequestTable).where(
            ApprovalRequestTable.status == "pending",
            ApprovalRequestTable.approver_id.in_(approver_ids),
            ApprovalRequestTable.deleted_at.is_(None),
        )
        if legal_entity_id is not None:
            stmt = stmt.where(ApprovalRequestTable.legal_entity_id == legal_entity_id)
        # priority: 1 = tertinggi (lihat ApprovalRequestTable) -> ASC. Lalu yang paling lama dulu.
        stmt = stmt.order_by(ApprovalRequestTable.priority.asc(), ApprovalRequestTable.created_at.asc())
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def update_request_status(
        self,
        request_id: uuid.UUID,
        status: str,
        approved_by: uuid.UUID,
        comments: str | None = None,
    ) -> None:
        """Update status request dengan pessimistic lock (SELECT ... FOR UPDATE).

        Transaksi dimiliki pemanggil/session (tidak memakai ``session.begin()`` sendiri,
        yang akan error bila session sudah autobegin).

        Raises:
            ValueError: status tidak diizinkan atau request tidak ditemukan.
        """
        allowed_statuses = {"approved", "rejected", "pending"}
        if status not in allowed_statuses:
            raise ValueError(f"Invalid status: {status}. Allowed: {allowed_statuses}")

        request = await self.get_request_by_id(request_id, for_update=True)
        if not request:
            raise ValueError(f"Approval request {request_id} not found")

        request.status = status
        if status == "pending":
            request.approved_by = None
            request.approved_at = None
        else:
            request.approved_by = approved_by
            request.approved_at = datetime.now(UTC)
        if comments is not None:
            request.approval_comments = comments
        request.increment_version()
        await self.flush_and_refresh(request)

    # ========== Approval Rules ==========

    async def save_rule(self, rule: ApprovalRuleTable) -> ApprovalRuleTable:
        session = await self._get_session()
        session.add(rule)
        await session.flush()
        return rule

    async def get_rule_by_id(self, rule_id: uuid.UUID) -> ApprovalRuleTable | None:
        session = await self._get_session()
        stmt = select(ApprovalRuleTable).where(
            ApprovalRuleTable.id == rule_id, ApprovalRuleTable.deleted_at.is_(None)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_rules_for_entity(
        self, entity_type: str, amount: Decimal | None = None
    ) -> list[ApprovalRuleTable]:
        """Rule AKTIF untuk entity_type (dan amount bila diberikan), prioritas tertinggi dulu."""
        session = await self._get_session()
        stmt = select(ApprovalRuleTable).where(
            ApprovalRuleTable.entity_type == entity_type,
            ApprovalRuleTable.is_active.is_(True),
            ApprovalRuleTable.deleted_at.is_(None),
        )
        if amount is not None:
            if amount < Decimal("0"):
                raise ValueError("Amount must be non-negative")
            stmt = stmt.where(
                ApprovalRuleTable.min_amount <= amount,
                ApprovalRuleTable.max_amount >= amount,
            )
        stmt = stmt.order_by(ApprovalRuleTable.priority.desc(), ApprovalRuleTable.approval_level)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_active_rules(self) -> list[ApprovalRuleTable]:
        session = await self._get_session()
        stmt = select(ApprovalRuleTable).where(
            ApprovalRuleTable.is_active.is_(True), ApprovalRuleTable.deleted_at.is_(None)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    # ========== Approval Request (tambahan) ==========

    async def get_request_by_number(
        self, request_number: str, legal_entity_id: uuid.UUID | None = None
    ) -> ApprovalRequestTable | None:
        session = await self._get_session()
        stmt = select(ApprovalRequestTable).where(
            ApprovalRequestTable.request_number == request_number,
            ApprovalRequestTable.deleted_at.is_(None),
        )
        if legal_entity_id:
            stmt = stmt.where(ApprovalRequestTable.legal_entity_id == legal_entity_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_requests(
        self,
        legal_entity_id: uuid.UUID,
        entity_type: str | None = None,
        status: str | None = None,
        requester_id: uuid.UUID | None = None,
        approver_id: uuid.UUID | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[ApprovalRequestTable], int]:
        session = await self._get_session()
        conditions: list[Any] = [
            ApprovalRequestTable.legal_entity_id == legal_entity_id,
            ApprovalRequestTable.deleted_at.is_(None),
        ]
        if entity_type:
            conditions.append(ApprovalRequestTable.entity_type == entity_type)
        if status:
            conditions.append(ApprovalRequestTable.status == status)
        if requester_id:
            conditions.append(ApprovalRequestTable.requested_by == requester_id)
        if approver_id:
            conditions.append(ApprovalRequestTable.approver_id == approver_id)
        conditions.extend(_date_conditions(ApprovalRequestTable.created_at, start_date, end_date))

        count_stmt = select(func.count()).select_from(ApprovalRequestTable).where(*conditions)
        total = (await session.execute(count_stmt)).scalar_one()

        stmt = (
            select(ApprovalRequestTable)
            .where(*conditions)
            .order_by(ApprovalRequestTable.created_at.desc(), ApprovalRequestTable.id)
            .offset((max(page, 1) - 1) * page_size)
            .limit(page_size)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all()), total

    # ========== Approval Matrix ==========

    async def save_matrix(self, matrix: ApprovalMatrixTable) -> ApprovalMatrixTable:
        session = await self._get_session()
        session.add(matrix)
        await session.flush()
        await session.refresh(matrix)
        return matrix

    async def get_matrix_by_id(
        self, matrix_id: uuid.UUID, legal_entity_id: uuid.UUID | None = None
    ) -> ApprovalMatrixTable | None:
        session = await self._get_session()
        stmt = select(ApprovalMatrixTable).where(
            ApprovalMatrixTable.id == matrix_id, ApprovalMatrixTable.deleted_at.is_(None)
        )
        if legal_entity_id:
            stmt = stmt.where(ApprovalMatrixTable.legal_entity_id == legal_entity_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_matrix_by_code(
        self, matrix_code: str, legal_entity_id: uuid.UUID
    ) -> ApprovalMatrixTable | None:
        session = await self._get_session()
        # Sengaja TANPA filter deleted_at: unique constraint tetap berlaku untuk baris soft-deleted.
        stmt = select(ApprovalMatrixTable).where(
            ApprovalMatrixTable.matrix_code == matrix_code,
            ApprovalMatrixTable.legal_entity_id == legal_entity_id,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_matrices(
        self,
        legal_entity_id: uuid.UUID,
        entity_type: str | None = None,
        is_active: bool | None = None,
    ) -> list[ApprovalMatrixTable]:
        session = await self._get_session()
        stmt = select(ApprovalMatrixTable).where(
            ApprovalMatrixTable.legal_entity_id == legal_entity_id,
            ApprovalMatrixTable.deleted_at.is_(None),
        )
        if entity_type:
            stmt = stmt.where(ApprovalMatrixTable.entity_type == entity_type)
        if is_active is not None:
            stmt = stmt.where(ApprovalMatrixTable.is_active == is_active)
        stmt = stmt.order_by(ApprovalMatrixTable.matrix_code)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def count_open_requests_for_matrix(
        self, matrix_id: uuid.UUID, legal_entity_id: uuid.UUID
    ) -> int:
        session = await self._get_session()
        stmt = (
            select(func.count())
            .select_from(ApprovalRequestTable)
            .where(
                ApprovalRequestTable.approval_matrix_id == matrix_id,
                ApprovalRequestTable.legal_entity_id == legal_entity_id,
                ApprovalRequestTable.status.in_(("pending", "escalated")),
                ApprovalRequestTable.deleted_at.is_(None),
            )
        )
        return int((await session.execute(stmt)).scalar_one())

    async def delete_matrix(self, matrix_id: uuid.UUID, legal_entity_id: uuid.UUID) -> bool:
        session = await self._get_session()
        matrix = await self.get_matrix_by_id(matrix_id, legal_entity_id)
        if not matrix:
            return False
        await session.delete(matrix)
        await session.flush()
        return True

    # ========== Approval Delegation ==========

    async def save_delegation(self, delegation: ApprovalDelegationTable) -> ApprovalDelegationTable:
        session = await self._get_session()
        session.add(delegation)
        await session.flush()
        await session.refresh(delegation)
        return delegation

    async def list_delegations_by_delegator(
        self,
        delegator_id: uuid.UUID,
        legal_entity_id: uuid.UUID,
        is_active: bool | None = None,
    ) -> list[ApprovalDelegationTable]:
        session = await self._get_session()
        stmt = select(ApprovalDelegationTable).where(
            ApprovalDelegationTable.delegator_id == delegator_id,
            ApprovalDelegationTable.legal_entity_id == legal_entity_id,
            ApprovalDelegationTable.deleted_at.is_(None),
        )
        if is_active is not None:
            stmt = stmt.where(ApprovalDelegationTable.is_active == is_active)
        stmt = stmt.order_by(ApprovalDelegationTable.created_at.desc())
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_delegation_by_id(
        self, delegation_id: uuid.UUID, legal_entity_id: uuid.UUID | None = None
    ) -> ApprovalDelegationTable | None:
        session = await self._get_session()
        stmt = select(ApprovalDelegationTable).where(
            ApprovalDelegationTable.id == delegation_id,
            ApprovalDelegationTable.deleted_at.is_(None),
        )
        if legal_entity_id:
            stmt = stmt.where(ApprovalDelegationTable.legal_entity_id == legal_entity_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_delegation(
        self,
        delegator_id: uuid.UUID,
        delegate_to_id: uuid.UUID,
        legal_entity_id: uuid.UUID,
        on_date: date,
    ) -> ApprovalDelegationTable | None:
        session = await self._get_session()
        stmt = (
            select(ApprovalDelegationTable)
            .where(
                ApprovalDelegationTable.delegator_id == delegator_id,
                ApprovalDelegationTable.delegate_to_id == delegate_to_id,
                ApprovalDelegationTable.legal_entity_id == legal_entity_id,
                ApprovalDelegationTable.is_active.is_(True),
                ApprovalDelegationTable.deleted_at.is_(None),
                ApprovalDelegationTable.start_date <= on_date,
                ApprovalDelegationTable.end_date >= on_date,
            )
            .order_by(ApprovalDelegationTable.created_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_active_delegator_ids(
        self, delegate_to_id: uuid.UUID, legal_entity_id: uuid.UUID, on_date: date
    ) -> list[uuid.UUID]:
        session = await self._get_session()
        stmt = select(ApprovalDelegationTable.delegator_id).where(
            ApprovalDelegationTable.delegate_to_id == delegate_to_id,
            ApprovalDelegationTable.legal_entity_id == legal_entity_id,
            ApprovalDelegationTable.is_active.is_(True),
            ApprovalDelegationTable.deleted_at.is_(None),
            ApprovalDelegationTable.start_date <= on_date,
            ApprovalDelegationTable.end_date >= on_date,
        )
        result = await session.execute(stmt)
        return list({row[0] for row in result.all()})

    # ========== Statistics ==========

    async def get_statistics(
        self,
        legal_entity_id: uuid.UUID,
        start_date: date | None = None,
        end_date: date | None = None,
        entity_type: str | None = None,
    ) -> dict[str, Any]:
        session = await self._get_session()
        conditions: list[Any] = [
            ApprovalRequestTable.legal_entity_id == legal_entity_id,
            ApprovalRequestTable.deleted_at.is_(None),
        ]
        conditions.extend(_date_conditions(ApprovalRequestTable.created_at, start_date, end_date))
        if entity_type:
            conditions.append(ApprovalRequestTable.entity_type == entity_type)

        stmt = (
            select(ApprovalRequestTable.status, func.count())
            .where(*conditions)
            .group_by(ApprovalRequestTable.status)
        )
        counts_by_status = {row[0]: row[1] for row in (await session.execute(stmt)).all()}
        total = sum(counts_by_status.values())

        stmt_type = (
            select(ApprovalRequestTable.entity_type, func.count())
            .where(*conditions)
            .group_by(ApprovalRequestTable.entity_type)
        )
        by_entity_type = {row[0]: row[1] for row in (await session.execute(stmt_type)).all()}

        stmt_level = (
            select(ApprovalRequestTable.current_level, func.count())
            .where(*conditions)
            .group_by(ApprovalRequestTable.current_level)
        )
        by_level = {str(row[0]): row[1] for row in (await session.execute(stmt_level)).all()}

        # Rata-rata waktu keputusan (jam) hanya untuk request yang sudah diputuskan.
        avg_stmt = select(
            func.avg(
                func.extract("epoch", ApprovalRequestTable.approved_at)
                - func.extract("epoch", ApprovalRequestTable.created_at)
            )
        ).where(
            *conditions,
            ApprovalRequestTable.status.in_(("approved", "rejected")),
            ApprovalRequestTable.approved_at.is_not(None),
        )
        avg_seconds = (await session.execute(avg_stmt)).scalar_one_or_none()
        avg_hours = float(avg_seconds) / 3600 if avg_seconds is not None else None

        return {
            "total_requests": total,
            "pending_requests": counts_by_status.get("pending", 0),
            "approved_requests": counts_by_status.get("approved", 0),
            "rejected_requests": counts_by_status.get("rejected", 0),
            "escalated_requests": counts_by_status.get("escalated", 0),
            "expired_requests": counts_by_status.get("expired", 0),
            "average_approval_time_hours": avg_hours,
            "by_entity_type": by_entity_type,
            "by_level": by_level,
        }


__all__ = ["SQLAlchemyApprovalRepository"]
