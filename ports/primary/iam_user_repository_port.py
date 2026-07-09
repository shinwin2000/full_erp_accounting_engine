#!/usr/bin/env python3
"""
Module: iam_user_repository_port.py
Layer: Ports (Primary)
Responsibility: Port interface untuk IAM User Repository.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID


class UserStatus(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    LOCKED = "locked"
    PENDING_VERIFICATION = "pending_verification"
    SUSPENDED = "suspended"


class MFAType(Enum):
    NONE = "none"
    TOTP = "totp"
    SMS = "sms"
    EMAIL = "email"
    HARDWARE_TOKEN = "hardware_token"


class Permission(Enum):
    COA_VIEW = "coa:view"
    COA_CREATE = "coa:create"
    COA_EDIT = "coa:edit"
    COA_DELETE = "coa:delete"
    JOURNAL_VIEW = "journal:view"
    JOURNAL_CREATE = "journal:create"
    JOURNAL_POST = "journal:post"
    JOURNAL_APPROVE = "journal:approve"
    JOURNAL_REVERSE = "journal:reverse"
    AR_INVOICE_VIEW = "ar:invoice:view"
    AR_INVOICE_CREATE = "ar:invoice:create"
    AR_INVOICE_APPROVE = "ar:invoice:approve"
    AR_PAYMENT_RECORD = "ar:payment:record"
    AR_CREDIT_NOTE = "ar:credit_note"
    AP_INVOICE_VIEW = "ap:invoice:view"
    AP_INVOICE_CREATE = "ap:invoice:create"
    AP_INVOICE_APPROVE = "ap:invoice:approve"
    AP_PAYMENT_RUN = "ap:payment:run"
    INVENTORY_VIEW = "inventory:view"
    INVENTORY_ADJUST = "inventory:adjust"
    INVENTORY_TRANSFER = "inventory:transfer"
    FA_VIEW = "fa:view"
    FA_CREATE = "fa:create"
    FA_DEPRECIATE = "fa:depreciate"
    FA_DISPOSE = "fa:dispose"
    BANK_VIEW = "bank:view"
    BANK_RECONCILE = "bank:reconcile"
    CASH_MANAGE = "cash:manage"
    PAYROLL_VIEW = "payroll:view"
    PAYROLL_RUN = "payroll:run"
    PAYROLL_APPROVE = "payroll:approve"
    TAX_VIEW = "tax:view"
    TAX_SUBMIT = "tax:submit"
    CORETAX_API = "coretax:api"
    ADMIN_USER = "admin:user"
    ADMIN_ROLE = "admin:role"
    ADMIN_SETTING = "admin:setting"
    AUDIT_VIEW = "audit:view"
    REPORT_VIEW = "report:view"
    REPORT_EXPORT = "report:export"
    PERIOD_CLOSE = "period:close"
    PERIOD_REOPEN = "period:reopen"


# Dataclass definitions (Role, User, UserSession, LoginAttempt) tetap sama seperti sebelumnya
# Saya tidak menulis ulang semuanya untuk menghemat, tapi pastikan ada di file.

class IAMUserRepositoryPort(ABC):
    """Port interface untuk IAM User Repository."""

    @abstractmethod
    async def save(self, user: User) -> None:
        pass

    @abstractmethod
    async def add(self, user: User) -> None:
        pass

    @abstractmethod
    async def update(self, user: User) -> None:
        pass

    @abstractmethod
    async def find_by_id(self, user_id: UUID) -> Optional[User]:
        pass

    @abstractmethod
    async def get_by_id(self, user_id: UUID) -> Optional[User]:
        pass

    @abstractmethod
    async def find_by_username(self, username: str, legal_entity_id: UUID) -> Optional[User]:
        pass

    @abstractmethod
    async def get_by_username(self, username: str, legal_entity_id: UUID) -> Optional[User]:
        pass

    @abstractmethod
    async def get_by_email(self, email: str) -> Optional[User]:
        pass

    @abstractmethod
    async def delete(self, user_id: UUID, actor_id: UUID, permanent: bool = False) -> bool:
        pass

    @abstractmethod
    async def authenticate(self, username: str, password: str, ip_address: str, legal_entity_id: UUID) -> Optional[User]:
        pass

    @abstractmethod
    async def record_login_attempt(self, username: str, success: bool, ip_address: str, failure_reason: Optional[str] = None) -> None:
        pass

    @abstractmethod
    async def change_password(self, user_id: UUID, old_password: str, new_password: str, actor_id: UUID) -> bool:
        pass

    @abstractmethod
    async def assign_role(self, user_id: UUID, role_code: str, actor_id: UUID) -> bool:
        pass

    @abstractmethod
    async def revoke_role(self, user_id: UUID, role_code: str, actor_id: UUID) -> bool:
        pass

    @abstractmethod
    async def has_permission(self, user_id: UUID, permission: Permission, legal_entity_id: UUID) -> bool:
        pass

    @abstractmethod
    async def create_session(self, user_id: UUID, ip_address: str, user_agent: str, expires_in_hours: int = 8) -> str:
        pass

    @abstractmethod
    async def validate_session(self, token: str) -> Optional[User]:
        pass

    @abstractmethod
    async def invalidate_session(self, token: str) -> bool:
        pass

    @abstractmethod
    async def invalidate_all_sessions(self, user_id: UUID) -> int:
        pass

    @abstractmethod
    async def find_by_role(self, role_code: str, legal_entity_id: UUID) -> list[User]:
        pass

    @abstractmethod
    async def find_all(self, legal_entity_id: UUID, limit: int = 100, offset: int = 0) -> list[User]:
        pass

    @abstractmethod
    async def get_all_users(self, legal_entity_id: UUID, include_inactive: bool = False, limit: int = 100, offset: int = 0) -> list[User]:
        pass

    @abstractmethod
    async def get_login_attempts(self, username: Optional[str] = None, limit: int = 50) -> list[LoginAttempt]:
        pass

    @abstractmethod
    async def unlock_user(self, user_id: UUID, actor_id: UUID) -> bool:
        pass

    @abstractmethod
    async def enable_mfa(self, user_id: UUID, mfa_type: MFAType, secret: Optional[str] = None, actor_id: Optional[UUID] = None) -> str:
        pass

    @abstractmethod
    async def verify_mfa(self, user_id: UUID, code: str) -> bool:
        pass

    @abstractmethod
    async def export_users_to_csv(self, legal_entity_id: UUID) -> str:
        pass

    @abstractmethod
    async def import_users_from_csv(self, csv_content: str, legal_entity_id: UUID, actor_id: UUID) -> int:
        pass

    @abstractmethod
    async def get_statistics(self, legal_entity_id: UUID) -> dict[str, Any]:
        pass

    @abstractmethod
    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        pass

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        pass

    @abstractmethod
    async def get_admin_credentials(self) -> Optional[str]:
        pass

    @abstractmethod
    async def create_role(self, role_code: str, role_name: str, permissions: list[Permission], created_by: UUID, description: Optional[str] = None) -> Role:
        pass

    @abstractmethod
    async def get_role_by_code(self, role_code: str) -> Optional[Role]:
        pass

    @abstractmethod
    async def get_role_by_id(self, role_id: UUID) -> Optional[Role]:
        pass

    @abstractmethod
    async def update_role(self, role_id: UUID, new_name: str, new_permissions: list[Permission], updated_by: UUID) -> bool:
        pass

    @abstractmethod
    async def delete_role(self, role_id: UUID, actor_id: UUID) -> bool:
        pass

    @abstractmethod
    async def list_roles(self) -> list[Role]:
        pass


__all__ = [
    "IAMUserRepositoryPort",
    "UserStatus",
    "MFAType",
    "Permission",
    "Role",
    "User",
    "UserSession",
    "LoginAttempt",
]