#!/usr/bin/env python3
"""
Module: sqlalchemy_iam_user_repository_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi repository untuk IAM (Identity Access Management)
               menggunakan SQLAlchemy ORM.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from passlib.hash import bcrypt
from sqlalchemy import and_, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

# Domain
from domain.iam.aggregate_root import UserAggregate
from domain.iam.permission_vo import Permission
from domain.iam.role_entity import Role
from domain.iam.session_entity import UserSession
from domain.iam.user_entity import UserStatus

# Infrastructure ORM (semua model IAM dari satu file terpusat)
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

        email = (
            self._encryption.decrypt(table.email_encrypted)
            if table.email_encrypted
            else table.email
        )
        phone = (
            self._encryption.decrypt(table.phone_encrypted)
            if table.phone_encrypted
            else table.phone
        )

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
        status_str = (
            aggregate.status.value if hasattr(aggregate.status, "value") else str(aggregate.status)
        )
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

    # ========================================================================
    # USER CRUD METHODS
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
            logger.info("User successfully added: %s (id=%s)", user.username, user.id)

        except (DuplicateUsernameError, DuplicateEmailError):
            raise
        except IntegrityError as e:
            err_msg = str(e).lower()
            if "username" in err_msg:
                raise DuplicateUsernameError(f"Username already exists: {e}") from e
            if "email" in err_msg:
                raise DuplicateEmailError(f"Email already exists: {e}") from e
            raise IAMRepositoryError(f"Database integrity violation: {e}") from e
        except Exception as e:
            logger.error("Failed to add user: %s", type(e).__name__)
            raise IAMRepositoryError(f"Failed to add user: {e}") from e

    async def get_by_id(self, user_id: UUID) -> UserAggregate | None:
        try:
            stmt = select(IAMUserTable).where(
                IAMUserTable.id == user_id, IAMUserTable.deleted_at.is_(None)
            )
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            if not table:
                return None
            return self._to_domain(table)
        except Exception as e:
            logger.error("Failed to get user by id %s: %s", user_id, type(e).__name__)
            raise IAMRepositoryError(f"Failed to get user: {e}") from e

    async def get_by_username(self, username: str) -> UserAggregate | None:
        try:
            stmt = select(IAMUserTable).where(
                IAMUserTable.username == username, IAMUserTable.deleted_at.is_(None)
            )
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            if not table:
                return None
            return self._to_domain(table)
        except Exception as e:
            logger.error("Failed to get user by username %s: %s", username, type(e).__name__)
            raise IAMRepositoryError(f"Failed to get user: {e}") from e

    async def get_by_email(self, email: str) -> UserAggregate | None:
        try:
            stmt = select(IAMUserTable).where(
                IAMUserTable.email == email, IAMUserTable.deleted_at.is_(None)
            )
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            if not table:
                return None
            return self._to_domain(table)
        except Exception as e:
            logger.error("Failed to get user by email %s: %s", email, type(e).__name__)
            raise IAMRepositoryError(f"Failed to get user: {e}") from e

    async def update(self, user: UserAggregate) -> None:
        try:
            stmt = select(IAMUserTable.version).where(IAMUserTable.id == user.id)
            result = await self.session.execute(stmt)
            current_version = result.scalar_one_or_none()
            if current_version is None:
                raise UserNotFoundError(f"User {user.id} not found")
            if current_version != user.version:
                raise OptimisticLockError(
                    f"Version mismatch: expected {user.version}, got {current_version}"
                )

            table = await self._to_orm(user)
            table.version = user.version + 1
            table.updated_at = datetime.utcnow()

            await self.session.merge(table)
            await self.session.flush()
            logger.info("User updated: %s", user.id)

        except OptimisticLockError:
            raise
        except Exception as e:
            await self.session.rollback()
            logger.error("Failed to update user %s: %s", user.id, type(e).__name__)
            raise IAMRepositoryError(f"Failed to update user: {e}") from e

    async def delete(self, user_id: UUID) -> bool:
        try:
            stmt = (
                update(IAMUserTable)
                .where(IAMUserTable.id == user_id)
                .values(deleted_at=datetime.utcnow(), is_active=False, status="inactive")
            )
            result = await self.session.execute(stmt)
            await self.session.flush()
            deleted = result.rowcount > 0
            if deleted:
                logger.info("User %s soft deleted", user_id)
            return deleted
        except Exception as e:
            await self.session.rollback()
            logger.error("Failed to delete user %s: %s", user_id, type(e).__name__)
            raise IAMRepositoryError(f"Failed to delete user: {e}") from e

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

            stmt = (
                update(IAMUserTable)
                .where(IAMUserTable.id == user.id)
                .values(
                    failed_login_count=new_failed_count,
                    locked_until=locked_until,
                    status="locked" if locked_until else user.status,
                )
            )
            await self.session.execute(stmt)
            await self.session.flush()
            return None

        stmt = (
            update(IAMUserTable)
            .where(IAMUserTable.id == user.id)
            .values(
                failed_login_count=0,
                locked_until=None,
                last_login_at=datetime.utcnow(),
                status="active" if user.status == UserStatus.LOCKED.value else user.status,
            )
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
            stmt = (
                update(IAMUserTable)
                .where(IAMUserTable.id == user_id)
                .values(
                    password_hash=hashed,
                    password_changed_at=datetime.utcnow(),
                    must_change_password=False,
                    updated_at=datetime.utcnow(),
                    updated_by=changed_by,
                )
            )
            result = await self.session.execute(stmt)
            await self.session.flush()
            logger.info("Credentials changed for user %s", user_id)
            return result.rowcount > 0
        except Exception as e:
            await self.session.rollback()
            logger.error("Failed to update credentials for user %s: %s", user_id, type(e).__name__)
            raise IAMRepositoryError(f"Failed to change password: {e}") from e

    async def exists_by_username(self, username: str) -> bool:
        try:
            stmt = (
                select(func.count())
                .select_from(IAMUserTable)
                .where(IAMUserTable.username == username, IAMUserTable.deleted_at.is_(None))
            )
            result = await self.session.execute(stmt)
            return result.scalar() > 0
        except Exception as e:
            logger.error("Failed to check username %s: %s", username, type(e).__name__)
            raise IAMRepositoryError(f"Failed to check username: {e}") from e

    async def exists_by_email(self, email: str) -> bool:
        try:
            stmt = (
                select(func.count())
                .select_from(IAMUserTable)
                .where(IAMUserTable.email == email, IAMUserTable.deleted_at.is_(None))
            )
            result = await self.session.execute(stmt)
            return result.scalar() > 0
        except Exception as e:
            logger.error("Failed to check email %s: %s", email, type(e).__name__)
            raise IAMRepositoryError(f"Failed to check email: {e}") from e

    # ========================================================================
    # ROLE METHODS
    # ========================================================================

    async def create_role(
        self,
        name: str,
        description: str | None = None,
        is_system_role: bool = False,
        created_by: UUID | None = None,
    ) -> Role:
        try:
            stmt = (
                select(func.count())
                .select_from(IAMRoleTable)
                .where(IAMRoleTable.name == name, IAMRoleTable.deleted_at.is_(None))
            )
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
            logger.error("Failed to create role: %s", type(e).__name__)
            raise IAMRepositoryError(f"Failed to create role: {e}") from e

    async def get_role_by_id(self, role_id: UUID) -> Role | None:
        try:
            stmt = select(IAMRoleTable).where(
                IAMRoleTable.id == role_id, IAMRoleTable.deleted_at.is_(None)
            )
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            if not table:
                return None
            return self._to_domain_role(table)
        except Exception as e:
            logger.error("Failed to get role by id %s: %s", role_id, type(e).__name__)
            raise IAMRepositoryError(f"Failed to get role: {e}") from e

    async def get_all_roles(self, is_active: bool | None = True) -> list[Role]:
        try:
            conditions = [IAMRoleTable.deleted_at.is_(None)]
            if is_active is not None:
                conditions.append(IAMRoleTable.is_active == is_active)
            stmt = select(IAMRoleTable).where(and_(*conditions)).order_by(IAMRoleTable.name)
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain_role(table) for table in tables]
        except Exception as e:
            logger.error("Failed to get all roles: %s", type(e).__name__)
            raise IAMRepositoryError(f"Failed to get roles: {e}") from e

    async def assign_role_to_user(self, user_id: UUID, role_id: UUID, assigned_by: UUID) -> None:
        try:
            stmt = (
                select(func.count())
                .select_from(iam_user_role)
                .where(
                    iam_user_role.c.user_id == user_id,
                    iam_user_role.c.role_id == role_id,
                )
            )
            result = await self.session.execute(stmt)
            if result.scalar() > 0:
                logger.warning("Role %s already assigned to user %s", role_id, user_id)
                return

            stmt_insert = iam_user_role.insert().values(
                user_id=user_id,
                role_id=role_id,
                assigned_at=datetime.utcnow(),
                assigned_by=assigned_by,
            )
            await self.session.execute(stmt_insert)
            await self.session.flush()
            logger.info("Role assigned to user")
        except Exception as e:
            await self.session.rollback()
            logger.error("Failed to assign role: %s", type(e).__name__)
            raise IAMRepositoryError(f"Failed to assign role: {e}") from e

    async def get_user_roles(self, user_id: UUID) -> list[Role]:
        try:
            stmt = (
                select(IAMRoleTable)
                .join(iam_user_role, IAMRoleTable.id == iam_user_role.c.role_id)
                .where(
                    iam_user_role.c.user_id == user_id,
                    IAMRoleTable.deleted_at.is_(None),
                )
            )
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain_role(table) for table in tables]
        except Exception as e:
            logger.error("Failed to get user roles for %s: %s", user_id, type(e).__name__)
            raise IAMRepositoryError(f"Failed to get user roles: {e}") from e

    # ========================================================================
    # PERMISSION METHODS
    # ========================================================================

    async def create_permission(
        self, name: str, resource: str, action: str, description: str | None = None
    ) -> Permission:
        try:
            table = IAMPermissionTable(
                id=uuid4(),
                name=name,
                resource=resource,
                action=action,
                description=description,
                created_at=datetime.utcnow(),
            )
            self.session.add(table)
            await self.session.flush()
            logger.info("Permission created: %s", name)
            return self._to_domain_permission(table)
        except Exception as e:
            await self.session.rollback()
            logger.error("Failed to create permission: %s", type(e).__name__)
            raise IAMRepositoryError(f"Failed to create permission: {e}") from e

    async def assign_permission_to_role(self, role_id: UUID, permission_id: UUID) -> None:
        try:
            stmt_insert = iam_role_permission.insert().values(
                role_id=role_id, permission_id=permission_id, assigned_at=datetime.utcnow()
            )
            await self.session.execute(stmt_insert)
            await self.session.flush()
            logger.info("Permission %s assigned to role %s", permission_id, role_id)
        except Exception as e:
            await self.session.rollback()
            logger.error("Failed to assign permission: %s", type(e).__name__)
            raise IAMRepositoryError(f"Failed to assign permission: {e}") from e

    async def get_role_permissions(self, role_id: UUID) -> list[Permission]:
        try:
            stmt = (
                select(IAMPermissionTable)
                .join(
                    iam_role_permission,
                    IAMPermissionTable.id == iam_role_permission.c.permission_id,
                )
                .where(iam_role_permission.c.role_id == role_id)
            )
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain_permission(table) for table in tables]
        except Exception as e:
            logger.error("Failed to get role permissions for %s: %s", role_id, type(e).__name__)
            raise IAMRepositoryError(f"Failed to get permissions: {e}") from e

    # ========================================================================
    # SESSION METHODS
    # ========================================================================

    async def create_session(
        self,
        user_id: UUID,
        ip_address: str,
        user_agent: str,
        session_timeout_hours: int = DEFAULT_SESSION_TIMEOUT_HOURS,
    ) -> UserSession:
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
            logger.error("Failed to create session: %s", type(e).__name__)
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
            logger.error("Failed to validate session: %s", type(e).__name__)
            raise IAMRepositoryError(f"Failed to validate session: {e}") from e

    async def invalidate_session(self, session_id: UUID) -> None:
        try:
            stmt = (
                update(IAMSessionTable)
                .where(IAMSessionTable.id == session_id)
                .values(is_active=False)
            )
            await self.session.execute(stmt)
            await self.session.flush()
            logger.info("Session %s invalidated", session_id)
        except Exception as e:
            await self.session.rollback()
            logger.error("Failed to invalidate session: %s", type(e).__name__)
            raise IAMRepositoryError(f"Failed to invalidate session: {e}") from e

    async def invalidate_all_user_sessions(self, user_id: UUID) -> int:
        try:
            stmt = (
                update(IAMSessionTable)
                .where(IAMSessionTable.user_id == user_id)
                .values(is_active=False)
            )
            result = await self.session.execute(stmt)
            await self.session.flush()
            count = result.rowcount
            logger.info("Invalidated %d sessions for user %s", count, user_id)
            return count
        except Exception as e:
            await self.session.rollback()
            logger.error("Failed to invalidate user sessions: %s", type(e).__name__)
            raise IAMRepositoryError(f"Failed to invalidate sessions: {e}") from e

    # ========================================================================
    # LOGIN ATTEMPT METHODS
    # ========================================================================

    async def record_login_attempt(self, username: str, success: bool, ip_address: str) -> None:
        try:
            table = LoginAttemptTable(
                id=uuid4(),
                username=username,
                success=success,
                ip_address=ip_address,
                attempted_at=datetime.utcnow(),
            )
            self.session.add(table)
            await self.session.flush()
            logger.debug("Login attempt recorded for %s: success=%s", username, success)
        except Exception as e:
            await self.session.rollback()
            logger.error("Failed to record login attempt: %s", type(e).__name__)
            raise IAMRepositoryError(f"Failed to record login attempt: {e}") from e

    async def get_recent_failed_attempts(self, username: str, minutes: int = 30) -> int:
        try:
            cutoff = datetime.utcnow() - timedelta(minutes=minutes)
            stmt = (
                select(func.count())
                .select_from(LoginAttemptTable)
                .where(
                    LoginAttemptTable.username == username,
                    LoginAttemptTable.success == False,
                    LoginAttemptTable.attempted_at >= cutoff,
                )
            )
            result = await self.session.execute(stmt)
            return result.scalar() or 0
        except Exception as e:
            logger.error("Failed to get recent failed attempts: %s", type(e).__name__)
            raise IAMRepositoryError(f"Failed to get failed attempts: {e}") from e


    async def save(self, user: UserAggregate) -> None:
        """P55: save user (add jika baru, update jika sudah ada)."""
        existing = await self.get_by_id(user.id)
        if existing:
            await self.update(user)
        else:
            await self.add(user)

    async def find_by_username(self, username: str) -> UserAggregate | None:
        """P55: cari user berdasarkan username."""
        return await self.get_by_username(username)
    
    async def find_by_id(self, user_id: UUID) -> UserAggregate | None:
        """P55: Find user by ID without legal_entity filter."""
        return await self.get_by_id(user_id)
        
    
# ============================================================================
# ALIAS UNTUK KOMPATIBILITAS DENGAN ADAPTER REGISTRY
# ============================================================================

# Adapter registry mengimport 'SQLAlchemyIAMUserRepositoryImpl'
SQLAlchemyIAMUserRepositoryImpl = SQLAlchemyIAMUserRepository

# ============================================================================
# EXPORTS
# ============================================================================

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