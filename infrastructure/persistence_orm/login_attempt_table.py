#!/usr/bin/env python3
"""
Module: login_attempt_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel login_attempt.
               Tabel ini menyimpan log percobaan login (baik sukses maupun gagal)
               untuk deteksi brute force, analisis keamanan, dan compliance.
               Mencatat IP address, user agent, timestamp, dan hasil percobaan.
Dependencies:
- sqlalchemy.orm (Mapped, mapped_column, relationship)
- sqlalchemy.dialects.postgresql (UUID)
- infrastructure.persistence_orm.base_model (Base, TimestampMixin)
Audit: Semua percobaan login dicatat untuk keperluan forensik dan audit.
       Kegagalan berulang dari IP yang sama akan memicu alert.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import Base, TimestampMixin

if TYPE_CHECKING:
    from infrastructure.persistence_orm.iam_user_table import IAMUserTable


# ============================================================================
# LOGIN ATTEMPT MODEL
# ============================================================================


class LoginAttemptTable(Base, TimestampMixin):
    """
    Model untuk tabel login_attempt.
    """

    __tablename__ = "login_attempt"
    __table_args__ = (
        CheckConstraint(
            "username IS NOT NULL AND username != ''", name="ck_login_attempt_username"
        ),
        Index("idx_login_attempt_username", "username"),
        Index("idx_login_attempt_ip", "ip_address"),
        Index("idx_login_attempt_timestamp", "attempted_at"),
        Index("idx_login_attempt_success", "success"),
        Index("idx_login_attempt_user", "user_id"),
        {
            "extend_existing": True,
        },  # 👈 Menghindari bentrokan inisialisasi ganda pada MetaData
    )

    # Who attempted
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("iam_user.id"), nullable=True
    )

    # Attempt metadata
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)  # IPv4 or IPv6
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Result
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    failure_reason: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )  # wrong_password, account_locked, etc.

    # Timestamp (from TimestampMixin, but we also have a specific column for when attempt occurred)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )

    # Additional info
    request_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # correlation ID for tracing

    # ========================================================================
    # RELATIONSHIPS
    # ========================================================================

    user: Mapped[IAMUserTable | None] = relationship(
        "IAMUserTable", back_populates="login_attempts"
    )

    # ========================================================================
    # PROPERTIES
    # =========================================================================

    @property
    def is_failed(self) -> bool:
        return not self.success

    # ========================================================================
    # METHODS
    # ========================================================================

    @classmethod
    def create_failed_attempt(
        cls,
        username: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
        failure_reason: str = "wrong_password",
        request_id: str | None = None,
    ) -> LoginAttemptTable:
        """Create a failed login attempt record."""
        return cls(
            username=username,
            ip_address=ip_address,
            user_agent=user_agent,
            success=False,
            failure_reason=failure_reason,
            request_id=request_id,
            attempted_at=datetime.utcnow(),
        )

    @classmethod
    def create_success_attempt(
        cls,
        user_id: uuid.UUID,
        username: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
        request_id: str | None = None,
    ) -> LoginAttemptTable:
        """Create a successful login attempt record."""
        return cls(
            user_id=user_id,
            username=username,
            ip_address=ip_address,
            user_agent=user_agent,
            success=True,
            request_id=request_id,
            attempted_at=datetime.utcnow(),
        )


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ["LoginAttemptTable"]
