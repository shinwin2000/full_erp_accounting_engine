#!/usr/bin/env python3
"""
Module: password_policy_enforcer.py
Layer: Security Hardening

Responsibility:
    Penegak kebijakan password: panjang, kompleksitas, history, expiry, lockout,
    dan notifikasi. Menggunakan hashing aman (bcrypt/argon2), rate limiting,
    dan integrasi dengan user database.

Metode yang ditambahkan:
- Untuk PasswordPolicy: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk PasswordHasher: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk PasswordPolicyEnforcer: semua entity dasar, get_statistics, reset.
- Untuk InMemoryUserStorage: entity dasar untuk kompatibilitas.
"""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

# Optional bcrypt
try:
    import bcrypt

    HAS_BCRYPT = True
except ImportError:
    HAS_BCRYPT = False
    try:
        from passlib.hash import bcrypt as bcrypt_alt

        HAS_BCRYPT = True
        bcrypt = bcrypt_alt
    except ImportError:
        HAS_BCRYPT = False

logger = logging.getLogger(__name__)


# ============================================================================
# Exceptions
# ============================================================================
class PasswordPolicyError(Exception):
    pass


class WeakPasswordError(PasswordPolicyError):
    pass


class PasswordExpiredError(PasswordPolicyError):
    pass


class AccountLockedError(PasswordPolicyError):
    pass


# ============================================================================
# Data Classes
# ============================================================================
@dataclass(kw_only=True)
class PasswordPolicy:
    min_length: int = 12
    require_uppercase: bool = True
    require_lowercase: bool = True
    require_digits: bool = True
    require_special: bool = True
    max_age_days: int = 90
    password_history_count: int = 10
    max_login_attempts: int = 5
    lockout_duration_minutes: int = 30
    min_password_age_days: int = 1
    prevent_common_passwords: bool = True
    prevent_username_containment: bool = True

    # Fields untuk entity dasar
    _version: int = field(default=1, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self):
        self._take_snapshot()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "min_length": self.min_length,
                "max_age_days": self.max_age_days,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if self.min_length < 1:
            errors.append("min_length must be at least 1")
        if self.max_age_days < 1:
            errors.append("max_age_days must be at least 1")
        if self.password_history_count < 0:
            errors.append("password_history_count cannot be negative")
        if self.max_login_attempts < 1:
            errors.append("max_login_attempts must be at least 1")
        if self.lockout_duration_minutes < 1:
            errors.append("lockout_duration_minutes must be at least 1")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "min_length": self.min_length,
            "require_uppercase": self.require_uppercase,
            "require_lowercase": self.require_lowercase,
            "require_digits": self.require_digits,
            "require_special": self.require_special,
            "max_age_days": self.max_age_days,
            "password_history_count": self.password_history_count,
            "max_login_attempts": self.max_login_attempts,
            "lockout_duration_minutes": self.lockout_duration_minutes,
            "min_password_age_days": self.min_password_age_days,
            "prevent_common_passwords": self.prevent_common_passwords,
            "prevent_username_containment": self.prevent_username_containment,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PasswordPolicy:
        instance = cls(
            min_length=data.get("min_length", 12),
            require_uppercase=data.get("require_uppercase", True),
            require_lowercase=data.get("require_lowercase", True),
            require_digits=data.get("require_digits", True),
            require_special=data.get("require_special", True),
            max_age_days=data.get("max_age_days", 90),
            password_history_count=data.get("password_history_count", 10),
            max_login_attempts=data.get("max_login_attempts", 5),
            lockout_duration_minutes=data.get("lockout_duration_minutes", 30),
            min_password_age_days=data.get("min_password_age_days", 1),
            prevent_common_passwords=data.get("prevent_common_passwords", True),
            prevent_username_containment=data.get("prevent_username_containment", True),
        )
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> PasswordPolicy:
        new = PasswordPolicy(
            min_length=self.min_length,
            require_uppercase=self.require_uppercase,
            require_lowercase=self.require_lowercase,
            require_digits=self.require_digits,
            require_special=self.require_special,
            max_age_days=self.max_age_days,
            password_history_count=self.password_history_count,
            max_login_attempts=self.max_login_attempts,
            lockout_duration_minutes=self.lockout_duration_minutes,
            min_password_age_days=self.min_password_age_days,
            prevent_common_passwords=self.prevent_common_passwords,
            prevent_username_containment=self.prevent_username_containment,
        )
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "min_length": self.min_length,
            "max_age_days": self.max_age_days,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> PasswordPolicy:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# ============================================================================
# Password Hasher (dengan entity dasar)
# ============================================================================
class PasswordHasher:
    """Utility untuk hashing password dengan bcrypt atau fallback."""

    def __init__(self):
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._take_snapshot()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "has_algorithm": "bcrypt" if HAS_BCRYPT else "pbkdf2",
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "details": details,
            }
        )

    @staticmethod
    def hash(password: str, rounds: int = 12) -> str:
        if HAS_BCRYPT:
            salt = bcrypt.gensalt(rounds=rounds)
            return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")
        else:
            salt = secrets.token_hex(16)
            dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000)
            return f"pbkdf2$100000${salt}${dk.hex()}"

    @staticmethod
    def verify(password: str, hashed: str) -> bool:
        if HAS_BCRYPT:
            try:
                return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
            except ValueError:
                return False
        else:
            if not hashed.startswith("pbkdf2$"):
                return False
            parts = hashed.split("$")
            if len(parts) != 4:
                return False
            iterations = int(parts[1])
            salt = parts[2]
            expected = parts[3]
            dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations)
            return dk.hex() == expected

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        return {"is_valid": True, "errors": []}

    def to_dict(self) -> dict[str, Any]:
        return {"algorithm": "bcrypt" if HAS_BCRYPT else "pbkdf2", "version": self._version}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PasswordHasher:
        instance = cls()
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> PasswordHasher:
        new = PasswordHasher()
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "algorithm": "bcrypt" if HAS_BCRYPT else "pbkdf2",
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> PasswordHasher:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# ============================================================================
# Common Password Dictionary
# ============================================================================
COMMON_PASSWORDS = {
    "password",
    "123456",
    "12345678",
    "123456789",
    "qwerty",
    "abc123",
    "admin",
    "welcome",
    "letmein",
    "password123",
    "12345",
    "qwerty123",
    "1q2w3e4r",
    "default",
    "passw0rd",
    "admin123",
    "root",
    "toor",
    "monkey",
    "dragon",
    "master",
    "sunshine",
    "iloveyou",
    "princess",
    "shadow",
    "baseball",
    "football",
    "superman",
    "batman",
    "trustno1",
}


# ============================================================================
# PasswordPolicyEnforcer Core (dengan entity dasar)
# ============================================================================
class PasswordPolicyEnforcer:
    """
    Enforcer kebijakan password sesuai standar keamanan bank.
    """

    def __init__(
        self,
        policy: PasswordPolicy | None = None,
        storage: Any | None = None,
        redis_client: Any | None = None,
    ):
        self.policy = policy or PasswordPolicy()
        self.storage = storage
        self.redis = redis_client
        self._hasher = PasswordHasher()
        self._failed_attempts: dict[str, list[datetime]] = {}
        self._lock = threading.RLock()
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._take_snapshot()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "policy_version": self.policy.version(),
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "details": details,
            }
        )

    # ========================================================================
    # Password Strength Validation
    # ========================================================================
    def validate_password_strength(
        self,
        password: str,
        username: str | None = None,
        user_id: str | None = None,
    ) -> tuple[bool, list[str]]:
        errors = []
        if len(password) < self.policy.min_length:
            errors.append(f"Password must be at least {self.policy.min_length} characters")
        if self.policy.require_uppercase and not re.search(r"[A-Z]", password):
            errors.append("Password must contain at least one uppercase letter")
        if self.policy.require_lowercase and not re.search(r"[a-z]", password):
            errors.append("Password must contain at least one lowercase letter")
        if self.policy.require_digits and not re.search(r"\d", password):
            errors.append("Password must contain at least one digit")
        if self.policy.require_special and not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
            errors.append("Password must contain at least one special character")
        if self.policy.prevent_common_passwords and password.lower() in COMMON_PASSWORDS:
            errors.append("Password is too common")
        if self.policy.prevent_username_containment and username and username.lower() in password.lower():
            errors.append("Password should not contain username")
        return len(errors) == 0, errors

    # ========================================================================
    # Password History Management
    # ========================================================================
    def _is_password_reused(self, user_id: str, new_password: str) -> bool:
        if not self.storage:
            return False
        try:
            history = self.storage.get_password_history(
                user_id, limit=self.policy.password_history_count
            )
            for old_hash in history:
                if self._hasher.verify(new_password, old_hash):
                    return True
        except Exception as e:
            logger.warning("History check failed: %s", type(e).__name__)
        return False

    def _store_password_history(self, user_id: str, password_hash: str) -> None:
        if self.storage:
            try:
                self.storage.add_password_history(
                    user_id, password_hash, self.policy.password_history_count
                )
            except Exception as e:
                logger.warning("History storage failed: %s", type(e).__name__)

    # ========================================================================
    # Password Expiry
    # ========================================================================
    def is_password_expired(self, last_changed_date: datetime) -> bool:
        if not last_changed_date:
            return True
        return datetime.now(UTC) - last_changed_date > timedelta(days=self.policy.max_age_days)

    def get_days_until_expiry(self, last_changed_date: datetime) -> int:
        expiry_date = last_changed_date + timedelta(days=self.policy.max_age_days)
        days_left = (expiry_date - datetime.now(UTC)).days
        return max(0, days_left)

    # ========================================================================
    # Password Change Enforcement
    # ========================================================================
    def enforce_new_password(
        self,
        user_id: str,
        username: str,
        new_password: str,
        current_password_hash: str | None = None,
    ) -> str:
        is_valid, errors = self.validate_password_strength(new_password, username, user_id)
        if not is_valid:
            raise WeakPasswordError(f"Password policy violation: {', '.join(errors)}")
        if self._is_password_reused(user_id, new_password):
            raise WeakPasswordError("Password has been used recently. Choose a new one.")
        hashed = self._hasher.hash(new_password)
        self._store_password_history(user_id, hashed)
        self._record_audit("ENFORCE_NEW_PASSWORD", user_id, {})
        logger.info("Security credential updated for user %s", user_id)
        return hashed

    # ========================================================================
    # Login Attempts & Lockout
    # ========================================================================
    def _get_failed_attempts(self, user_id: str) -> list[datetime]:
        if self.redis:
            key = f"login_failures:{user_id}"
            data = self.redis.lrange(key, 0, -1)
            return [datetime.fromtimestamp(float(t)) for t in data]
        else:
            return self._failed_attempts.get(user_id, [])

    def _add_failed_attempt(self, user_id: str) -> None:
        now = datetime.now(UTC)
        if self.redis:
            key = f"login_failures:{user_id}"
            self.redis.lpush(key, now.timestamp())
            self.redis.expire(key, self.policy.lockout_duration_minutes * 60)
        else:
            with self._lock:
                if user_id not in self._failed_attempts:
                    self._failed_attempts[user_id] = []
                self._failed_attempts[user_id].append(now)
                cutoff = now - timedelta(minutes=self.policy.lockout_duration_minutes)
                self._failed_attempts[user_id] = [
                    t for t in self._failed_attempts[user_id] if t > cutoff
                ]

    def _clear_failed_attempts(self, user_id: str) -> None:
        if self.redis:
            key = f"login_failures:{user_id}"
            self.redis.delete(key)
        else:
            with self._lock:
                self._failed_attempts.pop(user_id, None)

    def is_account_locked(self, user_id: str) -> bool:
        attempts = self._get_failed_attempts(user_id)
        return len(attempts) >= self.policy.max_login_attempts

    def record_failed_attempt(self, user_id: str) -> int:
        self._add_failed_attempt(user_id)
        attempts = self._get_failed_attempts(user_id)
        self._record_audit("RECORD_FAILED_ATTEMPT", user_id, {"attempts": len(attempts)})
        return len(attempts)

    def record_successful_login(self, user_id: str) -> None:
        self._clear_failed_attempts(user_id)
        self._record_audit("RECORD_SUCCESSFUL_LOGIN", user_id, {})

    def get_lockout_remaining_seconds(self, user_id: str) -> int:
        attempts = self._get_failed_attempts(user_id)
        if len(attempts) < self.policy.max_login_attempts:
            return 0
        latest = max(attempts)
        elapsed = (datetime.now(UTC) - latest).total_seconds()
        remaining = max(0, self.policy.lockout_duration_minutes * 60 - elapsed)
        return int(remaining)

    # ========================================================================
    # Pre-login Check
    # ========================================================================
    def pre_login_check(self, user_id: str) -> None:
        if self.is_account_locked(user_id):
            remaining = self.get_lockout_remaining_seconds(user_id)
            raise AccountLockedError(f"Account locked. Try again in {remaining} seconds")

    # ========================================================================
    # Password Expiry Check
    # ========================================================================
    def check_password_expiry(self, last_changed_date: datetime) -> tuple[bool, int]:
        if not last_changed_date:
            return True, 0
        days_left = self.get_days_until_expiry(last_changed_date)
        expired = days_left == 0
        return expired, days_left

    # ========================================================================
    # Admin Functions
    # ========================================================================
    def force_password_change(self, user_id: str) -> None:
        if self.storage:
            self.storage.set_force_password_change(user_id, True)
            self._record_audit("FORCE_PASSWORD_CHANGE", "admin", {"user_id": user_id})

    def unlock_account(self, user_id: str) -> None:
        self._clear_failed_attempts(user_id)
        self._record_audit("UNLOCK_ACCOUNT", "admin", {"user_id": user_id})

    # ========================================================================
    # Reporting & Stats
    # ========================================================================
    def generate_report(self) -> dict:
        return {
            "policy": self.policy.to_dict(),
            "hasher": "bcrypt" if HAS_BCRYPT else "pbkdf2",
            "version": self._version,
        }

    def get_statistics(self) -> dict[str, Any]:
        return self.generate_report()

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        res = self.policy.validate()
        if not res["is_valid"]:
            errors.extend([f"Policy: {e}" for e in res["errors"]])
        res = self._hasher.validate()
        if not res["is_valid"]:
            errors.extend([f"Hasher: {e}" for e in res["errors"]])
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy": self.policy.to_dict(),
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PasswordPolicyEnforcer:
        policy = PasswordPolicy.from_dict(data.get("policy", {}))
        instance = cls(policy=policy)
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> PasswordPolicyEnforcer:
        new = PasswordPolicyEnforcer(
            policy=self.policy.clone(), storage=self.storage, redis_client=self.redis
        )
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "policy_version": self.policy.version(),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> PasswordPolicyEnforcer:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self

    def reset(self) -> None:
        self._failed_attempts.clear()
        self._version = 1
        self._audit_trail = []
        self._snapshots = []
        self._record_audit("RESET", "system", {})


# ============================================================================
# Example User Storage Interface (In-Memory)
# ============================================================================
class InMemoryUserStorage:
    """Simple in-memory storage untuk demo purposes."""

    def __init__(self):
        self.users: dict[str, dict] = {}
        self.password_history: dict[str, list[str]] = {}
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []

    def get_user(self, user_id: str) -> dict | None:
        return self.users.get(user_id)

    def get_password_history(self, user_id: str, limit: int) -> list[str]:
        history = self.password_history.get(user_id, [])
        return history[-limit:]

    def add_password_history(self, user_id: str, password_hash: str, limit: int) -> None:
        if user_id not in self.password_history:
            self.password_history[user_id] = []
        self.password_history[user_id].append(password_hash)
        if len(self.password_history[user_id]) > limit:
            self.password_history[user_id] = self.password_history[user_id][-limit:]

    def set_force_password_change(self, user_id: str, flag: bool) -> None:
        if user_id not in self.users:
            self.users[user_id] = {}
        self.users[user_id]["force_change"] = flag

    # ==================== ENTITY DASAR (minimal) ====================
    def validate(self) -> dict[str, Any]:
        return {"is_valid": True, "errors": []}

    def to_dict(self) -> dict[str, Any]:
        return {"users_count": len(self.users), "history_count": len(self.password_history)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InMemoryUserStorage:
        return cls()

    def clone(self) -> InMemoryUserStorage:
        new = InMemoryUserStorage()
        new.users = self.users.copy()
        new.password_history = self.password_history.copy()
        return new

    def snapshot(self) -> dict[str, Any]:
        return {"users_count": len(self.users), "history_count": len(self.password_history)}

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> InMemoryUserStorage:
        self._version += 1
        return self


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    storage = InMemoryUserStorage()
    enforcer = PasswordPolicyEnforcer(storage=storage)

    pwd = "Weak"
    valid, errors = enforcer.validate_password_strength(pwd)
    print(f"Password '{pwd}': valid={valid}, errors={errors}")

    pwd2 = "Str0ngP@ssw0rd!"
    valid, errors = enforcer.validate_password_strength(pwd2)
    print(f"Password '{pwd2}': valid={valid}")

    user_id = "test_user"
    for i in range(5):
        enforcer.record_failed_attempt(user_id)
        print(f"Attempt {i + 1}: locked={enforcer.is_account_locked(user_id)}")

    remaining = enforcer.get_lockout_remaining_seconds(user_id)
    print(f"Lockout remaining: {remaining} seconds")

    enforcer.record_successful_login(user_id)
    print(f"After successful login, locked={enforcer.is_account_locked(user_id)}")

    hashed = enforcer.enforce_new_password(user_id, "testuser", "NewStr0ngP@ss!")
    print(f"New password hash: {hashed[:30]}...")
