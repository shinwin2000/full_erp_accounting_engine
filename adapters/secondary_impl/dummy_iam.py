from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import uuid4

from domain.iam.password_hashed_vo import PasswordHashedVO
from domain.iam.user_entity import UserEntity, UserStatus

logger = logging.getLogger("erp_engine")


class DummyIAMState:
    """Dummy IAM state untuk fallback ketika repository tidak menyediakan method get()."""

    def __init__(self):
        self.users = {}
        self.roles = {}
        admin_password = PasswordHashedVO.create_from_plain("Admin123!")
        from domain.iam.user_entity import UserAudit, UserProfile
        admin_profile = UserProfile(
            full_name="Administrator",
            email="admin@example.com",
            phone="+62-812-3456-7890",
            mobile=None,
            department="IT",
            position="System Administrator",
            avatar_url=None,
            timezone="Asia/Jakarta",
            language="id",
            metadata={},
        )
        admin_audit = UserAudit(
            last_login_at=None,
            last_login_ip=None,
            last_password_change_at=datetime.now(UTC),
            last_password_change_by="system",
            created_at=datetime.now(UTC),
            created_by="system",
            updated_at=datetime.now(UTC),
            updated_by="system",
            deleted_at=None,
            deleted_by=None,
            version=1,
        )
        admin_user = UserEntity(
            user_id=uuid4(),
            username="admin",
            email="admin@example.com",
            password_hash=admin_password,
            status=UserStatus.ACTIVE,
            profile=admin_profile,
            legal_entity_id=uuid4(),
            role_ids=[],
            failed_login_attempts=0,
            locked_until=None,
            mfa_enabled=False,
            mfa_secret=None,
            audit=admin_audit,
        )
        # Tambahkan property wrapper untuk kompatibilitas dengan schema
        self._wrap_user_for_schema(admin_user)
        self.users[admin_user.user_id] = admin_user
        logger.info("DummyIAMState initialized with admin user (admin/Admin123!)")

    def _wrap_user_for_schema(self, user: UserEntity) -> None:
        """Menambahkan property wrapper untuk kompatibilitas dengan UserResponseSchema."""
        # Property id (alias untuk user_id)
        if not hasattr(user, 'id'):
            object.__setattr__(user, 'id', user.user_id)

        # Property department (alias untuk profile.department)
        if not hasattr(user, 'department'):
            object.__setattr__(user, 'department', user.profile.department)

        # Property job_title (alias untuk profile.position)
        if not hasattr(user, 'job_title'):
            object.__setattr__(user, 'job_title', user.profile.position)

        # Property phone_number (alias untuk profile.phone)
        if not hasattr(user, 'phone_number'):
            object.__setattr__(user, 'phone_number', user.profile.phone)

        # Property full_name (alias untuk profile.full_name)
        if not hasattr(user, 'full_name'):
            object.__setattr__(user, 'full_name', user.profile.full_name)

        # Property is_active (call method)
        if not hasattr(user, 'is_active_property'):
            object.__setattr__(user, 'is_active_property', user.is_active())

        # Property is_locked (call method)
        if not hasattr(user, 'is_locked_property'):
            object.__setattr__(user, 'is_locked_property', user.is_locked())

        # Property is_superuser (default False untuk dummy)
        if not hasattr(user, 'is_superuser'):
            object.__setattr__(user, 'is_superuser', False)

        # Property must_change_password (default False untuk dummy)
        if not hasattr(user, 'must_change_password'):
            object.__setattr__(user, 'must_change_password', False)

        # Property last_login_at (dari audit)
        if not hasattr(user, 'last_login_at'):
            object.__setattr__(user, 'last_login_at', user.audit.last_login_at)

        # Property last_password_change (dari audit)
        if not hasattr(user, 'last_password_change'):
            object.__setattr__(user, 'last_password_change', user.audit.last_password_change_at)

        # Property legal_entity_ids (list dari single legal_entity_id)
        if not hasattr(user, 'legal_entity_ids'):
            object.__setattr__(user, 'legal_entity_ids', [user.legal_entity_id] if user.legal_entity_id else [])

        # Property notes (default None)
        if not hasattr(user, 'notes'):
            object.__setattr__(user, 'notes', None)

        # Property created_by_name (default None)
        if not hasattr(user, 'created_by_name'):
            object.__setattr__(user, 'created_by_name', None)

        # Override is_active dan is_locked menjadi property values
        object.__setattr__(user, 'is_active', user.is_active())
        object.__setattr__(user, 'is_locked', user.is_locked())

    def authenticate(self, username: str, password: str):
        for user in self.users.values():
            if user.username == username:
                if user.password_hash.verify(password):
                    return user
                return None
        return None

    def get_user_permissions(self, user_id):
        return set()

    def add_user(self, user):
        self.users[user.user_id] = user

    def update_user(self, user):
        self.users[user.user_id] = user

    def remove_user(self, user_id):
        self.users.pop(user_id, None)

    def add_role(self, role):
        self.roles[role.role_id] = role

    def update_role(self, role):
        self.roles[role.role_id] = role

    def remove_role(self, role_id):
        self.roles.pop(role_id, None)

    def assign_role_to_user(self, user_id, role_id):
        if user_id in self.users:
            if role_id not in self.users[user_id].role_ids:
                self.users[user_id].role_ids.append(role_id)

    def remove_role_from_user(self, user_id, role_id):
        if user_id in self.users:
            if role_id in self.users[user_id].role_ids:
                self.users[user_id].role_ids.remove(role_id)

    def has_permission(self, user_id, permission):
        return False


class IAMRepositoryAdapter:
    """Wrapper untuk repository yang tidak memiliki method get()."""

    def __init__(self, repo):
        self._repo = repo
        self._get_method = None
        for method_name in ['get_iam', 'load', 'get_state', 'get']:
            if hasattr(repo, method_name):
                self._get_method = getattr(repo, method_name)
                logger.info(f"Using repository method '{method_name}' for get()")
                break
        if self._get_method is None:
            logger.warning("Repository does not have any known get method. Using dummy IAM state.")
            self._get_method = self._dummy_get
            self._dummy_state = DummyIAMState()

    async def _dummy_get(self):
        return self._dummy_state

    async def get(self):
        return await self._get_method()

    async def save(self, iam):
        if hasattr(self._repo, 'save'):
            return await self._repo.save(iam)
        logger.warning("Repository has no save method; skipping save")
        return None

    def __getattr__(self, name):
        return getattr(self._repo, name)