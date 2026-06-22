#!/usr/bin/env python3
"""
Module: sqlalchemy_approval_repository_impl.py
Layer: Infrastructure (Secondary Adapter)
Responsibility: Implementasi repository Approval (workflow persetujuan) menggunakan SQLAlchemy.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

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
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
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
        Update the status of an approval request.

        Args:
            request_id: UUID of the request.
            status: New status (must be one of "approved", "rejected", or "pending").
            approved_by: UUID of the approver.
            comments: Optional comments.

        Raises:
            ValueError: If status is not allowed.
        """
        allowed_statuses = {"approved", "rejected", "pending"}
        if status not in allowed_statuses:
            raise ValueError(f"Invalid status: {status}. Allowed: {allowed_statuses}")

        session = await self._get_session()
        stmt = (
            update(ApprovalRequestTable)
            .where(ApprovalRequestTable.id == request_id)
            .values(
                status=status,
                approved_by=approved_by,
                approved_at=datetime.now(UTC),
                comments=comments,
            )
        )
        await session.execute(stmt)

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


__all__ = ["SQLAlchemyApprovalRepository"]