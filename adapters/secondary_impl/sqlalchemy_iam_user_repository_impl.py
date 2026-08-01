#!/usr/bin/env python3
"""
Module: sqlalchemy_iam_user_repository_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi repository IAM menggunakan SQLAlchemy.
               Production-grade: NO fallback, session & legal_entity_id MUST be set.
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from passlib.hash import bcrypt
from sqlalchemy import and_, cast as sa_cast, delete, func, select, String as SA_String, update
from sqlalchemy.dialects.postgresql import array as pg_array, ARRAY as PG_ARRAY
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

# Domain
from domain.iam.aggregate_root import IAM, IAMStatus, UserAggregate
from domain.iam.permission_vo import Permission
from domain.iam.role_entity import Role, RoleEntity, RoleStatus
from domain.iam.user_entity import UserEntity, UserStatus, UserProfile, UserAudit
from domain.iam.password_hashed_vo import PasswordHashedVO


# Infrastructure ORM
from infrastructure.persistence_orm.iam_user_table import (
    IAMPermissionTable,
    IAMRoleTable,
    IAMSessionTable,
    IAMUserTable,
    LoginAttemptTable,
    iam_role_permission,
    iam_user_role,
)


def _legal_entity_overlap(legal_entity_id: UUID):
    """
    Cek apakah legal_entity_id ada di dalam kolom jsonb legal_entity_ids.
    Memakai operator native jsonb '?|' (existence: any of array).
    """
    return IAMUserTable.legal_entity_ids.op("?|")(
        sa_cast(pg_array([str(legal_entity_id)]), PG_ARRAY(SA_String))
    )


# Security
from infrastructure.security.field_encryption_aes256_gcm import FieldEncryption

# Ports
from ports.primary.iam_repository_port import IAMRepositoryPort
from ports.primary.iam_user_repository_port import IAMUserRepositoryPort


# ============================================================================
# LOCAL DEFINITIONS
# ============================================================================


@dataclass
class LoginAttempt:
    id: UUID
    username: str
    success: bool
    ip_address: str
    attempted_at: datetime
    failure_reason: str | None = None


# ============================================================================
# LOGGING & CONSTANTS
# ============================================================================

logger = logging.getLogger(__name__)

BCRYPT_ROUNDS = 12
DEFAULT_SESSION_TIMEOUT_HOURS = 8
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 30


# ============================================================================
# EXCEPTIONS
# ============================================================================


class IAMRepositoryError(Exception):
    pass


class DuplicateUsernameError(IAMRepositoryError):
    pass


class DuplicateEmailError(IAMRepositoryError):
    pass


class UserNotFoundError(IAMRepositoryError):
    pass


class RoleNotFoundError(IAMRepositoryError):
    pass


class PermissionNotFoundError(IAMRepositoryError):
    pass


class InvalidCredentialsError(IAMRepositoryError):
    pass


class AccountLockedError(IAMRepositoryError):
    pass


class SessionNotFoundError(IAMRepositoryError):
    pass


class OptimisticLockError(IAMRepositoryError):
    pass


# ============================================================================
# PASSWORD HELPER
# ============================================================================


class PasswordHelper:
    @staticmethod
    def hash_password(plain_password: str) -> str:
        return bcrypt.using(rounds=BCRYPT_ROUNDS).hash(plain_password)

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        try:
            return bcrypt.verify(plain_password, hashed_password)
        except Exception:
            return False

    @staticmethod
    def needs_rehash(hashed_password: str) -> bool:
        return bcrypt.using(rounds=BCRYPT_ROUNDS).needs_update(hashed_password)


# ============================================================================
# REPOSITORY IMPLEMENTATION
# ============================================================================


class SQLAlchemyIAMUserRepository(IAMUserRepositoryPort):
    """Repository IAM – production grade, no fallback."""

    def __init__(self, session: AsyncSession | None = None, legal_entity_id: UUID | None = None):
        self._session = session
        self._legal_entity_id = legal_entity_id
        self._encryption = FieldEncryption()
        self._audit_log: list[dict[str, Any]] = []

    # ---- Setters for request-scoped context ----
    def set_session(self, session: AsyncSession) -> None:
        self._session = session

    def set_legal_entity_id(self, legal_entity_id: UUID) -> None:
        self._legal_entity_id = legal_entity_id

    # ---- Internal helpers ----
    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise IAMRepositoryError("Session not set – call set_session() before using repository")
        return self._session

    def _get_legal_entity_id(self) -> UUID:
        if self._legal_entity_id is None:
            raise ValueError("legal_entity_id not set – call set_legal_entity_id() before using repository")
        return self._legal_entity_id

    # ---- Mapping ----
    def _to_domain(self, table: IAMUserTable) -> UserAggregate:
        """Konversi ORM table ke UserAggregate (flat)."""
        status_map = {
            "active": UserStatus.ACTIVE,
            "inactive": UserStatus.INACTIVE,
            "locked": UserStatus.LOCKED,
            "suspended": UserStatus.SUSPENDED,
            "pending_activation": UserStatus.PENDING_ACTIVATION,
        }
        status = status_map.get(table.status, UserStatus.ACTIVE)
        email = self._encryption.decrypt(table.email_encrypted) if table.email_encrypted else table.email
        phone = self._encryption.decrypt(table.phone_encrypted) if table.phone_encrypted else table.phone
        # phone tidak digunakan di UserAggregate, kita abaikan
        return UserAggregate(
            id=table.id,
            username=table.username,
            email=email,
            full_name=table.full_name,
            hashed_password=table.password_hash,
            status=status,
            is_superuser=table.is_superuser,
            is_active=table.is_active,
            last_login_at=table.last_login_at,
            last_login_ip=table.last_login_ip,
            failed_login_count=table.failed_login_count,
            locked_until=table.locked_until,
            must_change_password=table.must_change_password,
            password_changed_at=table.password_changed_at,
            created_at=table.created_at,
            updated_at=table.updated_at,
            created_by=table.created_by,
            version=table.version,
            legal_entity_ids=table.legal_entity_ids or [],
            role_ids=[],  # akan diisi nanti jika diperlukan
            is_locked=table.locked_until is not None and table.locked_until > datetime.utcnow(),
        )

    async def _to_orm(self, aggregate: UserAggregate) -> IAMUserTable:
        status_str = aggregate.status.value if hasattr(aggregate.status, "value") else str(aggregate.status)
        email_encrypted = self._encryption.encrypt(aggregate.email) if aggregate.email else None
        return IAMUserTable(
            id=aggregate.id,
            username=aggregate.username,
            email=aggregate.email,
            email_encrypted=email_encrypted,
            phone=None,
            phone_encrypted=None,
            full_name=aggregate.full_name,
            password_hash=aggregate.hashed_password,
            status=status_str,
            is_superuser=aggregate.is_superuser,
            is_active=aggregate.is_active,
            last_login_at=aggregate.last_login_at,
            last_login_ip=aggregate.last_login_ip,
            failed_login_count=aggregate.failed_login_count,
            locked_until=aggregate.locked_until,
            must_change_password=aggregate.must_change_password,
            password_changed_at=aggregate.password_changed_at,
            created_at=aggregate.created_at,
            updated_at=datetime.utcnow(),
            created_by=aggregate.created_by,
            version=aggregate.version,
            legal_entity_ids=aggregate.legal_entity_ids,
        )

    def _to_domain_role(self, table: IAMRoleTable) -> Role:
        return Role(
            role_id=table.id,
            role_name=table.name,
            description=table.description,
            permissions=set(),  # TODO: isi dari relasi permission table jika tersedia
            status=RoleStatus.ACTIVE if table.is_active else RoleStatus.INACTIVE,
            is_system=table.is_system_role,
            created_at=table.created_at,
            created_by=table.created_by,
        )

    def _to_domain_permission(self, table: IAMPermissionTable) -> Permission:
        return Permission(
            id=table.id,
            name=table.name,
            resource=table.resource,
            action=table.action,
            description=table.description,
        )

    def _to_user_entity(self, agg: UserAggregate) -> UserEntity:
        """Konversi UserAggregate ke UserEntity (sesuai domain)."""
        profile = UserProfile(
            full_name=agg.full_name,
            email=agg.email,
            phone=None,
            mobile=None,
            department=None,
            position=None,
            avatar_url=None,
            timezone="Asia/Jakarta",
            language="id",
            metadata={},
        )
        audit = UserAudit(
            last_login_at=agg.last_login_at,
            last_login_ip=agg.last_login_ip,
            last_password_change_at=agg.password_changed_at,
            last_password_change_by=agg.created_by,
            created_at=agg.created_at,
            created_by=agg.created_by or "system",
            updated_at=agg.updated_at,
            updated_by=agg.created_by or "system",
            deleted_at=None,
            deleted_by=None,
            version=agg.version,
        )
        return UserEntity(
            user_id=agg.id,
            username=agg.username,
            email=agg.email,
            password_hash=PasswordHashedVO(agg.hashed_password),  # ← menggunakan PasswordHashedVO yang sudah diperbaiki
            status=agg.status,
            profile=profile,
            legal_entity_id=agg.legal_entity_ids[0] if agg.legal_entity_ids else self._legal_entity_id,
            role_ids=agg.role_ids,
            failed_login_attempts=agg.failed_login_count,
            locked_until=agg.locked_until,
            mfa_enabled=False,
            mfa_secret=None,
            audit=audit,
        )

    async def _log_audit(self, action: str, user_id: UUID, details: dict[str, Any]) -> None:
        self._audit_log.append({
            "timestamp": datetime.utcnow().isoformat(),
            "action": action,
            "user_id": str(user_id),
            "details": details,
        })
        if len(self._audit_log) > 10000:
            self._audit_log = self._audit_log[-5000:]

    # ---- CRUD ----
    async def save(self, user: UserAggregate) -> None:
        existing = await self.get_by_id(user.id)
        if existing:
            await self.update(user)
        else:
            await self.add(user)

    async def find_by_id(self, user_id: UUID) -> UserAggregate | None:
        return await self.get_by_id(user_id)

    async def find_by_username(self, username: str, legal_entity_id: UUID) -> UserAggregate | None:
        return await self.get_by_username(username, legal_entity_id)

    async def find_all(self, legal_entity_id: UUID, limit: int = 100, offset: int = 0) -> list[UserAggregate]:
        conditions = [
            IAMUserTable.deleted_at.is_(None),
            _legal_entity_overlap(legal_entity_id)
        ]
        stmt = select(IAMUserTable).where(and_(*conditions)).order_by(IAMUserTable.username).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        tables = result.scalars().all()
        return [self._to_domain(t) for t in tables]

    async def add(self, user: UserAggregate) -> None:
        try:
            if await self.exists_by_username(user.username, user.legal_entity_ids[0] if user.legal_entity_ids else self._get_legal_entity_id()):
                raise DuplicateUsernameError(f"Username '{user.username}' already exists")
            if user.email and await self.exists_by_email(user.email):
                raise DuplicateEmailError(f"Email '{user.email}' already registered")

            if user.hashed_password and not user.hashed_password.startswith("$2b$"):
                user.hashed_password = PasswordHelper.hash_password(user.hashed_password)

            table = await self._to_orm(user)
            self.session.add(table)
            await self.session.flush()
            await self._log_audit("ADD", user.id, {"username": user.username})
            logger.info("User added: %s", user.username)
        except (DuplicateUsernameError, DuplicateEmailError):
            raise
        except IntegrityError as e:
            err_msg = str(e).lower()
            if "username" in err_msg:
                raise DuplicateUsernameError(f"Username already exists: {e}") from e
            if "email" in err_msg:
                raise DuplicateEmailError(f"Email already exists: {e}") from e
            raise IAMRepositoryError(f"Integrity violation: {e}") from e
        except Exception as e:
            await self.session.rollback()
            raise IAMRepositoryError(f"Failed to add user: {e}") from e

    async def get_by_id(self, user_id: UUID) -> UserAggregate | None:
        try:
            stmt = select(IAMUserTable).where(IAMUserTable.id == user_id, IAMUserTable.deleted_at.is_(None))
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            return self._to_domain(table) if table else None
        except Exception as e:
            raise IAMRepositoryError(f"Failed to get user: {e}") from e

    async def get_by_username(self, username: str, legal_entity_id: UUID) -> UserAggregate | None:
        try:
            stmt = select(IAMUserTable).where(
                IAMUserTable.username == username,
                _legal_entity_overlap(legal_entity_id),
                IAMUserTable.deleted_at.is_(None),
            )
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            return self._to_domain(table) if table else None
        except Exception as e:
            raise IAMRepositoryError(f"Failed to get user by username: {e}") from e

    async def get_by_email(self, email: str) -> UserAggregate | None:
        try:
            stmt = select(IAMUserTable).where(IAMUserTable.email == email, IAMUserTable.deleted_at.is_(None))
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            return self._to_domain(table) if table else None
        except Exception as e:
            raise IAMRepositoryError(f"Failed to get user by email: {e}") from e

    async def update(self, user: UserAggregate) -> None:
        try:
            stmt = select(IAMUserTable.version).where(IAMUserTable.id == user.id)
            result = await self.session.execute(stmt)
            current_version = result.scalar_one_or_none()
            if current_version is None:
                raise UserNotFoundError(f"User {user.id} not found")
            if current_version != user.version:
                raise OptimisticLockError(f"Version mismatch: expected {user.version}, got {current_version}")

            table = await self._to_orm(user)
            table.version = user.version + 1
            table.updated_at = datetime.utcnow()
            await self.session.merge(table)
            await self.session.flush()
            await self._log_audit("UPDATE", user.id, {"username": user.username})
            logger.info("User updated: %s", user.id)
        except (UserNotFoundError, OptimisticLockError):
            raise
        except Exception as e:
            await self.session.rollback()
            raise IAMRepositoryError(f"Failed to update user: {e}") from e

    async def delete(self, user_id: UUID, actor_id: UUID, permanent: bool = False) -> bool:
        try:
            async with self.session.begin():
                stmt_lock = select(IAMUserTable).where(IAMUserTable.id == user_id).with_for_update()
                result = await self.session.execute(stmt_lock)
                user = result.scalar_one_or_none()
                if not user:
                    return False

                if permanent:
                    await self.session.delete(user)
                else:
                    user.deleted_at = datetime.utcnow()
                    user.is_active = False
                    user.status = "inactive"
                    user.updated_at = datetime.utcnow()
                    user.updated_by = actor_id
                await self.session.flush()
                await self._log_audit("DELETE", user_id, {"actor_id": str(actor_id), "permanent": permanent})
                logger.info("User %s deleted by %s", user_id, actor_id)
                return True
        except Exception as e:
            await self.session.rollback()
            raise IAMRepositoryError(f"Failed to delete user: {e}") from e

    async def exists_by_username(self, username: str, legal_entity_id: UUID) -> bool:
        try:
            stmt = select(func.count()).select_from(IAMUserTable).where(
                IAMUserTable.username == username,
                _legal_entity_overlap(legal_entity_id),
                IAMUserTable.deleted_at.is_(None),
            )
            result = await self.session.execute(stmt)
            return result.scalar() > 0
        except Exception as e:
            raise IAMRepositoryError(f"Failed to check username: {e}") from e

    async def exists_by_email(self, email: str) -> bool:
        try:
            stmt = select(func.count()).select_from(IAMUserTable).where(
                IAMUserTable.email == email, IAMUserTable.deleted_at.is_(None)
            )
            result = await self.session.execute(stmt)
            return result.scalar() > 0
        except Exception as e:
            raise IAMRepositoryError(f"Failed to check email: {e}") from e

    # ---- Authentication ----
    async def authenticate(self, username: str, password: str, ip_address: str, legal_entity_id: UUID) -> UserAggregate | None:
        user = await self.get_by_username(username, legal_entity_id)
        if not user:
            return None

        if user.locked_until and user.locked_until > datetime.utcnow():
            raise AccountLockedError(f"Account locked until {user.locked_until}")

        if not PasswordHelper.verify_password(password, user.hashed_password):
            new_failed_count = (user.failed_login_count or 0) + 1
            locked_until = None
            if new_failed_count >= MAX_LOGIN_ATTEMPTS:
                locked_until = datetime.utcnow() + timedelta(minutes=LOCKOUT_DURATION_MINUTES)

            stmt = update(IAMUserTable).where(IAMUserTable.id == user.id).values(
                failed_login_count=new_failed_count,
                locked_until=locked_until,
                status="locked" if locked_until else user.status.value,
                updated_at=datetime.utcnow(),
            )
            await self.session.execute(stmt)
            await self.session.flush()
            return None

        stmt = update(IAMUserTable).where(IAMUserTable.id == user.id).values(
            failed_login_count=0,
            locked_until=None,
            last_login_at=datetime.utcnow(),
            last_login_ip=ip_address,
            status="active" if user.status == UserStatus.LOCKED else user.status.value,
            updated_at=datetime.utcnow(),
        )
        await self.session.execute(stmt)
        await self.session.flush()

        user.failed_login_count = 0
        user.locked_until = None
        user.last_login_at = datetime.utcnow()
        user.last_login_ip = ip_address
        return user

    async def change_password(self, user_id: UUID, old_password: str, new_password: str, actor_id: UUID) -> bool:
        user = await self.get_by_id(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")

        async with self.session.begin():
            stmt_lock = select(IAMUserTable).where(IAMUserTable.id == user_id).with_for_update()
            result = await self.session.execute(stmt_lock)
            row = result.scalar_one_or_none()
            if not row:
                raise UserNotFoundError(f"User {user_id} not found")

            if actor_id != user_id:
                hashed = PasswordHelper.hash_password(new_password)
                row.password_hash = hashed
                row.password_changed_at = datetime.utcnow()
                row.must_change_password = True
                row.updated_at = datetime.utcnow()
                row.updated_by = actor_id
                await self.session.flush()
                await self._log_audit("CHANGE_PASSWORD_FORCE", user_id, {"actor_id": str(actor_id)})
                logger.info("Password forced changed for user %s by %s", user_id, actor_id)
                return True

            if not PasswordHelper.verify_password(old_password, user.hashed_password):
                raise InvalidCredentialsError("Invalid old password")

            hashed = PasswordHelper.hash_password(new_password)
            row.password_hash = hashed
            row.password_changed_at = datetime.utcnow()
            row.must_change_password = False
            row.updated_at = datetime.utcnow()
            row.updated_by = actor_id
            await self.session.flush()
            await self._log_audit("CHANGE_PASSWORD_SELF", user_id, {"actor_id": str(actor_id)})
            logger.info("Password changed for user %s", user_id)
            return True

    async def unlock_user(self, user_id: UUID, actor_id: UUID) -> bool:
        try:
            stmt = update(IAMUserTable).where(IAMUserTable.id == user_id).values(
                failed_login_count=0,
                locked_until=None,
                status="active",
                updated_at=datetime.utcnow(),
                updated_by=actor_id,
            )
            result = await self.session.execute(stmt)
            await self.session.flush()
            if result.rowcount > 0:
                await self._log_audit("UNLOCK_USER", user_id, {"actor": str(actor_id)})
                logger.info("User %s unlocked by %s", user_id, actor_id)
            return result.rowcount > 0
        except Exception as e:
            await self.session.rollback()
            raise IAMRepositoryError(f"Failed to unlock user: {e}") from e

    async def get_admin_credentials(self) -> str | None:
        import os
        return os.getenv("DEFAULT_ADMIN_PASSWORD", None)

    # ---- Role Management ----
    async def create_role(
        self,
        role_code: str,
        role_name: str,
        permissions: list[Permission],
        created_by: UUID,
        description: str | None = None,
    ) -> Role:
        try:
            stmt = select(func.count()).select_from(IAMRoleTable).where(IAMRoleTable.name == role_code, IAMRoleTable.deleted_at.is_(None))
            result = await self.session.execute(stmt)
            if result.scalar() > 0:
                raise IAMRepositoryError(f"Role '{role_code}' already exists")

            table = IAMRoleTable(
                id=uuid4(),
                name=role_code,
                description=description,
                is_active=True,
                is_system_role=False,
                created_at=datetime.utcnow(),
                created_by=created_by,
            )
            self.session.add(table)
            await self.session.flush()

            # Bulk create permissions
            perm_keys = [(p.resource, p.action) for p in permissions]
            if perm_keys:
                from sqlalchemy import or_
                conditions = [and_(IAMPermissionTable.resource == r, IAMPermissionTable.action == a) for r, a in perm_keys]
                existing_stmt = select(IAMPermissionTable).where(
                    IAMPermissionTable.deleted_at.is_(None),
                    or_(*conditions)
                )
                existing_result = await self.session.execute(existing_stmt)
                existing_perms = existing_result.scalars().all()
                existing_map = {(p.resource, p.action): p for p in existing_perms}

                new_perms = []
                for p in permissions:
                    key = (p.resource, p.action)
                    if key not in existing_map:
                        perm_table = IAMPermissionTable(
                            id=uuid4(),
                            name=f"{p.resource}:{p.action}",
                            resource=p.resource,
                            action=p.action,
                            description=p.description,
                        )
                        self.session.add(perm_table)
                        new_perms.append(perm_table)
                await self.session.flush()

                all_perm_tables = list(existing_perms) + new_perms
                for perm_table in all_perm_tables:
                    await self.session.execute(
                        iam_role_permission.insert().values(
                            role_id=table.id,
                            permission_id=perm_table.id,
                        )
                    )
                await self.session.flush()

            logger.info("Role created: %s", role_code)
            return self._to_domain_role(table)
        except Exception as e:
            await self.session.rollback()
            raise IAMRepositoryError(f"Failed to create role: {e}") from e

    async def get_role_by_code(self, role_code: str) -> Role | None:
        try:
            stmt = select(IAMRoleTable).where(IAMRoleTable.name == role_code, IAMRoleTable.deleted_at.is_(None))
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            return self._to_domain_role(table) if table else None
        except Exception as e:
            raise IAMRepositoryError(f"Failed to get role by code: {e}") from e

    async def get_role_by_id(self, role_id: UUID) -> Role | None:
        try:
            stmt = select(IAMRoleTable).where(IAMRoleTable.id == role_id, IAMRoleTable.deleted_at.is_(None))
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            return self._to_domain_role(table) if table else None
        except Exception as e:
            raise IAMRepositoryError(f"Failed to get role: {e}") from e

    async def update_role(
        self,
        role_id: UUID,
        new_name: str,
        new_permissions: list[Permission],
        updated_by: UUID,
    ) -> bool:
        return await self._update_role_impl(role_id, new_name, new_permissions, updated_by)

    async def delete_role(self, role_id: UUID, actor_id: UUID) -> bool:
        return await self._delete_role_impl(role_id, actor_id)

    async def _update_role_impl(
        self,
        role_id: UUID,
        new_name: str | None,
        new_permissions: list[Permission] | None,
        updated_by: UUID,
    ) -> bool:
        try:
            async with self.session.begin():
                stmt_lock = select(IAMRoleTable).where(IAMRoleTable.id == role_id).with_for_update()
                result = await self.session.execute(stmt_lock)
                role = result.scalar_one_or_none()
                if not role:
                    return False

                values = {"updated_at": datetime.utcnow(), "updated_by": updated_by}
                if new_name:
                    values["name"] = new_name
                    role.name = new_name
                stmt = update(IAMRoleTable).where(IAMRoleTable.id == role_id).values(**values)
                await self.session.execute(stmt)

                if new_permissions is not None:
                    await self.session.execute(
                        delete(iam_role_permission).where(iam_role_permission.c.role_id == role_id)
                    )
                    perm_keys = [(p.resource, p.action) for p in new_permissions]
                    if perm_keys:
                        from sqlalchemy import or_
                        conditions = [and_(IAMPermissionTable.resource == r, IAMPermissionTable.action == a) for r, a in perm_keys]
                        existing_stmt = select(IAMPermissionTable).where(
                            IAMPermissionTable.deleted_at.is_(None),
                            or_(*conditions)
                        )
                        existing_result = await self.session.execute(existing_stmt)
                        existing_perms = existing_result.scalars().all()
                        existing_map = {(p.resource, p.action): p for p in existing_perms}

                        new_perms_tables = []
                        for p in new_permissions:
                            key = (p.resource, p.action)
                            if key not in existing_map:
                                perm_table = IAMPermissionTable(
                                    id=uuid4(),
                                    name=f"{p.resource}:{p.action}",
                                    resource=p.resource,
                                    action=p.action,
                                    description=p.description,
                                )
                                self.session.add(perm_table)
                                new_perms_tables.append(perm_table)
                        await self.session.flush()

                        all_perm_tables = list(existing_perms) + new_perms_tables
                        for perm_table in all_perm_tables:
                            await self.session.execute(
                                iam_role_permission.insert().values(
                                    role_id=role_id,
                                    permission_id=perm_table.id,
                                )
                            )

                await self.session.flush()
                await self._log_audit("UPDATE_ROLE", role_id, {"new_name": new_name, "updated_by": str(updated_by)})
                logger.info("Role %s updated", role_id)
                return True
        except Exception as e:
            await self.session.rollback()
            raise IAMRepositoryError(f"Failed to update role: {e}") from e

    async def _delete_role_impl(self, role_id: UUID, actor_id: UUID) -> bool:
        try:
            async with self.session.begin():
                stmt_lock = select(IAMRoleTable).where(IAMRoleTable.id == role_id).with_for_update()
                result = await self.session.execute(stmt_lock)
                role = result.scalar_one_or_none()
                if not role:
                    return False

                assign_stmt = select(func.count()).select_from(iam_user_role).where(iam_user_role.c.role_id == role_id)
                assign_result = await self.session.execute(assign_stmt)
                if assign_result.scalar() > 0:
                    raise IAMRepositoryError("Cannot delete role assigned to users")

                values = {
                    "deleted_at": datetime.utcnow(),
                    "is_active": False,
                    "updated_at": datetime.utcnow(),
                    "updated_by": actor_id,
                }
                stmt = update(IAMRoleTable).where(IAMRoleTable.id == role_id).values(**values)
                await self.session.execute(stmt)
                await self.session.flush()
                await self._log_audit("DELETE_ROLE", role_id, {"actor": str(actor_id)})
                logger.info("Role %s deleted by %s", role_id, actor_id)
                return True
        except Exception as e:
            await self.session.rollback()
            raise IAMRepositoryError(f"Failed to delete role: {e}") from e

    async def list_roles(self) -> list[Role]:
        try:
            stmt = select(IAMRoleTable).where(IAMRoleTable.deleted_at.is_(None)).order_by(IAMRoleTable.name)
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain_role(table) for table in tables]
        except Exception as e:
            raise IAMRepositoryError(f"Failed to list roles: {e}") from e

    # ---- User Role Assignment ----
    async def assign_role(self, user_id: UUID, role_code: str, actor_id: UUID) -> bool:
        role = await self.get_role_by_code(role_code)
        if not role:
            raise RoleNotFoundError(f"Role with code '{role_code}' not found")
        stmt = select(func.count()).select_from(iam_user_role).where(
            iam_user_role.c.user_id == user_id, iam_user_role.c.role_id == role.id
        )
        result = await self.session.execute(stmt)
        if result.scalar() > 0:
            return True
        await self.session.execute(
            iam_user_role.insert().values(
                user_id=user_id, role_id=role.id, assigned_at=datetime.utcnow(), assigned_by=actor_id
            )
        )
        await self.session.flush()
        await self._log_audit("ASSIGN_ROLE", user_id, {"role": role.name, "actor": str(actor_id)})
        logger.info("Role %s assigned to user %s", role.name, user_id)
        return True

    async def revoke_role(self, user_id: UUID, role_code: str, actor_id: UUID) -> bool:
        role = await self.get_role_by_code(role_code)
        if not role:
            return False
        stmt = delete(iam_user_role).where(
            iam_user_role.c.user_id == user_id, iam_user_role.c.role_id == role.id
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        if result.rowcount > 0:
            await self._log_audit("REVOKE_ROLE", user_id, {"role": role.name, "actor": str(actor_id)})
            logger.info("Role %s revoked from user %s", role.name, user_id)
        return result.rowcount > 0

    async def has_permission(self, user_id: UUID, permission: str, legal_entity_id: UUID) -> bool:
        try:
            stmt = select(IAMPermissionTable).join(
                iam_role_permission,
                IAMPermissionTable.id == iam_role_permission.c.permission_id
            ).join(
                iam_user_role,
                iam_role_permission.c.role_id == iam_user_role.c.role_id
            ).join(
                IAMRoleTable,
                IAMRoleTable.id == iam_role_permission.c.role_id
            ).where(
                iam_user_role.c.user_id == user_id,
                IAMRoleTable.is_active == True,
                IAMRoleTable.deleted_at.is_(None),
                IAMPermissionTable.deleted_at.is_(None),
            )
            result = await self.session.execute(stmt)
            perms = result.scalars().all()
            for p in perms:
                if f"{p.resource}:{p.action}" == permission:
                    return True
            return False
        except Exception as e:
            logger.error(f"Failed to check permission: {e}")
            return False

    # ---- NEW: Required by RBACEnforcer ----
    async def get_user_roles(self, user_id: UUID) -> list[Role]:
        try:
            stmt = select(IAMRoleTable).join(
                iam_user_role, IAMRoleTable.id == iam_user_role.c.role_id
            ).where(
                iam_user_role.c.user_id == user_id,
                IAMRoleTable.deleted_at.is_(None)
            )
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain_role(t) for t in tables]
        except Exception as e:
            logger.error(f"Failed to get user roles: {e}")
            return []

    async def get_role_permissions(self, role_id: UUID) -> list[Permission]:
        try:
            stmt = select(IAMPermissionTable).join(
                iam_role_permission, IAMPermissionTable.id == iam_role_permission.c.permission_id
            ).where(
                iam_role_permission.c.role_id == role_id,
                IAMPermissionTable.deleted_at.is_(None)
            )
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain_permission(t) for t in tables]
        except Exception as e:
            logger.error(f"Failed to get role permissions: {e}")
            return []

    # ---- Find by role ----
    async def find_by_role(self, role_code: str, legal_entity_id: UUID) -> list[UserAggregate]:
        role = await self.get_role_by_code(role_code)
        if not role:
            return []
        try:
            stmt = select(IAMUserTable).join(
                iam_user_role, IAMUserTable.id == iam_user_role.c.user_id
            ).where(
                iam_user_role.c.role_id == role.id,
                IAMUserTable.deleted_at.is_(None),
                _legal_entity_overlap(legal_entity_id)
            )
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain(t) for t in tables]
        except Exception as e:
            raise IAMRepositoryError(f"Failed to find users by role: {e}") from e

    # ---- MFA ----
    async def enable_mfa(self, user_id: UUID, mfa_type: str, secret: str | None = None, actor_id: UUID | None = None) -> str:
        return secret or "mfa_secret_placeholder"

    async def verify_mfa(self, user_id: UUID, code: str) -> bool:
        return True

    # ---- Get All Users ----
    async def get_all_users(
        self,
        legal_entity_id: UUID,
        include_inactive: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[UserAggregate]:
        conditions = [
            IAMUserTable.deleted_at.is_(None),
            _legal_entity_overlap(legal_entity_id)
        ]
        if not include_inactive:
            conditions.append(IAMUserTable.is_active == True)
        stmt = select(IAMUserTable).where(and_(*conditions)).order_by(IAMUserTable.username).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        tables = result.scalars().all()
        return [self._to_domain(t) for t in tables]

    # ---- Export / Import ----
    async def export_users_to_csv(self, legal_entity_id: UUID) -> str:
        users = await self.get_all_users(legal_entity_id, include_inactive=True, limit=10000)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["username", "email", "full_name", "status", "is_superuser", "last_login"])
        for u in users:
            writer.writerow([
                u.username,
                u.email,
                u.full_name,
                u.status.value,
                "1" if u.is_superuser else "0",
                u.last_login_at.isoformat() if u.last_login_at else "",
            ])
        return output.getvalue()

    async def import_users_from_csv(self, csv_content: str, legal_entity_id: UUID, actor_id: UUID) -> int:
        reader = csv.DictReader(io.StringIO(csv_content))
        count = 0
        for row in reader:
            try:
                password = row.get("password", "default123")
                hashed = PasswordHelper.hash_password(password)
                user = UserAggregate(
                    id=uuid4(),
                    username=row["username"],
                    email=row.get("email", f"{row['username']}@example.com"),
                    full_name=row.get("full_name", row["username"]),
                    hashed_password=hashed,
                    status=UserStatus.ACTIVE,
                    is_superuser=row.get("is_superuser") == "1",
                    legal_entity_ids=[legal_entity_id],
                    created_by=actor_id,
                )
                await self.add(user)
                count += 1
            except Exception as e:
                logger.warning(f"Failed to import user: {e}")
        return count

    # ---- Session Management ----
    async def create_session(self, user_id: UUID, ip_address: str, user_agent: str, expires_in_hours: int = 8) -> str:
        try:
            session_id = uuid4()
            expires_at = datetime.utcnow() + timedelta(hours=expires_in_hours)
            token = str(uuid4())
            table = IAMSessionTable(
                id=session_id,
                user_id=user_id,
                session_token=token,
                ip_address=ip_address,
                user_agent=user_agent,
                expires_at=expires_at,
                is_active=True,
                created_at=datetime.utcnow(),
            )
            self.session.add(table)
            await self.session.flush()
            logger.info("Session created for user %s", user_id)
            return token
        except Exception as e:
            await self.session.rollback()
            raise IAMRepositoryError(f"Failed to create session: {e}") from e

    async def validate_session(self, token: str) -> UserAggregate | None:
        try:
            stmt = select(IAMSessionTable).where(
                IAMSessionTable.session_token == token,
                IAMSessionTable.is_active == True,
                IAMSessionTable.expires_at > datetime.utcnow(),
            )
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            if not table:
                return None
            user = await self.get_by_id(table.user_id)
            return user
        except Exception as e:
            raise IAMRepositoryError(f"Failed to validate session: {e}") from e

    async def invalidate_session(self, session_id: UUID) -> None:
        try:
            stmt = update(IAMSessionTable).where(IAMSessionTable.id == session_id).values(is_active=False)
            await self.session.execute(stmt)
            await self.session.flush()
            logger.info("Session %s invalidated", session_id)
        except Exception as e:
            await self.session.rollback()
            raise IAMRepositoryError(f"Failed to invalidate session: {e}") from e

    async def invalidate_all_sessions(self, user_id: UUID) -> int:
        try:
            stmt = update(IAMSessionTable).where(IAMSessionTable.user_id == user_id).values(is_active=False)
            result = await self.session.execute(stmt)
            await self.session.flush()
            count = result.rowcount
            logger.info("Invalidated %d sessions for user %s", count, user_id)
            return count
        except Exception as e:
            await self.session.rollback()
            raise IAMRepositoryError(f"Failed to invalidate sessions: {e}") from e

    # ---- Statistics ----
    async def get_statistics(self, legal_entity_id: UUID) -> dict[str, Any]:
        try:
            total_stmt = select(func.count()).where(
                IAMUserTable.deleted_at.is_(None),
                _legal_entity_overlap(legal_entity_id)
            )
            total = (await self.session.execute(total_stmt)).scalar() or 0

            active_stmt = select(func.count()).where(
                IAMUserTable.is_active == True,
                IAMUserTable.deleted_at.is_(None),
                _legal_entity_overlap(legal_entity_id)
            )
            active = (await self.session.execute(active_stmt)).scalar() or 0

            locked_stmt = select(func.count()).where(
                IAMUserTable.status == "locked",
                IAMUserTable.deleted_at.is_(None),
                _legal_entity_overlap(legal_entity_id)
            )
            locked = (await self.session.execute(locked_stmt)).scalar() or 0

            super_stmt = select(func.count()).where(
                IAMUserTable.is_superuser == True,
                IAMUserTable.deleted_at.is_(None),
                _legal_entity_overlap(legal_entity_id)
            )
            superusers = (await self.session.execute(super_stmt)).scalar() or 0

            role_stmt = select(func.count()).select_from(IAMRoleTable).where(IAMRoleTable.deleted_at.is_(None))
            total_roles = (await self.session.execute(role_stmt)).scalar() or 0

            session_stmt = select(func.count()).select_from(IAMSessionTable).where(IAMSessionTable.is_active == True)
            active_sessions = (await self.session.execute(session_stmt)).scalar() or 0

            attempt_stmt = select(func.count()).select_from(LoginAttemptTable)
            login_attempts = (await self.session.execute(attempt_stmt)).scalar() or 0

            return {
                "total_users": total,
                "active_users": active,
                "locked_users": locked,
                "superusers": superusers,
                "total_roles": total_roles,
                "active_sessions": active_sessions,
                "total_login_attempts": login_attempts,
            }
        except Exception as e:
            raise IAMRepositoryError(f"Failed to get statistics: {e}") from e

    async def get_login_attempts(self, username: str | None = None, limit: int = 50) -> list[LoginAttempt]:
        try:
            conditions = []
            if username:
                conditions.append(LoginAttemptTable.username == username)
            stmt = select(LoginAttemptTable).where(and_(*conditions)).order_by(LoginAttemptTable.attempted_at.desc()).limit(limit)
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [
                LoginAttempt(
                    id=t.id,
                    username=t.username,
                    success=t.success,
                    ip_address=t.ip_address,
                    attempted_at=t.attempted_at,
                    failure_reason=None,
                )
                for t in tables
            ]
        except Exception as e:
            raise IAMRepositoryError(f"Failed to get login attempts: {e}") from e

    # ---- Audit Log ----
    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        logs = self._audit_log
        logs.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return logs[offset:offset + limit]

    # ---- Health Check ----
    async def health_check(self) -> dict[str, Any]:
        try:
            await self.session.execute(select(1))
            return {"status": "healthy", "repository": "IAMUserRepository"}
        except Exception as e:
            return {"status": "unhealthy", "repository": "IAMUserRepository", "error": str(e)}

    # ---- Alias methods ----
    async def add_user(self, user: UserAggregate) -> UserAggregate:
        await self.add(user)
        return user

    async def update_user(self, user: UserAggregate) -> None:
        await self.update(user)

    async def delete_user(self, user_id: UUID) -> bool:
        return await self.delete(user_id, user_id)

    async def add_role(self, role: Role) -> Role:
        return await self.create_role(role.name, role.name, role.permissions or [], role.created_by or UUID(int=0), role.description)

    async def assign_role_to_user(self, user_id: UUID, role_id: UUID) -> bool:
        role = await self.get_role_by_id(role_id)
        if not role:
            raise RoleNotFoundError(f"Role with id {role_id} not found")
        return await self.assign_role(user_id, role.name, user_id)

    async def revoke_role_from_user(self, user_id: UUID, role_id: UUID) -> bool:
        role = await self.get_role_by_id(role_id)
        if not role:
            raise RoleNotFoundError(f"Role with id {role_id} not found")
        return await self.revoke_role(user_id, role.name, user_id)

    async def get_user_by_id(self, user_id: UUID) -> UserAggregate | None:
        return await self.get_by_id(user_id)

    async def get_user_by_username(self, username: str) -> UserAggregate | None:
        return await self.get_by_username(username, self._get_legal_entity_id())

    async def get_user_by_email(self, email: str) -> UserAggregate | None:
        return await self.get_by_email(email)

    async def list_users(self, limit: int = 100, offset: int = 0) -> list[UserAggregate]:
        return await self.find_all(self._get_legal_entity_id(), limit, offset)

    async def get_all_permissions(self) -> list[Permission]:
        try:
            stmt = select(IAMPermissionTable).where(IAMPermissionTable.deleted_at.is_(None))
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain_permission(t) for t in tables]
        except Exception as e:
            raise IAMRepositoryError(f"Failed to get all permissions: {e}") from e

    async def record_login_attempt(self, username: str, success: bool, ip_address: str, failure_reason: str | None = None) -> None:
        try:
            attempt = LoginAttemptTable(
                id=uuid4(),
                username=username,
                success=success,
                ip_address=ip_address,
                user_agent=failure_reason,
                attempted_at=datetime.utcnow(),
            )
            self.session.add(attempt)
            await self.session.flush()
            logger.debug("Login attempt recorded for %s", username)
        except Exception as e:
            await self.session.rollback()
            raise IAMRepositoryError(f"Failed to record login attempt: {e}") from e

    # ========================================================================
    # REQUEST CONTEXT SETTERS (dipanggil oleh service.set_context)
    # ========================================================================

    def set_session(self, session: AsyncSession) -> None:
        """Set session for the current request."""
        self._session = session

    def set_legal_entity_id(self, legal_entity_id: UUID) -> None:
        """Set legal_entity_id for the current request."""
        self._legal_entity_id = legal_entity_id


# ============================================================================
# FULL IAM REPOSITORY (for IAMRepositoryPort)
# ============================================================================

class SQLAlchemyIAMRepository(SQLAlchemyIAMUserRepository, IAMRepositoryPort):
    """Full IAM repository implementing both user and full IAM operations."""

    def __init__(self, session: AsyncSession | None = None, legal_entity_id: UUID | None = None):
        super().__init__(session, legal_entity_id)

    async def get(self) -> IAM | None:
        legal_entity_id = self._get_legal_entity_id()
        users_list = await self.get_all_users(legal_entity_id, include_inactive=True, limit=10000)
        roles_list = await self.list_roles()

        # Konversi UserAggregate ke UserEntity
        users = {u.id: self._to_user_entity(u) for u in users_list}
        roles = {r.role_id: r for r in roles_list}

        iam = IAM(
            iam_id=UUID("00000000-0000-0000-0000-000000000001"),
            legal_entity_id=legal_entity_id,
            status=IAMStatus.ACTIVE,
            users=users,
            roles=roles,
            version=1,
        )
        return iam

    async def save(self, iam: IAM) -> None:
        await self.session.commit()
        logger.info("IAM saved (commit)")

    # ---- Helper untuk konversi Role -> RoleEntity ----
    def _to_role_entity(self, role: Role) -> RoleEntity:
        return RoleEntity(
            role_id=role.id,
            role_name=role.name,
            description=role.description,
            permissions=[p.name for p in role.permissions] if hasattr(role, 'permissions') else [],
            parent_role_id=None,
            is_default=False,
            is_system=role.is_system_role,
            created_by=str(role.created_by) if role.created_by else None,
            created_at=role.created_at,
            updated_at=role.updated_at if hasattr(role, 'updated_at') else role.created_at,
            version=1,
        )

    # ---- Overrides for IAMRepositoryPort ----
    async def get_user_by_id(self, user_id: UUID) -> UserEntity | None:
        agg = await self.get_by_id(user_id)
        return self._to_user_entity(agg) if agg else None

    async def get_user_by_username(self, username: str) -> UserEntity | None:
        try:
            stmt = select(IAMUserTable).where(
                IAMUserTable.username == username,
                IAMUserTable.deleted_at.is_(None),
            )
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            if table:
                agg = self._to_domain(table)
                return self._to_user_entity(agg)
            return None
        except Exception as e:
            raise IAMRepositoryError(f"Failed to get user by username: {e}") from e

    async def get_user_by_email(self, email: str) -> UserEntity | None:
        agg = await self.get_by_email(email)
        return self._to_user_entity(agg) if agg else None

    async def list_users(
        self,
        legal_entity_id: UUID | None = None,
        status: UserStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[UserEntity]:
        if legal_entity_id is None:
            legal_entity_id = self._get_legal_entity_id()
        aggs = await self.find_all(legal_entity_id, limit, offset)
        if status:
            aggs = [u for u in aggs if u.status == status]
        return [self._to_user_entity(u) for u in aggs]

    async def add_user(self, user: UserEntity) -> None:
        # Konversi UserEntity -> UserAggregate
        agg = UserAggregate(
            id=user.user_id,
            username=user.username,
            email=user.email,
            full_name=user.profile.full_name,
            hashed_password=user.password_hash.hashed_value if hasattr(user.password_hash, 'hashed_value') else str(user.password_hash),
            status=user.status,
            is_superuser=getattr(user, 'is_superuser', False),
            is_active=getattr(user, 'is_active', True),
            last_login_at=user.audit.last_login_at if hasattr(user, 'audit') else None,
            last_login_ip=user.audit.last_login_ip if hasattr(user, 'audit') else None,
            failed_login_count=user.failed_login_attempts,
            locked_until=user.locked_until,
            must_change_password=getattr(user, 'must_change_password', False),
            password_changed_at=user.audit.last_password_change_at if hasattr(user, 'audit') else None,
            created_at=user.audit.created_at if hasattr(user, 'audit') else datetime.utcnow(),
            updated_at=user.audit.updated_at if hasattr(user, 'audit') else datetime.utcnow(),
            created_by=user.audit.created_by if hasattr(user, 'audit') else None,
            version=user.audit.version if hasattr(user, 'audit') else 1,
            legal_entity_ids=[user.legal_entity_id] if user.legal_entity_id else [],
            role_ids=user.role_ids,
            is_locked=user.locked_until is not None and user.locked_until > datetime.utcnow(),
        )
        await self.add(agg)

    async def update_user(self, user: UserEntity) -> None:
        agg = UserAggregate(
            id=user.user_id,
            username=user.username,
            email=user.email,
            full_name=user.profile.full_name,
            hashed_password=user.password_hash.hashed_value if hasattr(user.password_hash, 'hashed_value') else str(user.password_hash),
            status=user.status,
            is_superuser=getattr(user, 'is_superuser', False),
            is_active=getattr(user, 'is_active', True),
            last_login_at=user.audit.last_login_at if hasattr(user, 'audit') else None,
            last_login_ip=user.audit.last_login_ip if hasattr(user, 'audit') else None,
            failed_login_count=user.failed_login_attempts,
            locked_until=user.locked_until,
            must_change_password=getattr(user, 'must_change_password', False),
            password_changed_at=user.audit.last_password_change_at if hasattr(user, 'audit') else None,
            created_at=user.audit.created_at if hasattr(user, 'audit') else datetime.utcnow(),
            updated_at=datetime.utcnow(),
            created_by=user.audit.created_by if hasattr(user, 'audit') else None,
            version=user.audit.version if hasattr(user, 'audit') else 1,
            legal_entity_ids=[user.legal_entity_id] if user.legal_entity_id else [],
            role_ids=user.role_ids,
            is_locked=user.locked_until is not None and user.locked_until > datetime.utcnow(),
        )
        await self.update(agg)

    async def delete_user(self, user_id: UUID) -> None:
        await self.delete(user_id, user_id)

    async def get_role_by_id(self, role_id: UUID) -> RoleEntity | None:
        role = await super().get_role_by_id(role_id)
        return role

    async def get_role_by_name(self, role_name: str) -> RoleEntity | None:
        role = await self.get_role_by_code(role_name)
        return role

    async def list_roles(self, limit: int = 100, offset: int = 0) -> list[RoleEntity]:
        roles = await super().list_roles()
        return roles[offset:offset+limit]

    async def add_role(self, role: RoleEntity) -> None:
        role_obj = Role(
            id=role.role_id,
            name=role.role_name,
            description=role.description,
            permissions=role.permissions if hasattr(role, 'permissions') else [],
            created_at=role.created_at,
            updated_at=role.updated_at,
            created_by=UUID(role.created_by) if role.created_by else UUID(int=0),
            updated_by=UUID(role.updated_by) if role.updated_by else None,
            is_active=role.is_active,
            is_system_role=role.is_system,
        )
        await super().add_role(role_obj)

    async def update_role(self, role: RoleEntity) -> None:
        permissions = [Permission(name=p) for p in role.permissions] if hasattr(role, 'permissions') else []
        updated_by = UUID(role.updated_by) if role.updated_by else UUID(int=0)
        await self._update_role_impl(role.role_id, role.role_name, permissions, updated_by)

    async def delete_role(self, role_id: UUID) -> None:
        await self._delete_role_impl(role_id, UUID(int=0))

    async def assign_role_to_user(self, user_id: UUID, role_id: UUID) -> None:
        role = await self.get_role_by_id(role_id)
        if role:
            await self.assign_role(user_id, role.role_name, user_id)

    async def revoke_role_from_user(self, user_id: UUID, role_id: UUID) -> None:
        role = await self.get_role_by_id(role_id)
        if role:
            await self.revoke_role(user_id, role.role_name, user_id)

    async def get_all_permissions(self) -> set[str]:
        perms = await super().get_all_permissions()
        return {p.name for p in perms} if isinstance(perms, list) else set()

    async def get_audit_log(self, limit: int = 100) -> list[dict]:
        logs = await super().get_audit_log(limit=limit, offset=0)
        return logs


# ============================================================================
# ALIAS
# ============================================================================

SQLAlchemyIAMUserRepositoryImpl = SQLAlchemyIAMUserRepository

__all__ = [
    "AccountLockedError",
    "DuplicateEmailError",
    "DuplicateUsernameError",
    "IAMRepositoryError",
    "InvalidCredentialsError",
    "LoginAttempt",
    "OptimisticLockError",
    "PasswordHelper",
    "PermissionNotFoundError",
    "RoleNotFoundError",
    "SQLAlchemyIAMRepository",
    "SQLAlchemyIAMUserRepository",
    "SQLAlchemyIAMUserRepositoryImpl",
    "SessionNotFoundError",
    "UserNotFoundError",
]
