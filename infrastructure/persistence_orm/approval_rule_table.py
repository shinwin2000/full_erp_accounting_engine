#!/usr/bin/env python3
"""
Module: approval_rule_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Model untuk menyimpan aturan approval (workflow rules).
               Mendukung conditional rules berdasarkan entity type, amount,
               department, dan approval matrix (single/multi-level).
Dependencies:
- sqlalchemy, uuid, decimal, datetime
- base_model, LegalEntityMixin, TimestampMixin, SoftDeleteMixin, VersionMixin
Audit: Perubahan rule dicatat di event store.
"""

from __future__ import annotations
from uuid import UUID

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence_orm.base_model import (
    Base,
    LegalEntityMixin,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)


class ApprovalRuleTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    """
    Model untuk tabel approval rule (aturan persetujuan).
    """

    __tablename__ = "approval_rule"
    __table_args__ = (
        UniqueConstraint(
            "rule_code", "legal_entity_id", name="uq_approval_rule_code_legal_entity"
        ),
        CheckConstraint(
            "rule_code IS NOT NULL AND rule_code != ''", name="ck_approval_rule_code"
        ),
        CheckConstraint(
            "entity_type IN ('journal', 'ap_invoice', 'ar_invoice', 'payment', 'purchase_order', 'sales_order', 'budget', 'master_data')",
            name="ck_approval_rule_entity_type",
        ),
        CheckConstraint("min_amount >= 0", name="ck_approval_rule_min_amount_nonneg"),
        CheckConstraint("max_amount >= min_amount", name="ck_approval_rule_max_amount_ge_min"),
        CheckConstraint(
            "approval_level IN (1, 2, 3, 4, 5)", name="ck_approval_rule_level"
        ),
        CheckConstraint(
            "action IN ('approve', 'reject', 'escalate', 'require_dual')",
            name="ck_approval_rule_action",
        ),
        Index("idx_approval_rule_entity_type", "entity_type"),
        Index("idx_approval_rule_legal_entity", "legal_entity_id"),
        Index("idx_approval_rule_is_active", "is_active"),
        Index("idx_approval_rule_priority", "priority"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Identifikasi
    rule_code: Mapped[str] = mapped_column(String(50), nullable=False)
    rule_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Entity yang diatur
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)

    # Conditional: amount range
    min_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    max_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=Decimal("999999999999"))

    # Conditional: department (opsional)
    department: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Conditional: cost center (opsional)
    cost_center: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Conditional: project (opsional)
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Approval matrix
    approval_level: Mapped[int] = mapped_column(nullable=False, default=1)  # 1=first level
    approver_role: Mapped[str] = mapped_column(String(100), nullable=False)
    approver_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)  # specific user
    backup_approver_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Action
    action: Mapped[str] = mapped_column(String(20), nullable=False, default="approve")

    # Escalation settings (if action='escalate')
    escalate_after_hours: Mapped[int | None] = mapped_column(nullable=True)
    escalate_to_role: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Priority (higher number = higher priority when multiple rules match)
    priority: Mapped[int] = mapped_column(nullable=False, default=0)

    # Active flag
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Audit
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ========================================================================
    # PROPERTIES
    # ========================================================================
    @property
    def is_amount_in_range(self, amount: Decimal) -> bool:
        return self.min_amount <= amount <= self.max_amount

    @property
    def is_unlimited_amount(self) -> bool:
        return self.max_amount >= Decimal("999999999999")

    @property
    def requires_dual_approval(self) -> bool:
        return self.action == "require_dual"

    @property
    def is_active_rule(self) -> bool:
        return self.is_active

    # ========================================================================
    # METHODS
    # ========================================================================
    def activate(self) -> None:
        """Activate this rule."""
        self.is_active = True
        self.increment_version()

    def deactivate(self) -> None:
        """Deactivate this rule."""
        self.is_active = False
        self.increment_version()

    def matches(self, entity_type: str, amount: Decimal, department: str | None = None, cost_center: str | None = None) -> bool:
        """Check if this rule matches the given criteria."""
        if not self.is_active:
            return False
        if self.entity_type != entity_type:
            return False
        if not self.is_amount_in_range(amount):
            return False
        if self.department and self.department != department:
            return False
        if self.cost_center and cost_center and self.cost_center != cost_center:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "rule_code": self.rule_code,
            "rule_name": self.rule_name,
            "description": self.description,
            "entity_type": self.entity_type,
            "min_amount": float(self.min_amount),
            "max_amount": float(self.max_amount),
            "department": self.department,
            "cost_center": self.cost_center,
            "project_id": str(self.project_id) if self.project_id else None,
            "approval_level": self.approval_level,
            "approver_role": self.approver_role,
            "approver_user_id": str(self.approver_user_id) if self.approver_user_id else None,
            "backup_approver_id": str(self.backup_approver_id) if self.backup_approver_id else None,
            "action": self.action,
            "escalate_after_hours": self.escalate_after_hours,
            "escalate_to_role": self.escalate_to_role,
            "priority": self.priority,
            "is_active": self.is_active,
            "legal_entity_id": str(self.legal_entity_id),
            "version": self.version,
        }


__all__ = ["ApprovalRuleTable"]