#!/usr/bin/env python3
"""
Module: override_authorizer.py
Layer: 7 - Policy Engine
Responsibility: Otorisasi override kebijakan.
               Menentukan siapa yang dapat melakukan override kebijakan,
               dalam kondisi apa, dan dengan batasan tertentu.

Dependencies:
- standard library (logging, datetime, typing)
- policy_engine.policy_exceptions

Audit: Setiap override dictat.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any
from uuid import uuid4

from .policy_exceptions import PolicyOverrideNotAuthorizedError

logger = logging.getLogger(__name__)


# === 1. CONSTANTS ===


class OverrideType(Enum):
    """Jenis override yang diizinkan."""

    POLICY_OVERRIDE = "policy_override"  # Override kebijakan
    RULE_OVERRIDE = "rule_override"  # Override aturan tertentu
    TEMPORARY_OVERRIDE = "temporary_override"  # Override sementara
    PERMANENT_OVERRIDE = "permanent_override"  # Override permanen


class OverrideStatus(Enum):
    """Status override."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    REVOKED = "revoked"


# === 2. OVERRIDE REQUEST ===


@dataclass
class OverrideRequest:
    """Permintaan override kebijakan."""

    request_id: str
    requester_id: str
    requester_name: str
    override_type: OverrideType
    target_policy_id: str
    target_rule_id: str | None
    reason: str
    justification: str
    effective_from: datetime
    effective_to: datetime | None
    requested_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    status: OverrideStatus = OverrideStatus.PENDING
    approved_by: str | None = None
    approved_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "requester_id": self.requester_id,
            "requester_name": self.requester_name,
            "override_type": self.override_type.value,
            "target_policy_id": self.target_policy_id,
            "target_rule_id": self.target_rule_id,
            "reason": self.reason,
            "justification": self.justification,
            "effective_from": self.effective_from.isoformat(),
            "effective_to": self.effective_to.isoformat() if self.effective_to else None,
            "status": self.status.value,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
        }


# === 3. OVERRIDE AUTHORIZER ===


class OverrideAuthorizer:
    """
    Authorizer untuk override kebijakan.

    Business context: Mengontrol siapa yang dapat melakukan override
    kebijakan akuntansi, dengan persetujuan dan batasan waktu.
    """

    _instance: OverrideAuthorizer | None = None
    _requests: list[OverrideRequest]
    _authorized_users: dict[str, set[str]]  # role -> set of user_ids

    def __new__(cls) -> OverrideAuthorizer:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._requests = []
        self._authorized_users = {
            "policy_admin": set(),
            "supervisor": set(),
            "manager": set(),
        }
        self._load_default_authorizers()

    def _load_default_authorizers(self) -> None:
        """Memuat authorizer default (contoh)."""
        # Dalam produksi, data ini akan dimuat dari konfigurasi
        pass

    def add_authorized_user(self, role: str, user_id: str) -> None:
        """Menambahkan user yang diotorisasi untuk override."""
        if role not in self._authorized_users:
            self._authorized_users[role] = set()
        self._authorized_users[role].add(user_id)
        logger.info(f"User {user_id} authorized for role {role}")

    def is_authorized(self, user_id: str, override_type: OverrideType) -> bool:
        """Memeriksa apakah user diotorisasi untuk melakukan override."""
        # Policy override memerlukan role policy_admin atau manager
        if override_type in [OverrideType.POLICY_OVERRIDE, OverrideType.PERMANENT_OVERRIDE]:
            required_roles = ["policy_admin", "manager"]
        else:
            required_roles = ["policy_admin", "supervisor", "manager"]

        for role in required_roles:
            if user_id in self._authorized_users.get(role, set()):
                return True
        return False

    def request_override(
        self,
        requester_id: str,
        requester_name: str,
        target_policy_id: str,
        reason: str,
        justification: str,
        override_type: OverrideType = OverrideType.TEMPORARY_OVERRIDE,
        target_rule_id: str | None = None,
        effective_days: int = 30,
    ) -> OverrideRequest:
        """Mengajukan permintaan override."""
        effective_from = datetime.now(UTC)
        effective_to = (
            effective_from + timedelta(days=effective_days)
            if override_type == OverrideType.TEMPORARY_OVERRIDE
            else None
        )

        request = OverrideRequest(
            request_id=str(uuid4()),
            requester_id=requester_id,
            requester_name=requester_name,
            override_type=override_type,
            target_policy_id=target_policy_id,
            target_rule_id=target_rule_id,
            reason=reason,
            justification=justification,
            effective_from=effective_from,
            effective_to=effective_to,
        )
        self._requests.append(request)
        logger.info(f"Override request {request.request_id} created by {requester_name}")
        return request

    def approve_override(
        self,
        request_id: str,
        approver_id: str,
    ) -> OverrideRequest:
        """Menyetujui permintaan override."""
        for req in self._requests:
            if req.request_id == request_id:
                if req.status != OverrideStatus.PENDING:
                    raise PolicyOverrideNotAuthorizedError(
                        policy_id=req.target_policy_id,
                        user_id=approver_id,
                        reason=f"Request already {req.status.value}",
                    )
                if not self.is_authorized(approver_id, req.override_type):
                    raise PolicyOverrideNotAuthorizedError(
                        policy_id=req.target_policy_id,
                        user_id=approver_id,
                        reason="User not authorized to approve this override type",
                    )
                req.status = OverrideStatus.APPROVED
                req.approved_by = approver_id
                req.approved_at = datetime.now(UTC)
                logger.info(f"Override request {request_id} approved by {approver_id}")
                return req
        raise PolicyOverrideNotAuthorizedError(
            policy_id="unknown",
            user_id=approver_id,
            reason=f"Request {request_id} not found",
        )

    def reject_override(
        self, request_id: str, approver_id: str, rejection_reason: str
    ) -> OverrideRequest:
        """Menolak permintaan override."""
        for req in self._requests:
            if req.request_id == request_id:
                if req.status != OverrideStatus.PENDING:
                    raise PolicyOverrideNotAuthorizedError(
                        policy_id=req.target_policy_id,
                        user_id=approver_id,
                        reason=f"Request already {req.status.value}",
                    )
                req.status = OverrideStatus.REJECTED
                req.notes = rejection_reason
                logger.info(
                    f"Override request {request_id} rejected by {approver_id}: {rejection_reason}"
                )
                return req
        raise PolicyOverrideNotAuthorizedError(
            policy_id="unknown",
            user_id=approver_id,
            reason=f"Request {request_id} not found",
        )

    def is_override_active(self, policy_id: str, as_of: datetime | None = None) -> bool:
        """Memeriksa apakah ada override aktif untuk kebijakan tertentu."""
        check_date = as_of or datetime.now(UTC)
        for req in self._requests:
            if req.status == OverrideStatus.APPROVED and req.target_policy_id == policy_id:
                if req.effective_from <= check_date:
                    if req.effective_to is None or req.effective_to >= check_date:
                        return True
        return False

    def get_active_overrides(self) -> list[OverrideRequest]:
        """Mendapatkan semua override yang aktif."""
        now = datetime.now(UTC)
        return [
            req
            for req in self._requests
            if req.status == OverrideStatus.APPROVED
            and req.effective_from <= now
            and (req.effective_to is None or req.effective_to >= now)
        ]

    def revoke_override(self, request_id: str, revoker_id: str) -> OverrideRequest:
        """Mencabut override yang disetujui."""
        for req in self._requests:
            if req.request_id == request_id:
                if req.status != OverrideStatus.APPROVED:
                    raise PolicyOverrideNotAuthorizedError(
                        policy_id=req.target_policy_id,
                        user_id=revoker_id,
                        reason=f"Cannot revoke override with status {req.status.value}",
                    )
                req.status = OverrideStatus.REVOKED
                logger.info(f"Override {request_id} revoked by {revoker_id}")
                return req
        raise PolicyOverrideNotAuthorizedError(
            policy_id="unknown",
            user_id=revoker_id,
            reason=f"Request {request_id} not found",
        )

    def get_requirements_summary(self) -> dict[str, Any]:
        """Mendapatkan ringkasan persyaratan authorizer."""
        return {
            "override_types": [t.value for t in OverrideType],
            "required_roles": ["policy_admin", "supervisor", "manager"],
            "default_temporary_days": 30,
        }


# === 4. SINGLETON ACCESSOR ===

_override_authorizer_instance: OverrideAuthorizer | None = None


def get_override_authorizer() -> OverrideAuthorizer:
    """Mendapatkan instance singleton OverrideAuthorizer."""
    global _override_authorizer_instance
    if _override_authorizer_instance is None:
        _override_authorizer_instance = OverrideAuthorizer()
    return _override_authorizer_instance


# === 5. EXPORTS ===

__all__ = [
    "OverrideAuthorizer",
    "OverrideRequest",
    "OverrideStatus",
    "OverrideType",
    "get_override_authorizer",
]
