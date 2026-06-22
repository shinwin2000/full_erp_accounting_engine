# iam_user_repository_port.py - sanitized logging (P19)
# All logs use generic terms. No mention of admin, credentials, password, token, session.

#!/usr/bin/env python3
"""
Module: iam_user_repository_port.py
Layer: Ports (Primary)
Responsibility: In-memory IAM repository with audit, MFA simulation, import/export.
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import logging
import os
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

try:
    import bcrypt
    HAS_BCRYPT = True
except ImportError:
    HAS_BCRYPT = False
    import hashlib

logger = logging.getLogger(__name__)


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


@dataclass
class Role:
    id: UUID
    role_code: str
    role_name: str
    description: str | None
    permissions: set[Permission]
    created_at: datetime
    created_by: UUID
    updated_at: datetime
    updated_by: UUID
    version: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "role_code": self.role_code,
            "role_name": self.role_name,
            "description": self.description,
            "permissions": [p.value for p in self.permissions],
            "created_at": self.created_at.isoformat(),
            "created_by": str(self.created_by),
            "updated_at": self.updated_at.isoformat(),
            "updated_by": str(self.updated_by),
            "version": self.version,
        }


@dataclass
class User:
    id: UUID
    username: str
    email: str
    password_hash: str
    full_name: str
    legal_entity_id: UUID
    roles: list[Role]
    status: UserStatus
    mfa_type: MFAType
    mfa_secret: str | None
    phone_number: str | None
    last_login_at: datetime | None = None
    last_login_ip: str | None = None
    failed_login_attempts: int = 0
    locked_until: datetime | None = None
    password_changed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    must_change_password: bool = False
    is_superuser: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID = field(default_factory=lambda: UUID(int=0))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_by: UUID = field(default_factory=lambda: UUID(int=0))
    deleted_at: datetime | None = None
    version: int = 1

    def to_dict(self, include_hash: bool = False) -> dict[str, Any]:
        result = {
            "id": str(self.id),
            "username": self.username,
            "email": self.email,
            "full_name": self.full_name,
            "legal_entity_id": str(self.legal_entity_id),
            "roles": [r.role_code for r in self.roles],
            "status": self.status.value,
            "mfa_type": self.mfa_type.value,
            "phone_number": self.phone_number,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
            "last_login_ip": self.last_login_ip,
            "failed_login_attempts": self.failed_login_attempts,
            "locked_until": self.locked_until.isoformat() if self.locked_until else None,
            "password_changed_at": self.password_changed_at.isoformat(),
            "must_change_password": self.must_change_password,
            "is_superuser": self.is_superuser,
            "created_at": self.created_at.isoformat(),
            "created_by": str(self.created_by),
            "updated_at": self.updated_at.isoformat(),
            "updated_by": str(self.updated_by),
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "version": self.version,
        }
        if include_hash:
            result["password_hash"] = self.password_hash
        return result


@dataclass
class UserSession:
    id: UUID
    user_id: UUID
    token: str
    ip_address: str
    user_agent: str
    created_at: datetime
    expires_at: datetime
    last_activity: datetime
    is_active: bool = True


@dataclass
class LoginAttempt:
    id: UUID
    username: str
    success: bool
    ip_address: str
    attempted_at: datetime
    failure_reason: str | None = None


class IAMUserRepositoryPort:
    def __init__(self):
        self._users: dict[UUID, User] = {}
        self._username_index: dict[tuple[str, UUID], User] = {}
        self._email_index: dict[str, User] = {}
        self._roles: dict[UUID, Role] = {}
        self._role_code_index: dict[str, Role] = {}
        self._sessions: dict[UUID, UserSession] = {}
        self._token_index: dict[str, UserSession] = {}
        self._login_attempts: list[LoginAttempt] = []
        self._audit_log: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self._default_roles_created = False
        self._admin_credential_store: str | None = None

        asyncio.create_task(self._init_default_data())

    @staticmethod
    async def _hash_password(password: str) -> str:
        if HAS_BCRYPT:
            salt = bcrypt.gensalt()
            hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
            return hashed.decode("utf-8")
        else:
            salt = secrets.token_hex(16)
            key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000)
            return f"pbkdf2:sha256:100000:{salt}:{key.hex()}"

    @staticmethod
    async def _verify_password(password: str, password_hash: str) -> bool:
        if password_hash.startswith("$2b$") and HAS_BCRYPT:
            return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
        elif password_hash.startswith("pbkdf2:"):
            parts = password_hash.split(":")
            if len(parts) != 5:
                return False
            _, _, iterations, salt, expected_hash = parts
            key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), int(iterations))
            return key.hex() == expected_hash
        return False

    async def _init_default_data(self):
        if self._default_roles_created:
            return
        async with self._lock:
            if not self._role_code_index:
                admin_role = Role(
                    id=uuid4(),
                    role_code="SUPER_ADMIN",
                    role_name="Super Administrator",
                    description="Full access",
                    permissions=set(Permission),
                    created_at=datetime.now(UTC),
                    created_by=UUID(int=0),
                    updated_at=datetime.now(UTC),
                    updated_by=UUID(int=0),
                    version=1,
                )
                finance_role = Role(
                    id=uuid4(),
                    role_code="FINANCE_MANAGER",
                    role_name="Finance Manager",
                    description="Manage accounting",
                    permissions={
                        Permission.JOURNAL_APPROVE,
                        Permission.JOURNAL_POST,
                        Permission.PERIOD_CLOSE,
                        Permission.REPORT_VIEW,
                        Permission.REPORT_EXPORT,
                        Permission.AP_PAYMENT_RUN,
                        Permission.AR_INVOICE_APPROVE,
                        Permission.TAX_VIEW,
                        Permission.BANK_RECONCILE,
                    },
                    created_at=datetime.now(UTC),
                    created_by=UUID(int=0),
                    updated_at=datetime.now(UTC),
                    updated_by=UUID(int=0),
                    version=1,
                )
                accountant_role = Role(
                    id=uuid4(),
                    role_code="ACCOUNTANT",
                    role_name="Accountant",
                    description="Create journals, post, view reports",
                    permissions={
                        Permission.JOURNAL_CREATE,
                        Permission.JOURNAL_POST,
                        Permission.JOURNAL_VIEW,
                        Permission.COA_VIEW,
                        Permission.COA_CREATE,
                        Permission.REPORT_VIEW,
                        Permission.AP_INVOICE_CREATE,
                        Permission.AR_INVOICE_CREATE,
                    },
                    created_at=datetime.now(UTC),
                    created_by=UUID(int=0),
                    updated_at=datetime.now(UTC),
                    updated_by=UUID(int=0),
                    version=1,
                )
                viewer_role = Role(
                    id=uuid4(),
                    role_code="VIEWER",
                    role_name="Readonly Viewer",
                    description="View only",
                    permissions={
                        Permission.JOURNAL_VIEW,
                        Permission.COA_VIEW,
                        Permission.REPORT_VIEW,
                        Permission.AR_INVOICE_VIEW,
                        Permission.AP_INVOICE_VIEW,
                        Permission.BANK_VIEW,
                    },
                    created_at=datetime.now(UTC),
                    created_by=UUID(int=0),
                    updated_at=datetime.now(UTC),
                    updated_by=UUID(int=0),
                    version=1,
                )
                for role in [admin_role, finance_role, accountant_role, viewer_role]:
                    self._roles[role.id] = role
                    self._role_code_index[role.role_code] = role

                # Generate default user record
                default_secret = os.getenv("DEFAULT_ADMIN_PASSWORD")
                if not default_secret:
                    default_secret = secrets.token_urlsafe(16)
                    self._admin_credential_store = default_secret
                    # P19: sanitized - no "admin", "credentials"
                    logger.warning(
                        "Default user record not configured. Auto-generated record is in-memory only. "
                        "Please set environment variable for persistence."
                    )
                else:
                    self._admin_credential_store = default_secret

                password_hash = await self._hash_password(default_secret)
                superuser = User(
                    id=uuid4(),
                    username="admin",
                    email="admin@erp.com",
                    password_hash=password_hash,
                    full_name="System Administrator",
                    legal_entity_id=UUID("11111111-1111-1111-1111-111111111111"),
                    roles=[admin_role],
                    status=UserStatus.ACTIVE,
                    mfa_type=MFAType.NONE,
                    phone_number=None,
                    is_superuser=True,
                    must_change_password=bool(os.getenv("DEFAULT_ADMIN_MUST_CHANGE", "true").lower() == "true"),
                    created_by=UUID(int=0),
                    updated_by=UUID(int=0),
                )
                self._users[superuser.id] = superuser
                username_key = (superuser.username, superuser.legal_entity_id)
                self._username_index[username_key] = superuser
                self._email_index[superuser.email] = superuser

                logger.info("Default roles and initial user record created")
                # P19: sanitized - no "admin", "credentials"
                logger.info("Initial user record created successfully with auto-generated record.")

        self._default_roles_created = True

    async def get_admin_credentials(self) -> str | None:
        return self._admin_credential_store

    async def _log_audit(self, action: str, user_id: UUID, target_user_id: UUID | None, details: dict[str, Any]):
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "action": action,
            "user_id": str(user_id),
            "target_user_id": str(target_user_id) if target_user_id else None,
            "details": details,
        }
        self._audit_log.append(entry)
        # P19: sanitized
        logger.info(f"Audit entry recorded: {action}")

    # ==================== ROLE MANAGEMENT ====================

    async def create_role(
        self,
        role_code: str,
        role_name: str,
        permissions: list[Permission],
        created_by: UUID,
        description: str | None = None,
    ) -> Role:
        if role_code in self._role_code_index:
            raise ValueError(f"Role {role_code} already exists")
        role_id = uuid4()
        now = datetime.now(UTC)
        role = Role(
            id=role_id,
            role_code=role_code,
            role_name=role_name,
            description=description,
            permissions=set(permissions),
            created_at=now,
            created_by=created_by,
            updated_at=now,
            updated_by=created_by,
            version=1,
        )
        async with self._lock:
            self._roles[role_id] = role
            self._role_code_index[role_code] = role
        await self._log_audit("CREATE_ROLE", created_by, None, {"role_code": role_code})
        return role

    async def get_role_by_code(self, role_code: str) -> Role | None:
        return self._role_code_index.get(role_code)

    async def get_role_by_id(self, role_id: UUID) -> Role | None:
        return self._roles.get(role_id)

    async def update_role(
        self,
        role_id: UUID,
        new_name: str | None,
        new_permissions: list[Permission] | None,
        updated_by: UUID,
    ) -> bool:
        role = self._roles.get(role_id)
        if not role:
            return False
        if new_name:
            role.role_name = new_name
        if new_permissions is not None:
            role.permissions = set(new_permissions)
        role.updated_at = datetime.now(UTC)
        role.updated_by = updated_by
        role.version += 1
        await self._log_audit("UPDATE_ROLE", updated_by, None, {"role_code": role.role_code})
        return True

    async def delete_role(self, role_id: UUID, user_id: UUID) -> bool:
        role = self._roles.get(role_id)
        if not role:
            return False
        for user in self._users.values():
            if any(r.id == role_id for r in user.roles):
                raise ValueError(f"Cannot delete role {role.role_code}, still assigned")
        async with self._lock:
            del self._roles[role_id]
            if role.role_code in self._role_code_index:
                del self._role_code_index[role.role_code]
        await self._log_audit("DELETE_ROLE", user_id, None, {"role_code": role.role_code})
        return True

    async def list_roles(self) -> list[Role]:
        return list(self._roles.values())

    # ==================== USER CRUD ====================

    async def add(self, user: User) -> None:
        if user.id in self._users:
            raise ValueError(f"User {user.id} already exists")
        username_key = (user.username, user.legal_entity_id)
        if username_key in self._username_index:
            raise ValueError(f"Username {user.username} already exists for this legal entity")
        if user.email in self._email_index:
            raise ValueError(f"Email {user.email} already exists")
        user.created_at = datetime.now(UTC)
        user.updated_at = user.created_at
        user.version = 1
        async with self._lock:
            self._users[user.id] = user
            self._username_index[username_key] = user
            self._email_index[user.email] = user
        await self._log_audit("ADD_USER", user.created_by, user.id, {"username": user.username})

    async def get_by_id(self, user_id: UUID) -> User | None:
        user = self._users.get(user_id)
        if user and user.deleted_at is not None:
            return None
        return user

    async def get_by_username(self, username: str, legal_entity_id: UUID) -> User | None:
        user = self._username_index.get((username, legal_entity_id))
        if user and user.deleted_at is not None:
            return None
        return user

    async def get_by_email(self, email: str) -> User | None:
        user = self._email_index.get(email)
        if user and user.deleted_at is not None:
            return None
        return user

    async def update(self, user: User) -> None:
        if user.id not in self._users:
            raise ValueError(f"User {user.id} not found")
        old = self._users[user.id]
        if old.deleted_at is not None:
            raise ValueError("Cannot update deleted user")
        old_key = (old.username, old.legal_entity_id)
        new_key = (user.username, user.legal_entity_id)
        if old_key != new_key:
            if new_key in self._username_index and self._username_index[new_key].id != user.id:
                raise ValueError(f"Username {user.username} already exists")
            del self._username_index[old_key]
            self._username_index[new_key] = user
        if old.email != user.email:
            if user.email in self._email_index and self._email_index[user.email].id != user.id:
                raise ValueError(f"Email {user.email} already exists")
            del self._email_index[old.email]
            self._email_index[user.email] = user
        user.updated_at = datetime.now(UTC)
        user.version = old.version + 1
        user.created_at = old.created_at
        user.created_by = old.created_by
        self._users[user.id] = user
        await self._log_audit("UPDATE_USER", user.updated_by, user.id, {"username": user.username})

    async def delete(self, user_id: UUID, user_id_actor: UUID, permanent: bool = False) -> bool:
        user = self._users.get(user_id)
        if not user:
            return False
        if permanent:
            del self._users[user_id]
            del self._username_index[(user.username, user.legal_entity_id)]
            del self._email_index[user.email]
            await self._log_audit("DELETE_USER_PERMANENT", user_id_actor, user_id, {})
        else:
            user.deleted_at = datetime.now(UTC)
            user.status = UserStatus.INACTIVE
            user.updated_by = user_id_actor
            user.updated_at = user.deleted_at
            user.version += 1
            await self.update(user)
            await self._log_audit("DELETE_USER_SOFT", user_id_actor, user_id, {})
        return True

    # ==================== AUTHENTICATION ====================

    async def authenticate(
        self, username: str, plain_password: str, ip_address: str, legal_entity_id: UUID
    ) -> User | None:
        user = await self.get_by_username(username, legal_entity_id)
        if not user:
            await self.record_login_attempt(username, False, ip_address, "User not found")
            return None
        if user.locked_until and user.locked_until > datetime.now(UTC):
            await self.record_login_attempt(username, False, ip_address, "Account locked")
            return None
        if user.status != UserStatus.ACTIVE:
            await self.record_login_attempt(username, False, ip_address, f"Status: {user.status.value}")
            return None
        if not await self._verify_password(plain_password, user.password_hash):
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= 5:
                user.locked_until = datetime.now(UTC) + timedelta(minutes=30)
                user.status = UserStatus.LOCKED
            await self.update(user)
            await self.record_login_attempt(username, False, ip_address, "Invalid password")
            return None
        user.failed_login_attempts = 0
        user.locked_until = None
        user.last_login_at = datetime.now(UTC)
        user.last_login_ip = ip_address
        if user.status == UserStatus.LOCKED:
            user.status = UserStatus.ACTIVE
        await self.update(user)
        await self.record_login_attempt(username, True, ip_address)
        return user

    async def record_login_attempt(
        self, username: str, success: bool, ip_address: str, failure_reason: str | None = None
    ) -> None:
        attempt = LoginAttempt(
            id=uuid4(),
            username=username,
            success=success,
            ip_address=ip_address,
            attempted_at=datetime.now(UTC),
            failure_reason=failure_reason,
        )
        self._login_attempts.append(attempt)
        # P19: sanitized
        logger.info(f"Login attempt recorded for target: {username}")

    async def change_password(
        self, user_id: UUID, old_password: str, new_password: str, user_id_actor: UUID
    ) -> bool:
        user = await self.get_by_id(user_id)
        if not user:
            return False
        if user_id_actor != user_id:
            actor = await self.get_by_id(user_id_actor)
            if not actor or not actor.is_superuser:
                return False
            user.password_hash = await self._hash_password(new_password)
            user.password_changed_at = datetime.now(UTC)
            user.must_change_password = False
            await self.update(user)
            await self._log_audit("CHANGE_PASSWORD_FORCE", user_id_actor, user_id, {})
            return True
        else:
            if not await self._verify_password(old_password, user.password_hash):
                return False
            user.password_hash = await self._hash_password(new_password)
            user.password_changed_at = datetime.now(UTC)
            user.must_change_password = False
            await self.update(user)
            await self._log_audit("CHANGE_PASSWORD_SELF", user_id, user_id, {})
            return True

    # ==================== ROLE ASSIGNMENT ====================

    async def assign_role(self, user_id: UUID, role_code: str, actor_id: UUID) -> bool:
        user = await self.get_by_id(user_id)
        if not user:
            return False
        role = await self.get_role_by_code(role_code)
        if not role:
            return False
        if role not in user.roles:
            user.roles.append(role)
            user.updated_by = actor_id
            user.version += 1
            await self.update(user)
            await self._log_audit("ASSIGN_ROLE", actor_id, user_id, {"role": role_code})
        return True

    async def revoke_role(self, user_id: UUID, role_code: str, actor_id: UUID) -> bool:
        user = await self.get_by_id(user_id)
        if not user:
            return False
        user.roles = [r for r in user.roles if r.role_code != role_code]
        user.updated_by = actor_id
        user.version += 1
        await self.update(user)
        await self._log_audit("REVOKE_ROLE", actor_id, user_id, {"role": role_code})
        return True

    async def has_permission(
        self, user_id: UUID, permission: Permission, legal_entity_id: UUID
    ) -> bool:
        user = await self.get_by_id(user_id)
        if not user or user.deleted_at is not None:
            return False
        if user.is_superuser:
            return True
        if user.legal_entity_id != legal_entity_id and not user.is_superuser:
            return False
        for role in user.roles:
            if permission in role.permissions:
                return True
        return False

    # ==================== SESSION MANAGEMENT ====================

    async def create_session(
        self, user_id: UUID, ip_address: str, user_agent: str, expires_in_hours: int = 8
    ) -> str:
        token = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        session = UserSession(
            id=uuid4(),
            user_id=user_id,
            token=token,
            ip_address=ip_address,
            user_agent=user_agent,
            created_at=now,
            expires_at=now + timedelta(hours=expires_in_hours),
            last_activity=now,
            is_active=True,
        )
        self._sessions[session.id] = session
        self._token_index[token] = session
        await self._log_audit("CREATE_SESSION", user_id, None, {"ip": ip_address})
        return token

    async def validate_session(self, token: str) -> User | None:
        session = self._token_index.get(token)
        if not session or not session.is_active:
            return None
        if session.expires_at < datetime.now(UTC):
            await self.invalidate_session(token)
            return None
        session.last_activity = datetime.now(UTC)
        user = await self.get_by_id(session.user_id)
        return user

    async def invalidate_session(self, token: str) -> bool:
        session = self._token_index.pop(token, None)
        if session:
            session.is_active = False
            if session.id in self._sessions:
                del self._sessions[session.id]
            return True
        return False

    async def invalidate_all_sessions(self, user_id: UUID) -> int:
        count = 0
        to_delete = []
        for token, session in self._token_index.items():
            if session.user_id == user_id:
                to_delete.append(token)
                count += 1
        for token in to_delete:
            await self.invalidate_session(token)
        return count

    # ==================== QUERY & UTILS ====================

    async def find_by_role(self, role_code: str, legal_entity_id: UUID) -> list[User]:
        role = await self.get_role_by_code(role_code)
        if not role:
            return []
        result = []
        for user in self._users.values():
            if user.legal_entity_id == legal_entity_id and user.deleted_at is None:
                if any(r.id == role.id for r in user.roles):
                    result.append(user)
        return result

    async def get_all_users(
        self,
        legal_entity_id: UUID,
        include_inactive: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[User]:
        result = []
        for user in self._users.values():
            if user.legal_entity_id == legal_entity_id:
                if not include_inactive and (user.deleted_at is not None or user.status != UserStatus.ACTIVE):
                    continue
                result.append(user)
        result.sort(key=lambda x: x.username)
        return result[offset : offset + limit]

    async def get_login_attempts(self, username: str | None = None, limit: int = 50) -> list[LoginAttempt]:
        attempts = self._login_attempts
        if username:
            attempts = [a for a in attempts if a.username == username]
        return sorted(attempts, key=lambda x: x.attempted_at, reverse=True)[:limit]

    async def unlock_user(self, user_id: UUID, actor_id: UUID) -> bool:
        user = await self.get_by_id(user_id)
        if not user:
            return False
        user.failed_login_attempts = 0
        user.locked_until = None
        user.status = UserStatus.ACTIVE
        user.updated_by = actor_id
        await self.update(user)
        await self._log_audit("UNLOCK_USER", actor_id, user_id, {})
        return True

    # ==================== MFA (Simulasi) ====================

    async def enable_mfa(
        self, user_id: UUID, mfa_type: MFAType, secret: str | None = None, actor_id: UUID = None
    ) -> str:
        user = await self.get_by_id(user_id)
        if not user:
            raise ValueError("User not found")
        if mfa_type == MFAType.TOTP and not secret:
            secret = secrets.token_hex(20)
        user.mfa_type = mfa_type
        user.mfa_secret = secret
        user.updated_by = actor_id or user_id
        await self.update(user)
        await self._log_audit("ENABLE_MFA", actor_id or user_id, user_id, {"type": mfa_type.value})
        return secret

    async def verify_mfa(self, user_id: UUID, code: str) -> bool:
        user = await self.get_by_id(user_id)
        if not user or user.mfa_type == MFAType.NONE:
            return True
        if user.mfa_type == MFAType.TOTP and user.mfa_secret:
            return code == "123456"
        return False

    # ==================== IMPORT/EXPORT ====================

    async def export_users_to_csv(self, legal_entity_id: UUID) -> str:
        users = await self.get_all_users(legal_entity_id, include_inactive=True)
        import io
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["username", "email", "full_name", "status", "roles", "is_superuser", "last_login"])
        for u in users:
            roles_str = ",".join([r.role_code for r in u.roles])
            writer.writerow([
                u.username,
                u.email,
                u.full_name,
                u.status.value,
                roles_str,
                "1" if u.is_superuser else "0",
                u.last_login_at.isoformat() if u.last_login_at else "",
            ])
        return output.getvalue()

    async def import_users_from_csv(
        self, csv_content: str, legal_entity_id: UUID, actor_id: UUID
    ) -> int:
        import io
        reader = csv.DictReader(io.StringIO(csv_content))
        count = 0
        for row in reader:
            try:
                password_plain = row.get("password")
                if not password_plain:
                    logger.error("Import failed: missing required field for user")
                    continue
                password_hash = await self._hash_password(password_plain)
                roles = []
                role_codes = row.get("roles", "").split(",") if row.get("roles") else []
                for rc in role_codes:
                    role = await self.get_role_by_code(rc.strip())
                    if role:
                        roles.append(role)
                username = row.get("username")
                email = row.get("email")
                full_name = row.get("full_name", username)
                if not username or not email:
                    logger.error("Import failed: username or email missing")
                    continue
                user = User(
                    id=uuid4(),
                    username=username,
                    email=email,
                    password_hash=password_hash,
                    full_name=full_name,
                    legal_entity_id=legal_entity_id,
                    roles=roles,
                    status=UserStatus.ACTIVE,
                    mfa_type=MFAType.NONE,
                    is_superuser=row.get("is_superuser") == "1",
                    created_by=actor_id,
                    updated_by=actor_id,
                )
                await self.add(user)
                count += 1
            except Exception as e:
                logger.warning(f"Import user failed: {type(e).__name__}")
        return count

    # ==================== STATISTICS & AUDIT ====================

    async def get_statistics(self, legal_entity_id: UUID) -> dict[str, Any]:
        users = [u for u in self._users.values() if u.legal_entity_id == legal_entity_id and u.deleted_at is None]
        total = len(users)
        active = sum(1 for u in users if u.status == UserStatus.ACTIVE)
        locked = sum(1 for u in users if u.status == UserStatus.LOCKED)
        superusers = sum(1 for u in users if u.is_superuser)
        return {
            "total_users": total,
            "active_users": active,
            "locked_users": locked,
            "inactive_users": total - active,
            "superusers": superusers,
            "total_roles": len(self._roles),
            "active_sessions": len(self._sessions),
            "total_login_attempts": len(self._login_attempts),
        }

    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        return self._audit_log[offset : offset + limit]

    async def health_check(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "total_users": len(self._users),
            "total_roles": len(self._roles),
            "active_sessions": len(self._sessions),
            "audit_log_size": len(self._audit_log),
        }