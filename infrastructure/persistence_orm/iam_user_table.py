#!/usr/bin/env python3
"""
Module: iam_user_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Model SQLAlchemy untuk user, role, permission, session, login attempt, dan tabel asosiasi.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, relationship

from infrastructure.persistence_orm.base_model import (
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)

# ============================================================================
# HELPER: safe table creation – reuse existing table if already defined
# ============================================================================

def _safe_table(name: str, *args, **kwargs):
    """Create a Table only if it doesn't already exist in the metadata."""
    schema = kwargs.get('schema', 'public')
    qualified_name = f"{schema}.{name}"

    if qualified_name in Base.metadata.tables:
        return Base.metadata.tables[qualified_name]
    if name in Base.metadata.tables:
        return Base.metadata.tables[name]

    kwargs.setdefault('extend_existing', True)
    return Table(name, *args, **kwargs)


# ============================================================================
# ASSOCIATION TABLES
# ============================================================================

iam_user_legal_entity = _safe_table(
    "iam_user_legal_entity",
    Base.metadata,
    Column("user_id", PGUUID(as_uuid=True), ForeignKey("iam_user.id"), primary_key=True),
    Column("legal_entity_id", PGUUID(as_uuid=True), ForeignKey("legal_entity.id"), primary_key=True),
    Column("assigned_at", DateTime(timezone=True), server_default="now()"),
    Column("assigned_by", PGUUID(as_uuid=True), nullable=True),
    schema="public",
)

iam_user_role = _safe_table(
    "iam_user_role",
    Base.metadata,
    Column("user_id", PGUUID(as_uuid=True), ForeignKey("iam_user.id"), primary_key=True),
    Column("role_id", PGUUID(as_uuid=True), ForeignKey("iam_role.id"), primary_key=True),
    Column("assigned_at", DateTime(timezone=True), server_default="now()"),
    Column("assigned_by", PGUUID(as_uuid=True), nullable=True),
    schema="public",
)

iam_role_permission = _safe_table(
    "iam_role_permission",
    Base.metadata,
    Column("role_id", PGUUID(as_uuid=True), ForeignKey("iam_role.id"), primary_key=True),
    Column("permission_id", PGUUID(as_uuid=True), ForeignKey("iam_permission.id"), primary_key=True),
    Column("assigned_at", DateTime(timezone=True), server_default="now()"),
    schema="public",
)

iam_user_role_table = iam_user_role
iam_role_permission_table = iam_role_permission


# ============================================================================
# MAIN ENTITY TABLES
# ============================================================================

iam_user_table = _safe_table(
    "iam_user",
    Base.metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
    Column("username", String(100), nullable=False),
    Column("email", String(200), nullable=True),
    Column("email_encrypted", String(500), nullable=True),
    Column("phone", String(20), nullable=True),
    Column("phone_encrypted", String(200), nullable=True),
    Column("full_name", String(200), nullable=True),
    Column("password_hash", String(255), nullable=False),
    Column("password_changed_at", DateTime(timezone=True), nullable=True),
    Column("must_change_password", Boolean, nullable=False, default=False),
    Column("is_superuser", Boolean, nullable=False, default=False),
    Column("is_active", Boolean, nullable=False, default=True),
    Column("status", String(20), nullable=False, default="active"),
    Column("last_login_at", DateTime(timezone=True), nullable=True),
    Column("last_login_ip", String(45), nullable=True),
    Column("failed_login_count", Integer, nullable=False, default=0),
    Column("locked_until", DateTime(timezone=True), nullable=True),
    Column("preferences", JSONB, nullable=True),
    Column("user_metadata", JSONB, nullable=True),
    Column("legal_entity_ids", JSONB, nullable=True),
    Column("created_by", PGUUID(as_uuid=True), nullable=True),
    Column("created_at", DateTime(timezone=True), server_default="now()"),
    Column("updated_at", DateTime(timezone=True), onupdate="now()"),
    Column("deleted_at", DateTime(timezone=True), nullable=True),
    Column("version", Integer, nullable=False, default=1),
    UniqueConstraint("username", name="uq_iam_user_username"),
    UniqueConstraint("email", name="uq_iam_user_email"),
    CheckConstraint("username IS NOT NULL AND username != ''", name="ck_iam_user_username"),
    CheckConstraint("LENGTH(username) >= 3", name="ck_iam_user_username_length"),
    Index("idx_iam_user_username", "username"),
    Index("idx_iam_user_email", "email"),
    Index("idx_iam_user_status", "status"),
    Index("idx_iam_user_is_active", "is_active"),
    schema="public",
)

iam_role_table = _safe_table(
    "iam_role",
    Base.metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
    Column("name", String(100), nullable=False),
    Column("description", String(500), nullable=True),
    Column("is_active", Boolean, nullable=False, default=True),
    Column("is_system_role", Boolean, nullable=False, default=False),
    Column("created_by", PGUUID(as_uuid=True), nullable=True),
    Column("created_at", DateTime(timezone=True), server_default="now()"),
    Column("updated_at", DateTime(timezone=True), onupdate="now()"),
    Column("deleted_at", DateTime(timezone=True), nullable=True),
    UniqueConstraint("name", name="uq_iam_role_name"),
    Index("idx_iam_role_name", "name"),
    Index("idx_iam_role_is_active", "is_active"),
    schema="public",
)

iam_permission_table = _safe_table(
    "iam_permission",
    Base.metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
    Column("name", String(100), nullable=False),
    Column("resource", String(100), nullable=False),
    Column("action", String(50), nullable=False),
    Column("description", String(500), nullable=True),
    Column("created_at", DateTime(timezone=True), server_default="now()"),
    Column("updated_at", DateTime(timezone=True), onupdate="now()"),
    UniqueConstraint("name", name="uq_iam_permission_name"),
    Index("idx_iam_permission_name", "name"),
    Index("idx_iam_permission_resource", "resource"),
    Index("idx_iam_permission_action", "action"),
    schema="public",
)

iam_session_table = _safe_table(
    "iam_session",
    Base.metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
    Column("session_token", String(255), nullable=False, unique=True),
    Column("user_id", PGUUID(as_uuid=True), ForeignKey("iam_user.id"), nullable=False),
    Column("ip_address", String(45), nullable=True),
    Column("user_agent", String(500), nullable=True),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("is_active", Boolean, nullable=False, default=True),
    Column("session_metadata", JSONB, nullable=True),
    Column("created_at", DateTime(timezone=True), server_default="now()"),
    Column("updated_at", DateTime(timezone=True), onupdate="now()"),
    Index("idx_iam_session_user_id", "user_id"),
    Index("idx_iam_session_session_token", "session_token"),
    Index("idx_iam_session_expires_at", "expires_at"),
    Index("idx_iam_session_is_active", "is_active"),
    schema="public",
)

iam_login_attempt_table = _safe_table(
    "iam_login_attempt",
    Base.metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
    Column("username", String(100), nullable=False),
    Column("success", Boolean, nullable=False, default=False),
    Column("ip_address", String(45), nullable=True),
    Column("attempted_at", DateTime(timezone=True), nullable=False, server_default="now()"),
    Column("created_at", DateTime(timezone=True), server_default="now()"),
    Column("updated_at", DateTime(timezone=True), onupdate="now()"),
    Index("idx_login_attempt_username", "username"),
    Index("idx_login_attempt_attempted_at", "attempted_at"),
    Index("idx_login_attempt_success", "success"),
    schema="public",
)


# ============================================================================
# ORM CLASSES MAPPED TO EXPLICIT TABLES
# ============================================================================

class IAMUserTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin):
    __table__ = iam_user_table

    # Semua relasi menggunakan string literal, tidak ada impor langsung
    roles: Mapped[list[IAMRoleTable]] = relationship(
        "IAMRoleTable",
        secondary=iam_user_role,
        back_populates="users",
        lazy="selectin",
    )
    legal_entities: Mapped[list[LegalEntityTable]] = relationship(
        "LegalEntityTable",
        secondary=iam_user_legal_entity,
        viewonly=True,
        lazy="selectin",
    )
    sessions: Mapped[list[IAMSessionTable]] = relationship(
        "IAMSessionTable",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    login_attempts: Mapped[list[LoginAttemptTable]] = relationship(
        "LoginAttemptTable",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    @property
    def is_locked(self) -> bool:
        return bool(self.locked_until and self.locked_until > datetime.now(UTC))

    @property
    def is_admin(self) -> bool:
        return self.is_superuser or any(getattr(role, "role_code", "") == "admin" for role in (self.roles or []))

    legal_entity: Mapped[LegalEntityTable | None] = relationship(
        "LegalEntityTable", back_populates="user"
    )
    entity: Mapped[LegalEntityTable | None] = relationship(
        "LegalEntityTable", back_populates="users"
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "username": self.username,
            "email": self.email,
            "full_name": self.full_name,
            "is_active": self.is_active,
            "is_superuser": self.is_superuser,
            "status": self.status,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
            "preferences": self.preferences,
            "user_metadata": self.user_metadata,
            "legal_entity_ids": [str(eid) for eid in self.legal_entity_ids] if self.legal_entity_ids else [],
            "version": self.version,
        }


class IAMRoleTable(Base, TimestampMixin, SoftDeleteMixin):
    __table__ = iam_role_table

    users: Mapped[list[IAMUserTable]] = relationship(
        "IAMUserTable",
        secondary=iam_user_role,
        back_populates="roles",
        lazy="selectin",
    )
    permissions: Mapped[list[IAMPermissionTable]] = relationship(
        "IAMPermissionTable",
        secondary=iam_role_permission,
        back_populates="roles",
        lazy="selectin",
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "name": self.name,
            "description": self.description,
            "is_active": self.is_active,
            "is_system_role": self.is_system_role,
            "created_by": str(self.created_by) if self.created_by else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class IAMPermissionTable(Base, TimestampMixin):
    __table__ = iam_permission_table

    roles: Mapped[list[IAMRoleTable]] = relationship(
        "IAMRoleTable",
        secondary=iam_role_permission,
        back_populates="permissions",
        lazy="selectin",
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "name": self.name,
            "resource": self.resource,
            "action": self.action,
            "description": self.description,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class IAMSessionTable(Base, TimestampMixin):
    __table__ = iam_session_table

    user: Mapped[IAMUserTable] = relationship("IAMUserTable", back_populates="sessions")

    @property
    def is_expired(self) -> bool:
        return datetime.now(UTC) > self.expires_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "session_token": self.session_token,
            "user_id": str(self.user_id),
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "expires_at": self.expires_at.isoformat(),
            "is_active": self.is_active,
            "session_metadata": self.session_metadata,
        }


class LoginAttemptTable(Base, TimestampMixin):
    __table__ = iam_login_attempt_table

    user: Mapped[IAMUserTable] = relationship(
        "IAMUserTable",
        back_populates="login_attempts",
        primaryjoin="LoginAttemptTable.username == IAMUserTable.username",
        foreign_keys="LoginAttemptTable.username",
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "username": self.username,
            "success": self.success,
            "ip_address": self.ip_address,
            "attempted_at": self.attempted_at.isoformat(),
        }


__all__ = [
    "IAMPermissionTable",
    "IAMRoleTable",
    "IAMSessionTable",
    "IAMUserTable",
    "LoginAttemptTable",
    "iam_role_permission",
    "iam_role_permission_table",
    "iam_user_legal_entity",
    "iam_user_role",
    "iam_user_role_table",
]
