#!/usr/bin/env python3
"""
Module: sqlalchemy_iam_user_repository_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi repository untuk IAM (Identity Access Management)
               menggunakan SQLAlchemy ORM. Menyediakan operasi CRUD untuk user,
               role, permission, session management, login attempts, dan
               password management. Mendukung hashing password dengan bcrypt,
               optimistic locking, soft delete, dan audit trail.
Dependencies:
- sqlalchemy.ext.asyncio (AsyncSession)
- sqlalchemy import select, update, func, and_, or_
- passlib.hash (bcrypt) untuk password hashing
- ports.primary.iam_user_repository_port (IAMUserRepositoryPort)
- domain.iam.aggregate_root (UserAggregate, Role, Permission)
- infrastructure.persistence_orm.iam_user_table (semua model IAM terpusat di sini)
Audit: Setiap perubahan user (create, update, delete), login attempt,
       dan permission assignment dicatat di event store.
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
    iam_role_permission_table,
    iam_user_role_table,
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
    """Base exception untuk repository IAM."""

    pass


class DuplicateUsernameError(IAMRepositoryError):
    """Username sudah ada."""

    pass


class DuplicateEmailError(IAMRepositoryError):
    """Email sudah terdaftar."""

    pass


class UserNotFoundError(IAMRepositoryError):
    """User tidak ditemukan."""

    pass


class RoleNotFoundError(IAMRepositoryError):
    """Role tidak ditemukan."""

    pass


class PermissionNotFoundError(IAMRepositoryError):
    """Permission tidak ditemukan."""

    pass


class InvalidCredentialsError(IAMRepositoryError):
    """Username/password salah."""

    pass


class AccountLockedError(IAMRepositoryError):
    """Akun terkunci karena terlalu banyak percobaan login gagal."""

    pass


class SessionNotFoundError(IAMRepositoryError):
    """Session tidak ditemukan atau sudah expired."""

    pass


class OptimisticLockError(IAMRepositoryError):
    """Version mismatch saat update."""

    pass


# ============================================================================
# PASSWORD HELPER
# ============================================================================


class PasswordHelper:
    """Helper untuk hashing dan verifikasi password."""

    @staticmethod
    def hash_password(plain_password: str) -> str:
        """Hash password menggunakan bcrypt."""
        return bcrypt.using(rounds=BCRYPT_ROUNDS).hash(plain_password)

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """Verifikasi password dengan hash yang tersimpan."""
        try:
            return bcrypt.verify(plain_password, hashed_password)
        except Exception:
            return False

    @staticmethod
    def needs_rehash(hashed_password: str) -> bool:
        """Check apakah hash perlu di-rehash (upgrade security)."""
        return bcrypt.using(rounds=BCRYPT_ROUNDS).needs_update(hashed_password)


# ============================================================================
# REPOSITORY IMPLEMENTATION
# ============================================================================


class SQLAlchemyIAMUserRepository(IAMUserRepositoryPort):
    """
    Implementasi repository IAM User dengan SQLAlchemy.
    """

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
        """
        Mapping dari ORM model ke domain UserAggregate.
        """
        # Map status
        status_map = {
            "active": UserStatus.ACTIVE,
            "inactive": UserStatus.INACTIVE,
            "locked": UserStatus.LOCKED,
            "suspended": UserStatus.SUSPENDED,
            "pending_activation": UserStatus.PENDING_ACTIVATION,
        }
        status = status_map.get(table.status, UserStatus.ACTIVE)

        # Decrypt sensitive fields
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

        aggregate = UserAggregate(
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
        return aggregate

    async def _to_orm(self, aggregate: UserAggregate) -> IAMUserTable:
        """Mapping dari domain ke ORM model."""
        status_str = (
            aggregate.status.value if hasattr(aggregate.status, "value") else str(aggregate.status)
        )

        # Encrypt sensitive fields
        email_encrypted = self._encryption.encrypt(aggregate.email) if aggregate.email else None
        phone_encrypted = self._encryption.encrypt(aggregate.phone) if aggregate.phone else None

        table = IAMUserTable(
            id=aggregate.id,
            username=aggregate.username,
            email=aggregate.email,  # plain for search, but also store encrypted
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
        return table

    def _to_domain_role(self, table: IAMRoleTable) -> Role:
        """Mapping ORM role ke domain."""
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
        """Mapping ORM permission ke domain."""
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
        """
        Menambahkan user baru ke dalam sistem.
        Mendukung pola Unit of Work (UoW) dengan mendelegasikan rollback
        ke transaction manager terpusat guna menjaga konsistensi state.
        """
        try:
            # 1. Validasi proaktif: Cek duplikasi username
            exists_username = await self.exists_by_username(user.username)
            if exists_username:
                raise DuplicateUsernameError(
                    f"Username '{user.username}' already exists"
                )

            # 2. Validasi proaktif: Cek duplikasi email
            if user.email:
                exists_email = await self.exists_by_email(user.email)
                if exists_email:
                    raise DuplicateEmailError(
                        f"Email '{user.email}' already registered"
                    )

            # 3. Pengamanan Kriptografi: Hash password jika masih berupa plain text
            if user.hashed_password and not user.hashed_password.startswith("$2b$"):
                user.hashed_password = PasswordHelper.hash_password(user.hashed_password)

            # 4. Pemetaan ke ORM & Registrasi ke Database Session Context
            table = await self._to_orm(user)
            self.session.add(table)

            # Flush untuk mendapatkan ID/memicu constraint validation tanpa commit prematur
            await self.session.flush()
            # FIX: Hindari kata "password" di log
            logger.info(
                "User successfully staged/added: %s (id=%s)",
                user.username,
                user.id
            )

        except (DuplicateUsernameError, DuplicateEmailError):
            # Biarkan custom domain exception naik ke application layer tanpa diubah
            raise

        except IntegrityError as e:
            # PENTING: Jangan lakukan self.session.rollback() manual di sini jika menggunakan UoW.
            # UoW manager di application layer yang berkewajiban melakukan rollback secara utuh.
            err_msg = str(e).lower()
            if "username" in err_msg:
                raise DuplicateUsernameError(f"Username already exists: {e}") from e
            if "email" in err_msg:
                raise DuplicateEmailError(f"Email already exists: {e}") from e
            raise IAMRepositoryError(f"Database integrity violation: {e}") from e

        except Exception as e:
            # Tangkap kegagalan sistem/infrastruktur lainnya
            logger.error("Failed to add user aggregate to infrastructure: %s", type(e).__name__)
            raise IAMRepositoryError(
                f"Failed to add user due to internal repository error: {e}"
            ) from e

    async def get_by_id(self, user_id: UUID) -> UserAggregate | None:
        """Mengambil user berdasarkan ID."""
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
        """Mengambil user berdasarkan username."""
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
        """Mengambil user berdasarkan email."""
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
        """Memperbarui user."""
        try:
            # Get current version
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
            # FIX: Hindari kata "password" di log
            logger.info("User updated: %s", user.id)

        except OptimisticLockError:
            raise
        except Exception as e:
            await self.session.rollback()
            logger.error("Failed to update user %s: %s", user.id, type(e).__name__)
            raise IAMRepositoryError(f"Failed to update user: {e}") from e

    async def delete(self, user_id: UUID) -> bool:
        """Soft delete user."""
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
        """
        Autentikasi user dengan username dan password.
        Mencatat percobaan login (sukses/gagal) dan lock account jika perlu.
        """
        user = await self.get_by_username(username)
        if not user:
            return None

        # Check if account is locked
        if user.locked_until and user.locked_until > datetime.utcnow():
            raise AccountLockedError(f"Account locked until {user.locked_until}")

        # Verify password
        if not PasswordHelper.verify_password(plain_password, user.hashed_password):
            # Increment failed login count
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

        # Reset failed login count on successful login
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

        # Update user object
        user.failed_login_count = 0
        user.locked_until = None
        user.last_login_at = datetime.utcnow()

        return user

    async def change_password(self, user_id: UUID, new_password: str, changed_by: UUID) -> bool:
        """Mengubah password user."""
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
            # FIX: Hindari kata "password" di log
            logger.info("Credentials changed for user %s", user_id)
            return result.rowcount > 0

        except Exception as e:
            await self.session.rollback()
            # FIX: Hindari kata "password" di log dan gunakan type(e).__name__
            logger.error("Failed to update credentials for user %s: %s", user_id, type(e).__name__)
            raise IAMRepositoryError(f"Failed to change password: {e}") from e

    async def exists_by_username(self, username: str) -> bool:
        """Check apakah username sudah ada."""
        try:
            stmt = (
                select(func.count())
                .select_from(IAMUserTable)
                .where(IAMUserTable.username == username, IAMUserTable.deleted_at.is_(None))
            )
            result = await self.session.execute(stmt)
            count = result.scalar()
            return count > 0

        except Exception as e:
            logger.error("Failed to check username %s: %s", username, type(e).__name__)
            raise IAMRepositoryError(f"Failed to check username: {e}") from e

    async def exists_by_email(self, email: str) -> bool:
        """Check apakah email sudah terdaftar."""
        try:
            stmt = (
                select(func.count())
                .select_from(IAMUserTable)
                .where(IAMUserTable.email == email, IAMUserTable.deleted_at.is_(None))
            )
            result = await self.session.execute(stmt)
            count = result.scalar()
            return count > 0

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
        """Membuat role baru."""
        try:
            # Check duplicate name
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
        """Mendapatkan role berdasarkan ID."""
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
        """Mendapatkan semua role."""
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
        """Assign role ke user."""
        try:
            # Check if already assigned
            stmt = (
                select(func.count())
                .select_from(iam_user_role_table)
                .where(
                    iam_user_role_table.c.user_id == user_id,
                    iam_user_role_table.c.role_id == role_id,
                )
            )
            result = await self.session.execute(stmt)
            if result.scalar() > 0:
                logger.warning("Role %s already assigned to user %s", role_id, user_id)
                return

            # Insert using the Table object directly
            stmt_insert = iam_user_role_table.insert().values(
                user_id=user_id,
                role_id=role_id,
                assigned_at=datetime.utcnow(),
                assigned_by=assigned_by,
            )
            await self.session.execute(stmt_insert)
            await self.session.flush()
            # FIX: Jangan log role_id dan user_id yang mungkin sensitif
            logger.info("Role assigned to user")

        except Exception as e:
            await self.session.rollback()
            logger.error("Failed to assign role: %s", type(e).__name__)
            raise IAMRepositoryError(f"Failed to assign role: {e}") from e

    async def get_user_roles(self, user_id: UUID) -> list[Role]:
        """Mendapatkan semua role yang dimiliki user."""
        try:
            stmt = (
                select(IAMRoleTable)
                .join(iam_user_role_table, IAMRoleTable.id == iam_user_role_table.c.role_id)
                .where(
                    iam_user_role_table.c.user_id == user_id,
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
        """Membuat permission baru."""
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
        """Assign permission ke role."""
        try:
            # Insert using the Table object directly
            stmt_insert = iam_role_permission_table.insert().values(
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
        """Mendapatkan semua permission dari role."""
        try:
            stmt = (
                select(IAMPermissionTable)
                .join(
                    iam_role_permission_table,
                    IAMPermissionTable.id == iam_role_permission_table.c.permission_id,
                )
                .where(iam_role_permission_table.c.role_id == role_id)
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
        """Membuat session baru untuk user."""
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
        """Validasi session token."""
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
        """Invalidate session (logout)."""
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
        """Invalidate semua session user (logout dari semua device)."""
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
        """Mencatat percobaan login."""
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
        """Mendapatkan jumlah percobaan login gagal dalam rentang waktu."""
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
    "SessionNotFoundError",
    "UserNotFoundError",
]
