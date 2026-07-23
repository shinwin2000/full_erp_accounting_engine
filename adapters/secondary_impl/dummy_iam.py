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
        from domain.iam.user_entity import UserProfile, UserAudit
        admin_profile = UserProfile(
            full_name="Administrator",
            email="admin@example.com",
        )
        admin_audit = UserAudit(
            created_at=datetime.now(UTC),
            created_by="system",
            updated_at=datetime.now(UTC),
            updated_by="system",
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
            audit=admin_audit,
        )
        self.users[admin_user.user_id] = admin_user
        logger.info("DummyIAMState initialized with admin user (admin/Admin123!)")

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