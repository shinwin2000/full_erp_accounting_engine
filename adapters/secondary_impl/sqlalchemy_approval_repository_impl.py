#!/usr/bin/env python3
"""
Module: sqlalchemy_approval_repository_impl.py
Layer: Infrastructure (Secondary Adapter)
Responsibility: Implementasi repository Approval (workflow persetujuan) menggunakan SQLAlchemy.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.persistence_orm.approval_delegation_table import ApprovalDelegationTable
from infrastructure.persistence_orm.approval_matrix_table import ApprovalMatrixTable
from infrastructure.persistence_orm.approval_request_table import ApprovalRequestTable
from infrastructure.persistence_orm.approval_rule_table import ApprovalRuleTable
from ports.primary.approval_repository_port import ApprovalRepositoryPort


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

    # ========== Approval Request ==========

    async def save_request(self, request: ApprovalRequestTable) -> ApprovalRequestTable:
        """
        Persist a new approval request.

        Args:
            request: The approval request ORM object.

        Returns:
            The persisted request (with generated fields populated).
        """
        session = await self._get_session()
        session.add(request)
        await session.flush()
        return request

    async def get_request_by_id(self, request_id: uuid.UUID) -> ApprovalRequestTable | None:
        """
        Retrieve an approval request by its primary key.

        Args:
            request_id: UUID of the request.

        Returns:
            The request if found, else None.
        """
        session = await self._get_session()
        stmt = select(ApprovalRequestTable).where(ApprovalRequestTable.id == request_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_requests_by_entity(
        self, entity_type: str, entity_id: uuid.UUID
    ) -> list[ApprovalRequestTable]:
        """
        Retrieve all approval requests for a given entity, ordered by creation date descending.

        Args:
            entity_type: Type of the entity (e.g., "purchase_order").
            entity_id: UUID of the entity.

        Returns:
            List of requests (empty if none).
        """
        session = await self._get_session()
        stmt = (
            select(ApprovalRequestTable)
            .where(
                ApprovalRequestTable.entity_type == entity_type,
                ApprovalRequestTable.entity_id == entity_id,
            )
            .order_by(ApprovalRequestTable.created_at.desc())
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_pending_requests_for_user(self, user_id: uuid.UUID) -> list[ApprovalRequestTable]:
        """
        Retrieve all pending approval requests assigned to a specific user,
        ordered by priority (descending) and creation date (ascending).

        Args:
            user_id: UUID of the approver.

        Returns:
            List of pending requests.
        """
        session = await self._get_session()
        stmt = (
            select(ApprovalRequestTable)
            .where(
                ApprovalRequestTable.status == "pending",
                ApprovalRequestTable.approver_id == user_id,
            )
            .order_by(ApprovalRequestTable.priority.desc(), ApprovalRequestTable.created_at)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def update_request_status(
        self,
        request_id: uuid.UUID,
        status: str,
        approved_by: uuid.UUID,
        comments: str | None = None,
    ) -> None:
        """
        Update the status of an approval request with pessimistic locking.

        LOCKING: SELECT FOR UPDATE ensures exclusive lock on the record.

        Args:
            request_id: UUID of the request.
            status: New status (must be one of "approved", "rejected", or "pending").
            approved_by: UUID of the approver.
            comments: Optional comments.

        Raises:
            ValueError: If status is not allowed or request not found.
        """
        allowed_statuses = {"approved", "rejected", "pending"}
        if status not in allowed_statuses:
            raise ValueError(f"Invalid status: {status}. Allowed: {allowed_statuses}")

        session = await self._get_session()
        async with session.begin():
            # 1. Lock the row with SELECT FOR UPDATE
            stmt_lock = select(ApprovalRequestTable).where(
                ApprovalRequestTable.id == request_id
            ).with_for_update()
            result = await session.execute(stmt_lock)
            request = result.scalar_one_or_none()
            if not request:
                raise ValueError(f"Approval request {request_id} not found")

            # 2. Update the locked row
            request.status = status
            request.approved_by = approved_by
            request.approved_at = datetime.now(UTC)
            if comments is not None:
                request.comments = comments
            await session.flush()

    # ========== Approval Rules ==========

    async def save_rule(self, rule: ApprovalRuleTable) -> ApprovalRuleTable:
        """
        Persist a new approval rule.

        Args:
            rule: The approval rule ORM object.

        Returns:
            The persisted rule.
        """
        session = await self._get_session()
        session.add(rule)
        await session.flush()
        return rule

    async def get_rule_by_id(self, rule_id: uuid.UUID) -> ApprovalRuleTable | None:
        """
        Retrieve an approval rule by its primary key.

        Args:
            rule_id: UUID of the rule.

        Returns:
            The rule if found, else None.
        """
        session = await self._get_session()
        stmt = select(ApprovalRuleTable).where(ApprovalRuleTable.id == rule_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_rules_for_entity(
        self, entity_type: str, amount: Decimal | None = None
    ) -> list[ApprovalRuleTable]:
        """
        Retrieve applicable approval rules for a given entity type and optional monetary amount.

        Args:
            entity_type: Type of the entity.
            amount: The monetary amount to match against min_amount/max_amount.
                   If None, amount filtering is skipped.

        Returns:
            List of matching rules.

        Note:
            The amount is compared as Decimal to avoid floating-point precision issues.
        """
        session = await self._get_session()
        stmt = select(ApprovalRuleTable).where(ApprovalRuleTable.entity_type == entity_type)

        if amount is not None:
            # Ensure amount is non-negative (business rule)
            if amount < Decimal("0"):
                raise ValueError("Amount must be non-negative")

            stmt = stmt.where(
                ApprovalRuleTable.min_amount <= amount,
                ApprovalRuleTable.max_amount >= amount,
            )

        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_active_rules(self) -> list[ApprovalRuleTable]:
        """
        Retrieve all active approval rules.

        Returns:
            List of active rules.
        """
        session = await self._get_session()
        stmt = select(ApprovalRuleTable).where(ApprovalRuleTable.is_active.is_(True))
        result = await session.execute(stmt)
        return list(result.scalars().all())

    # ========== Approval Request (tambahan) ==========

    async def get_request_by_number(
        self, request_number: str, legal_entity_id: uuid.UUID | None = None
    ) -> ApprovalRequestTable | None:
        session = await self._get_session()
        stmt = select(ApprovalRequestTable).where(
            ApprovalRequestTable.request_number == request_number
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
        conditions = [ApprovalRequestTable.legal_entity_id == legal_entity_id]
        if entity_type:
            conditions.append(ApprovalRequestTable.entity_type == entity_type)
        if status:
            conditions.append(ApprovalRequestTable.status == status)
        if requester_id:
            conditions.append(ApprovalRequestTable.requested_by == requester_id)
        if approver_id:
            conditions.append(ApprovalRequestTable.approver_id == approver_id)
        if start_date:
            conditions.append(ApprovalRequestTable.created_at >= start_date)
        if end_date:
            conditions.append(ApprovalRequestTable.created_at <= end_date)

        count_stmt = select(func.count()).select_from(ApprovalRequestTable).where(*conditions)
        total = (await session.execute(count_stmt)).scalar_one()

        stmt = (
            select(ApprovalRequestTable)
            .where(*conditions)
            .order_by(ApprovalRequestTable.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all()), total

    # ========== Approval Matrix ==========

    async def save_matrix(self, matrix: ApprovalMatrixTable) -> ApprovalMatrixTable:
        session = await self._get_session()
        session.add(matrix)
        await session.flush()
        return matrix

    async def get_matrix_by_id(
        self, matrix_id: uuid.UUID, legal_entity_id: uuid.UUID | None = None
    ) -> ApprovalMatrixTable | None:
        session = await self._get_session()
        stmt = select(ApprovalMatrixTable).where(ApprovalMatrixTable.id == matrix_id)
        if legal_entity_id:
            stmt = stmt.where(ApprovalMatrixTable.legal_entity_id == legal_entity_id)
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
            ApprovalMatrixTable.legal_entity_id == legal_entity_id
        )
        if entity_type:
            stmt = stmt.where(ApprovalMatrixTable.entity_type == entity_type)
        if is_active is not None:
            stmt = stmt.where(ApprovalMatrixTable.is_active == is_active)
        stmt = stmt.order_by(ApprovalMatrixTable.matrix_code)
        result = await session.execute(stmt)
        return list(result.scalars().all())

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
        stmt = select(ApprovalDelegationTable).where(ApprovalDelegationTable.id == delegation_id)
        if legal_entity_id:
            stmt = stmt.where(ApprovalDelegationTable.legal_entity_id == legal_entity_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    # ========== Statistics ==========

    async def get_statistics(
        self,
        legal_entity_id: uuid.UUID,
        start_date: date | None = None,
        end_date: date | None = None,
        entity_type: str | None = None,
    ) -> dict:
        session = await self._get_session()
        conditions = [ApprovalRequestTable.legal_entity_id == legal_entity_id]
        if start_date:
            conditions.append(ApprovalRequestTable.created_at >= start_date)
        if end_date:
            conditions.append(ApprovalRequestTable.created_at <= end_date)
        if entity_type:
            conditions.append(ApprovalRequestTable.entity_type == entity_type)

        # Hitung per status sekaligus dalam satu query
        stmt = (
            select(ApprovalRequestTable.status, func.count())
            .where(*conditions)
            .group_by(ApprovalRequestTable.status)
        )
        result = await session.execute(stmt)
        counts_by_status = {row[0]: row[1] for row in result.all()}

        total = sum(counts_by_status.values())

        # Hitung per entity_type
        stmt_type = (
            select(ApprovalRequestTable.entity_type, func.count())
            .where(*conditions)
            .group_by(ApprovalRequestTable.entity_type)
        )
        result_type = await session.execute(stmt_type)
        by_entity_type = {row[0]: row[1] for row in result_type.all()}

        # Hitung per level saat ini
        stmt_level = (
            select(ApprovalRequestTable.current_level, func.count())
            .where(*conditions)
            .group_by(ApprovalRequestTable.current_level)
        )
        result_level = await session.execute(stmt_level)
        by_level = {str(row[0]): row[1] for row in result_level.all()}

        # Rata-rata waktu approval (jam) untuk request yang sudah selesai (approved/rejected)
        avg_stmt = select(
            func.avg(
                func.extract("epoch", ApprovalRequestTable.approved_at)
                - func.extract("epoch", ApprovalRequestTable.created_at)
            )
        ).where(*conditions, ApprovalRequestTable.approved_at.is_not(None))
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
