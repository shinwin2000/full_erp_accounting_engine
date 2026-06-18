#!/usr/bin/env python3
"""
Module: iam_permission_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Model SQLAlchemy untuk tabel iam_permission (daftar izin) - mapper only.
"""

from __future__ import annotations

from sqlalchemy.orm import Mapped, relationship

from infrastructure.persistence_orm.base_model import Base
from infrastructure.persistence_orm.iam_user_table import iam_permission_table, iam_role_permission


class IAMPermissionTable(Base):
    __table__ = iam_permission_table

    # Relationships
    roles: Mapped[list[IAMRoleTable]] = relationship(
        "IAMRoleTable",
        secondary=iam_role_permission,
        back_populates="permissions",
        lazy="selectin",
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "permission_code": self.permission_code,
            "permission_name": self.permission_name,
            "description": self.description,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "action": self.action,
            "is_active": self.is_active,
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else None,
            "created_by": str(self.created_by) if self.created_by else None,
        }


__all__ = ["IAMPermissionTable"]
