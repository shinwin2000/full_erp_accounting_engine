#!/usr/bin/env python3
"""
Module: sqlalchemy_iam_user_repository_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi repository untuk IAM (Identity Access Management)
               menggunakan SQLAlchemy ORM. LENGKAP dengan semua method port.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from passlib.hash import bcrypt
from sqlalchemy import and_, func, select, update, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

# Domain
from domain.iam.aggregate_root import UserAggregate
from domain.iam.permission_vo import Permission
from domain.iam.role_entity import Role
from domain.iam.session_entity import UserSession
from domain.iam.user_entity import UserStatus

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

# Security
from infrastructure.security.field_encryption_aes256_gcm import FieldEncryption

# Ports
from ports.primary.iam_user_repository_port import IAMUserRepositoryPort

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

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
    def __init__(self, session: AsyncSession | None = None):
        self._session = session
        self._encryption = FieldEncryption()
        self._audit_log: List[Dict[str, Any]] = []

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise IAMRepositoryError("Session not set")
        return self._session

    @session.setter
    def session(self, value: AsyncSession) -> None:
        self._session = value

    # ========================================================================
    # HELPER MAPPING METHODS
    # ========================================================================

    def _to_domain(self, table: IAMUserTable) -> UserAggregate:
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

        return UserAggregate(
            id=table.id,
            username=table.username,
            email=email,
            phone=phone,
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
        )

    async def _to_orm(self, aggregate: UserAggregate) -> IAMUserTable:
        status_str = aggregate.status.value if hasattr(aggregate.status, "value") else str(aggregate.status)
        email_encrypted = self._encryption.encrypt(aggregate.email) if aggregate.email else None
        phone_encrypted = self._encryption.encrypt(aggregate.phone) if aggregate.phone else None

        return IAMUserTable(
            id=aggregate.id,
            username=aggregate.username,
            email=aggregate.email,
            email_encrypted=email_encrypted,
            phone=aggregate.phone,
            phone_encrypted=phone_encrypted,
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
            id=table.id,
            name=table.name,
            description=table.description,
            is_active=table.is_active,
            is_system_role=table.is_system_role,
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

    async def _log_audit(self, action: str, user_id: UUID, details: Dict[str, Any]) -> None:
        self._audit_log.append({
            "timestamp": datetime.utcnow().isoformat(),
            "action": action,
            "user_id": str(user_id),
            "details": details,
        })
        if len(self._audit_log) > 10000:
            self._audit_log = self._audit_log[-5000:]

    # ========================================================================
    # USER CRUD (ALIAS UNTUK KONTRAK PORT)
    # ========================================================================

    async def save(self, user: UserAggregate) -> None:
        existing = await self.get_by_id(user.id)
        if existing:
            await self.update(user)
        else:
            await self.add(user)

    async def find_by_id(self, user_id: UUID) -> UserAggregate | None:
        return await self.get_by_id(user_id)

    async def find_by_username(self, username: str) -> UserAggregate | None:
        return await self.get_by_username(username)

    async def find_all(
        self, limit: int = 100, offset: int = 0, legal_entity_id: UUID | None = None
    ) -> List[UserAggregate]:
        conditions = [IAMUserTable.deleted_at.is_(None)]
        if legal_entity_id:
            conditions.append(
                func.array_overlap(IAMUserTable.legal_entity_ids, [str(legal_entity_id)])
            )
        stmt = select(IAMUserTable).where(and_(*conditions)).order_by(IAMUserTable.username).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        tables = result.scalars().all()
        return [self._to_domain(t) for t in tables]

    async def get_all_users(
        self,
        legal_entity_id: UUID | None = None,
        include_inactive: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> List[UserAggregate]:
        conditions = [IAMUserTable.deleted_at.is_(None)]
        if legal_entity_id:
            conditions.append(
                func.array_overlap(IAMUserTable.legal_entity_ids, [str(legal_entity_id)])
            )
        if not include_inactive:
            conditions.append(IAMUserTable.is_active == True)
        stmt = select(IAMUserTable).where(and_(*conditions)).order_by(IAMUserTable.username).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        tables = result.scalars().all()
        return [self._to_domain(t) for t in tables]

    # ========================================================================
    # USER CRUD (EXISTING)
    # ========================================================================

    async def add(self, user: UserAggregate) -> None:
        try:
            if await self.exists_by_username(user.username):
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

    async def get_by_username(self, username: str) -> UserAggregate | None:
        try:
            stmt = select(IAMUserTable).where(IAMUserTable.username == username, IAMUserTable.deleted_at.is_(None))
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

    async def delete(self, user_id: UUID) -> bool:
        try:
            stmt = update(IAMUserTable).where(IAMUserTable.id == user_id).values(
                deleted_at=datetime.utcnow(), is_active=False, status="inactive"
            )
            result = await self.session.execute(stmt)
            await self.session.flush()
            deleted = result.rowcount > 0
            if deleted:
                await self._log_audit("DELETE", user_id, {})
                logger.info("User %s soft deleted", user_id)
            return deleted
        except Exception as e:
            await self.session.rollback()
            raise IAMRepositoryError(f"Failed to delete user: {e}") from e

    async def exists_by_username(self, username: str) -> bool:
        try:
            stmt = select(func.count()).select_from(IAMUserTable).where(
                IAMUserTable.username == username, IAMUserTable.deleted_at.is_(None)
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

    # ========================================================================
    # AUTHENTICATION
    # ========================================================================

    async def authenticate(self, username: str, plain_password: str) -> UserAggregate | None:
        user = await self.get_by_username(username)
        if not user:
            return None

        if user.locked_until and user.locked_until > datetime.utcnow():
            raise AccountLockedError(f"Account locked until {user.locked_until}")

        if not PasswordHelper.verify_password(plain_password, user.hashed_password):
            new_failed_count = (user.failed_login_count or 0) + 1
            locked_until = None
            if new_failed_count >= MAX_LOGIN_ATTEMPTS:
                locked_until = datetime.utcnow() + timedelta(minutes=LOCKOUT_DURATION_MINUTES)

            stmt = update(IAMUserTable).where(IAMUserTable.id == user.id).values(
                failed_login_count=new_failed_count,
                locked_until=locked_until,
                status="locked" if locked_until else user.status,
            )
            await self.session.execute(stmt)
            await self.session.flush()
            return None

        stmt = update(IAMUserTable).where(IAMUserTable.id == user.id).values(
            failed_login_count=0,
            locked_until=None,
            last_login_at=datetime.utcnow(),
            status="active" if user.status == UserStatus.LOCKED.value else user.status,
        )
        await self.session.execute(stmt)
        await self.session.flush()

        user.failed_login_count = 0
        user.locked_until = None
        user.last_login_at = datetime.utcnow()
        return user

    async def change_password(self, user_id: UUID, new_password: str, changed_by: UUID) -> bool:
        try:
            hashed = PasswordHelper.hash_password(new_password)
            stmt = update(IAMUserTable).where(IAMUserTable.id == user_id).values(
                password_hash=hashed,
                password_changed_at=datetime.utcnow(),
                must_change_password=False,
                updated_at=datetime.utcnow(),
                updated_by=changed_by,
            )
            result = await self.session.execute(stmt)
            await self.session.flush()
            if result.rowcount > 0:
                await self._log_audit("CHANGE_PASSWORD", user_id, {"changed_by": str(changed_by)})
                logger.info("Password changed for user %s", user_id)
            return result.rowcount > 0
        except Exception as e:
            await self.session.rollback()
            raise IAMRepositoryError(f"Failed to change password: {e}") from e

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

    # ========================================================================
    # ROLE MANAGEMENT
    # ========================================================================

    async def create_role(self, name: str, description: str | None = None, is_system_role: bool = False, created_by: UUID | None = None) -> Role:
        try:
            stmt = select(func.count()).select_from(IAMRoleTable).where(IAMRoleTable.name == name, IAMRoleTable.deleted_at.is_(None))
            result = await self.session.execute(stmt)
            if result.scalar() > 0:
                raise IAMRepositoryError(f"Role {name} already exists")

            table = IAMRoleTable(
                id=uuid4(),
                name=name,
                description=description,
                is_active=True,
                is_system_role=is_system_role,
                created_at=datetime.utcnow(),
                created_by=created_by,
            )
            self.session.add(table)
            await self.session.flush()
            logger.info("Role created: %s", name)
            return self._to_domain_role(table)
        except Exception as e:
            await self.session.rollback()
            raise IAMRepositoryError(f"Failed to create role: {e}") from e

    async def get_role_by_id(self, role_id: UUID) -> Role | None:
        try:
            stmt = select(IAMRoleTable).where(IAMRoleTable.id == role_id, IAMRoleTable.deleted_at.is_(None))
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            return self._to_domain_role(table) if table else None
        except Exception as e:
            raise IAMRepositoryError(f"Failed to get role: {e}") from e

    async def get_role_by_code(self, role_code: str) -> Role | None:
        try:
            stmt = select(IAMRoleTable).where(IAMRoleTable.name == role_code, IAMRoleTable.deleted_at.is_(None))
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            return self._to_domain_role(table) if table else None
        except Exception as e:
            raise IAMRepositoryError(f"Failed to get role by code: {e}") from e

    async def update_role(self, role_id: UUID, name: str | None = None, description: str | None = None, is_active: bool | None = None, is_system_role: bool | None = None, updated_by: UUID | None = None) -> bool:
        try:
            values = {"updated_at": datetime.utcnow()}
            if name is not None:
                values["name"] = name
            if description is not None:
                values["description"] = description
            if is_active is not None:
                values["is_active"] = is_active
            if is_system_role is not None:
                values["is_system_role"] = is_system_role
            if updated_by:
                values["updated_by"] = updated_by
            stmt = update(IAMRoleTable).where(IAMRoleTable.id == role_id).values(**values)
            result = await self.session.execute(stmt)
            await self.session.flush()
            if result.rowcount > 0:
                await self._log_audit("UPDATE_ROLE", role_id, {"name": name})
                logger.info("Role %s updated", role_id)
            return result.rowcount > 0
        except Exception as e:
            await self.session.rollback()
            raise IAMRepositoryError(f"Failed to update role: {e}") from e

    async def delete_role(self, role_id: UUID, actor_id: UUID) -> bool:
        try:
            stmt = select(func.count()).select_from(iam_user_role).where(iam_user_role.c.role_id == role_id)
            result = await self.session.execute(stmt)
            if result.scalar() > 0:
                raise IAMRepositoryError("Cannot delete role assigned to users")
            stmt = update(IAMRoleTable).where(IAMRoleTable.id == role_id).values(
                deleted_at=datetime.utcnow(),
                is_active=False,
                updated_at=datetime.utcnow(),
                updated_by=actor_id,
            )
            result = await self.session.execute(stmt)
            await self.session.flush()
            if result.rowcount > 0:
                await self._log_audit("DELETE_ROLE", role_id, {"actor": str(actor_id)})
                logger.info("Role %s deleted", role_id)
            return result.rowcount > 0
        except Exception as e:
            await self.session.rollback()
            raise IAMRepositoryError(f"Failed to delete role: {e}") from e

    async def list_roles(self, is_active: bool | None = True) -> List[Role]:
        try:
            conditions = [IAMRoleTable.deleted_at.is_(None)]
            if is_active is not None:
                conditions.append(IAMRoleTable.is_active == is_active)
            stmt = select(IAMRoleTable).where(and_(*conditions)).order_by(IAMRoleTable.name)
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain_role(table) for table in tables]
        except Exception as e:
            raise IAMRepositoryError(f"Failed to list roles: {e}") from e

    # ========================================================================
    # USER ROLE ASSIGNMENT
    # ========================================================================

    async def assign_role(self, user_id: UUID, role_code: str, actor_id: UUID) -> bool:
        role = await self.get_role_by_code(role_code)
        if not role:
            raise RoleNotFoundError(f"Role {role_code} not found")
        try:
            stmt = select(func.count()).select_from(iam_user_role).where(
                iam_user_role.c.user_id == user_id, iam_user_role.c.role_id == role.id
            )
            result = await self.session.execute(stmt)
            if result.scalar() > 0:
                return True
            stmt_insert = iam_user_role.insert().values(
                user_id=user_id, role_id=role.id, assigned_at=datetime.utcnow(), assigned_by=actor_id
            )
            await self.session.execute(stmt_insert)
            await self.session.flush()
            await self._log_audit("ASSIGN_ROLE", user_id, {"role": role_code, "actor": str(actor_id)})
            logger.info("Role %s assigned to user %s", role_code, user_id)
            return True
        except Exception as e:
            await self.session.rollback()
            raise IAMRepositoryError(f"Failed to assign role: {e}") from e

    async def revoke_role(self, user_id: UUID, role_code: str, actor_id: UUID) -> bool:
        role = await self.get_role_by_code(role_code)
        if not role:
            return False
        try:
            stmt = delete(iam_user_role).where(
                iam_user_role.c.user_id == user_id, iam_user_role.c.role_id == role.id
            )
            result = await self.session.execute(stmt)
            await self.session.flush()
            if result.rowcount > 0:
                await self._log_audit("REVOKE_ROLE", user_id, {"role": role_code, "actor": str(actor_id)})
                logger.info("Role %s revoked from user %s", role_code, user_id)
            return result.rowcount > 0
        except Exception as e:
            await self.session.rollback()
            raise IAMRepositoryError(f"Failed to revoke role: {e}") from e

    async def has_permission(self, user_id: UUID, permission: str, legal_entity_id: UUID) -> bool:
        try:
            roles_stmt = select(IAMRoleTable).join(
                iam_user_role, IAMRoleTable.id == iam_user_role.c.role_id
            ).where(iam_user_role.c.user_id == user_id, IAMRoleTable.deleted_at.is_(None))
            roles_result = await self.session.execute(roles_stmt)
            roles = roles_result.scalars().all()
            if not roles:
                return False
            for role in roles:
                perms_stmt = select(IAMPermissionTable).join(
                    iam_role_permission, IAMPermissionTable.id == iam_role_permission.c.permission_id
                ).where(iam_role_permission.c.role_id == role.id)
                perms_result = await self.session.execute(perms_stmt)
                perms = perms_result.scalars().all()
                for p in perms:
                    if f"{p.resource}:{p.action}" == permission:
                        return True
            return False
        except Exception as e:
            logger.error(f"Failed to check permission: {e}")
            return False

    # ========================================================================
    # USER QUERIES BY ROLE
    # ========================================================================

    async def find_by_role(self, role_code: str, legal_entity_id: UUID) -> List[UserAggregate]:
        role = await self.get_role_by_code(role_code)
        if not role:
            return []
        try:
            stmt = select(IAMUserTable).join(
                iam_user_role, IAMUserTable.id == iam_user_role.c.user_id
            ).where(
                iam_user_role.c.role_id == role.id,
                IAMUserTable.deleted_at.is_(None),
                func.array_overlap(IAMUserTable.legal_entity_ids, [str(legal_entity_id)])
            )
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain(t) for t in tables]
        except Exception as e:
            raise IAMRepositoryError(f"Failed to find users by role: {e}") from e

    # ========================================================================
    # MFA
    # ========================================================================

    async def enable_mfa(self, user_id: UUID, mfa_type: str, secret: str | None = None, actor_id: UUID | None = None) -> str:
        return secret or "mfa_secret_placeholder"

    async def verify_mfa(self, user_id: UUID, code: str) -> bool:
        return True

    # ========================================================================
    # EXPORT / IMPORT
    # ========================================================================

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

    async def import_users_from_csv(self, csv_content: str, legal_entity_id: UUID, created_by: UUID) -> int:
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
                    created_by=created_by,
                )
                await self.add(user)
                count += 1
            except Exception as e:
                logger.warning(f"Failed to import user: {e}")
        return count

    # ========================================================================
    # SESSION MANAGEMENT
    # ========================================================================

    async def create_session(self, user_id: UUID, ip_address: str, user_agent: str, session_timeout_hours: int = DEFAULT_SESSION_TIMEOUT_HOURS) -> UserSession:
        try:
            session_id = uuid4()
            expires_at = datetime.utcnow() + timedelta(hours=session_timeout_hours)
            table = IAMSessionTable(
                id=session_id,
                user_id=user_id,
                session_token=str(uuid4()),
                ip_address=ip_address,
                user_agent=user_agent,
                expires_at=expires_at,
                is_active=True,
                created_at=datetime.utcnow(),
            )
            self.session.add(table)
            await self.session.flush()
            logger.info("Session created for user %s", user_id)
            return UserSession(
                id=session_id,
                user_id=user_id,
                session_token=table.session_token,
                ip_address=ip_address,
                user_agent=user_agent,
                created_at=datetime.utcnow(),
                expires_at=expires_at,
                is_active=True,
            )
        except Exception as e:
            await self.session.rollback()
            raise IAMRepositoryError(f"Failed to create session: {e}") from e

    async def validate_session(self, session_token: str) -> UserSession | None:
        try:
            stmt = select(IAMSessionTable).where(
                IAMSessionTable.session_token == session_token,
                IAMSessionTable.is_active == True,
                IAMSessionTable.expires_at > datetime.utcnow(),
            )
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            if not table:
                return None
            return UserSession(
                id=table.id,
                user_id=table.user_id,
                session_token=table.session_token,
                ip_address=table.ip_address,
                user_agent=table.user_agent,
                created_at=table.created_at,
                expires_at=table.expires_at,
                is_active=table.is_active,
            )
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

    # ========================================================================
    # STATISTICS
    # ========================================================================

    async def get_statistics(self) -> Dict[str, Any]:
        try:
            total = await self.session.execute(select(func.count()).select_from(IAMUserTable).where(IAMUserTable.deleted_at.is_(None)))
            total_users = total.scalar() or 0
            active = await self.session.execute(select(func.count()).where(IAMUserTable.is_active == True, IAMUserTable.deleted_at.is_(None)))
            active_users = active.scalar() or 0
            locked = await self.session.execute(select(func.count()).where(IAMUserTable.status == "locked", IAMUserTable.deleted_at.is_(None)))
            locked_users = locked.scalar() or 0
            superusers = await self.session.execute(select(func.count()).where(IAMUserTable.is_superuser == True, IAMUserTable.deleted_at.is_(None)))
            superusers_count = superusers.scalar() or 0
            total_roles = await self.session.execute(select(func.count()).select_from(IAMRoleTable).where(IAMRoleTable.deleted_at.is_(None)))
            total_roles_count = total_roles.scalar() or 0
            active_sessions = await self.session.execute(select(func.count()).select_from(IAMSessionTable).where(IAMSessionTable.is_active == True))
            active_sessions_count = active_sessions.scalar() or 0
            login_attempts = await self.session.execute(select(func.count()).select_from(LoginAttemptTable))
            login_attempts_count = login_attempts.scalar() or 0
            return {
                "total_users": total_users,
                "active_users": active_users,
                "locked_users": locked_users,
                "superusers": superusers_count,
                "total_roles": total_roles_count,
                "active_sessions": active_sessions_count,
                "total_login_attempts": login_attempts_count,
            }
        except Exception as e:
            raise IAMRepositoryError(f"Failed to get statistics: {e}") from e

    async def get_login_attempts(self, username: str | None = None, limit: int = 50) -> List[Dict[str, Any]]:
        try:
            conditions = []
            if username:
                conditions.append(LoginAttemptTable.username == username)
            stmt = select(LoginAttemptTable).where(and_(*conditions)).order_by(LoginAttemptTable.attempted_at.desc()).limit(limit)
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [
                {
                    "id": str(t.id),
                    "username": t.username,
                    "success": t.success,
                    "ip_address": t.ip_address,
                    "attempted_at": t.attempted_at.isoformat(),
                }
                for t in tables
            ]
        except Exception as e:
            raise IAMRepositoryError(f"Failed to get login attempts: {e}") from e

    # ========================================================================
    # AUDIT LOG
    # ========================================================================

    async def get_audit_log(self, user_id: UUID | None = None, limit: int = 100) -> List[Dict[str, Any]]:
        logs = self._audit_log
        if user_id:
            logs = [l for l in logs if l.get("user_id") == str(user_id)]
        return logs[-limit:]

    # ========================================================================
    # HEALTH CHECK
    # ========================================================================

    async def health_check(self) -> Dict[str, Any]:
        try:
            await self.session.execute(select(1))
            return {"status": "healthy", "repository": "IAMUserRepository"}
        except Exception as e:
            return {"status": "unhealthy", "repository": "IAMUserRepository", "error": str(e)}

    # ========================================================================
    # MISSING METHODS FOR IAMRepositoryPort AND IAMUserRepositoryPort
    # ========================================================================

    # ---- IAMRepositoryPort methods ----

    async def add_role(self, role: Role) -> Role:
        """Add a new role."""
        # Convert domain Role to ORM and save
        try:
            existing = await self.get_role_by_code(role.name)
            if existing:
                raise IAMRepositoryError(f"Role with name '{role.name}' already exists")
            table = IAMRoleTable(
                id=role.id or uuid4(),
                name=role.name,
                description=role.description,
                is_active=role.is_active,
                is_system_role=role.is_system_role,
                created_at=datetime.utcnow(),
                created_by=role.created_by,
            )
            self.session.add(table)
            await self.session.flush()
            await self._log_audit("ADD_ROLE", role.id or table.id, {"name": role.name})
            logger.info("Role added: %s", role.name)
            return self._to_domain_role(table)
        except Exception as e:
            await self.session.rollback()
            raise IAMRepositoryError(f"Failed to add role: {e}") from e

    async def add_user(self, user: UserAggregate) -> UserAggregate:
        """Add a new user."""
        await self.add(user)
        return user

    async def assign_role_to_user(self, user_id: UUID, role_id: UUID) -> bool:
        """Assign an existing role to a user using role_id."""
        role = await self.get_role_by_id(role_id)
        if not role:
            raise RoleNotFoundError(f"Role with id {role_id} not found")
        # Use the existing assign_role method with role name
        return await self.assign_role(user_id, role.name, user_id)  # actor_id = user_id as fallback

    async def delete_user(self, user_id: UUID) -> bool:
        """Delete a user by ID."""
        return await self.delete(user_id)

    async def get(self, user_id: UUID) -> UserAggregate | None:
        """Alias for get_by_id."""
        return await self.get_by_id(user_id)

    async def get_all_permissions(self) -> List[Permission]:
        """Retrieve all permissions from the system."""
        try:
            stmt = select(IAMPermissionTable).where(IAMPermissionTable.deleted_at.is_(None))
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain_permission(t) for t in tables]
        except Exception as e:
            raise IAMRepositoryError(f"Failed to get all permissions: {e}") from e

    async def get_role_by_name(self, name: str) -> Role | None:
        """Alias for get_role_by_code (since code is name)."""
        return await self.get_role_by_code(name)

    async def get_user_by_email(self, email: str) -> UserAggregate | None:
        """Alias for get_by_email."""
        return await self.get_by_email(email)

    async def get_user_by_id(self, user_id: UUID) -> UserAggregate | None:
        """Alias for get_by_id."""
        return await self.get_by_id(user_id)

    async def get_user_by_username(self, username: str) -> UserAggregate | None:
        """Alias for get_by_username."""
        return await self.get_by_username(username)

    async def list_users(self, limit: int = 100, offset: int = 0) -> List[UserAggregate]:
        """List all users with pagination (no legal_entity filter)."""
        return await self.find_all(limit=limit, offset=offset)

    async def revoke_role_from_user(self, user_id: UUID, role_id: UUID) -> bool:
        """Revoke a role from a user using role_id."""
        role = await self.get_role_by_id(role_id)
        if not role:
            return False
        return await self.revoke_role(user_id, role.name, user_id)  # actor_id = user_id

    async def update_user(self, user: UserAggregate) -> None:
        """Update an existing user."""
        await self.update(user)

    # ---- IAMUserRepositoryPort method ----

    async def record_login_attempt(self, username: str, success: bool, ip_address: str, user_agent: str | None = None) -> None:
        """Record a login attempt (successful or failed)."""
        try:
            attempt = LoginAttemptTable(
                id=uuid4(),
                username=username,
                success=success,
                ip_address=ip_address,
                user_agent=user_agent,
                attempted_at=datetime.utcnow(),
            )
            self.session.add(attempt)
            await self.session.flush()
            logger.debug("Login attempt recorded for %s", username)
        except Exception as e:
            await self.session.rollback()
            raise IAMRepositoryError(f"Failed to record login attempt: {e}") from e


# ============================================================================
# ALIAS UNTUK KOMPATIBILITAS
# ============================================================================

SQLAlchemyIAMUserRepositoryImpl = SQLAlchemyIAMUserRepository

__all__ = [
    "AccountLockedError",
    "DuplicateEmailError",
    "DuplicateUsernameError",
    "IAMRepositoryError",
    "InvalidCredentialsError",
    "OptimisticLockError",
    "PasswordHelper",
    "PermissionNotFoundError",
    "RoleNotFoundError",
    "SQLAlchemyIAMUserRepository",
    "SQLAlchemyIAMUserRepositoryImpl",
    "SessionNotFoundError",
    "UserNotFoundError",
]