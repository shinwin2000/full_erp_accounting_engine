#!/usr/bin/env python3
"""
Module: iam_role_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Model SQLAlchemy untuk tabel iam_role (role/hak akses) - mapper only.
"""

from __future__ import annotations

from sqlalchemy.orm import Mapped, relationship

from infrastructure.persistence_orm.base_model import Base
from infrastructure.persistence_orm.iam_user_table import (
    iam_role_permission,
    iam_role_table,
    iam_user_role,
)


class IAMRoleTable(Base):
    __table__ = iam_role_table

    # Relationships
    permissions: Mapped[list[IAMPermissionTable]] = relationship(
        "IAMPermissionTable",
        secondary=iam_role_permission,
        back_populates="roles",
        lazy="selectin",
    )
    users: Mapped[list[IAMUserTable]] = relationship(
        "IAMUserTable",
        secondary=iam_user_role,
        back_populates="roles",
        lazy="selectin",
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "role_code": self.role_code,
            "role_name": self.role_name,
            "description": self.description,
            "role_type": self.role_type,
            "is_active": self.is_active,
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else None,
            "created_by": str(self.created_by) if self.created_by else None,
        }


__all__ = ["IAMRoleTable"]
