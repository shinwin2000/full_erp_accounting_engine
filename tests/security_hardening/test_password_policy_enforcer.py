# tests/security_hardening/test_password_policy_enforcer.py
"""
Comprehensive tests for security_hardening/password_policy_enforcer.py.

Covers:
- Exceptions: PasswordPolicyError, WeakPasswordError, PasswordExpiredError, AccountLockedError
- PasswordPolicy: all entity methods (validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch)
- PasswordHasher: hash, verify, entity methods
- InMemoryUserStorage: get_user, get_password_history, add_password_history, set_force_password_change, entity methods
- PasswordPolicyEnforcer:
  - validate_password_strength (all rules, common passwords, username containment)
  - is_password_expired, get_days_until_expiry, check_password_expiry
  - _is_password_reused, _store_password_history
  - _get_failed_attempts, _add_failed_attempt, _clear_failed_attempts
  - is_account_locked, record_failed_attempt, record_successful_login, get_lockout_remaining_seconds, pre_login_check
  - enforce_new_password (with history reuse, weak password)
  - force_password_change, unlock_account
  - generate_report, get_statistics
  - entity methods: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch, reset
- Redis integration mocked
- Edge cases: empty history, expired password, lockout, multiple failed attempts
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from security_hardening.password_policy_enforcer import (
    AccountLockedError,
    COMMON_PASSWORDS,
    InMemoryUserStorage,
    PasswordExpiredError,
    PasswordHasher,
    PasswordPolicy,
    PasswordPolicyEnforcer,
    PasswordPolicyError,
    WeakPasswordError,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def policy():
    """Default password policy."""
    return PasswordPolicy(
        min_length=8,
        require_uppercase=True,
        require_lowercase=True,
        require_digits=True,
        require_special=True,
        max_age_days=90,
        password_history_count=5,
        max_login_attempts=3,
        lockout_duration_minutes=30,
        min_password_age_days=1,
        prevent_common_passwords=True,
        prevent_username_containment=True,
    )


@pytest.fixture
def storage():
    """InMemoryUserStorage instance."""
    return InMemoryUserStorage()


@pytest.fixture
def mock_redis():
    """Mock Redis client with methods."""
    redis = MagicMock()
    redis.lpush = MagicMock()
    redis.lrange = MagicMock(return_value=[])
    redis.expire = MagicMock()
    redis.delete = MagicMock()
    return redis


@pytest.fixture
def enforcer(policy, storage, mock_redis):
    """PasswordPolicyEnforcer with mocked redis and storage."""
    return PasswordPolicyEnforcer(
        policy=policy,
        storage=storage,
        redis_client=mock_redis,
    )


@pytest.fixture
def strong_password():
    return "Str0ngP@ssw0rd!"


# ============================================================================
# Tests for Exceptions
# ============================================================================

class TestExceptions:
    def test_password_policy_error(self):
        with pytest.raises(PasswordPolicyError):
            raise PasswordPolicyError("test")

    def test_weak_password_error(self):
        with pytest.raises(WeakPasswordError):
            raise WeakPasswordError("test")

    def test_password_expired_error(self):
        with pytest.raises(PasswordExpiredError):
            raise PasswordExpiredError("test")

    def test_account_locked_error(self):
        with pytest.raises(AccountLockedError):
            raise AccountLockedError("test")


# ============================================================================
# Tests for PasswordPolicy
# ============================================================================

class TestPasswordPolicy:
    def test_init_defaults(self):
        policy = PasswordPolicy()
        assert policy.min_length == 12
        assert policy.max_age_days == 90
        assert policy.password_history_count == 10

    def test_validate_valid(self):
        policy = PasswordPolicy()
        result = policy.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_invalid(self):
        policy = PasswordPolicy(min_length=0, max_age_days=0, max_login_attempts=0, lockout_duration_minutes=0)
        result = policy.validate()
        assert result["is_valid"] is False
        assert any("min_length" in e for e in result["errors"])
        assert any("max_age_days" in e for e in result["errors"])
        assert any("max_login_attempts" in e for e in result["errors"])
        assert any("lockout_duration_minutes" in e for e in result["errors"])

    def test_to_dict(self):
        policy = PasswordPolicy(min_length=10)
        d = policy.to_dict()
        assert d["min_length"] == 10
        assert "version" in d

    def test_from_dict(self):
        data = {"min_length": 8, "max_age_days": 60, "version": 3}
        policy = PasswordPolicy.from_dict(data)
        assert policy.min_length == 8
        assert policy.max_age_days == 60
        assert policy._version == 3

    def test_clone(self):
        policy = PasswordPolicy(min_length=15)
        clone = policy.clone()
        assert clone is not policy
        assert clone.min_length == policy.min_length
        assert clone._version == policy._version + 1

    def test_snapshot(self):
        policy = PasswordPolicy()
        snap = policy.snapshot()
        assert snap["version"] == policy._version
        assert snap["min_length"] == policy.min_length
        assert "timestamp" in snap

    def test_version(self):
        policy = PasswordPolicy()
        assert policy.version() == 1

    def test_audit_trail(self):
        policy = PasswordPolicy()
        policy._record_audit("TEST", "user", {})
        trail = policy.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TEST"

    def test_touch(self):
        policy = PasswordPolicy()
        old_version = policy._version
        policy.touch("tester")
        assert policy._version == old_version + 1
        assert policy._audit_trail[-1]["action"] == "TOUCH"


# ============================================================================
# Tests for PasswordHasher
# ============================================================================

class TestPasswordHasher:
    def test_hash_and_verify_bcrypt(self):
        password = "test123"
        hashed = PasswordHasher.hash(password)
        assert PasswordHasher.verify(password, hashed) is True
        assert PasswordHasher.verify("wrong", hashed) is False

    def test_hash_and_verify_pbkdf2_fallback(self, monkeypatch):
        # Force fallback by setting HAS_BCRYPT to False
        import security_hardening.password_policy_enforcer as module
        monkeypatch.setattr(module, "HAS_BCRYPT", False)
        # Reload the class? Actually we just patch the function
        # We'll use the class as is but patch the HAS_BCRYPT in the module
        with patch.object(module, "HAS_BCRYPT", False):
            # Re-import? Not needed; we'll call the static methods
            # They will use the fallback based on the patched value
            hashed = PasswordHasher.hash("fallback")
            # The hash should start with "pbkdf2$"
            assert hashed.startswith("pbkdf2$")
            assert PasswordHasher.verify("fallback", hashed) is True
            assert PasswordHasher.verify("wrong", hashed) is False

    def test_verify_invalid_hash(self):
        assert PasswordHasher.verify("pass", "invalid") is False

    def test_verify_pbkdf2_invalid_format(self, monkeypatch):
        with patch.object(PasswordHasher, "HAS_BCRYPT", False):
            # Hash format: pbkdf2$100000$salt$hash
            assert PasswordHasher.verify("pass", "notpbkdf2") is False
            assert PasswordHasher.verify("pass", "pbkdf2$100000$salt$hash") is False  # hash mismatch

    # Entity methods
    def test_validate(self):
        hasher = PasswordHasher()
        result = hasher.validate()
        assert result["is_valid"] is True

    def test_to_dict(self):
        hasher = PasswordHasher()
        d = hasher.to_dict()
        assert "algorithm" in d
        assert "version" in d

    def test_from_dict(self):
        data = {"version": 5}
        hasher = PasswordHasher.from_dict(data)
        assert hasher._version == 5

    def test_clone(self):
        hasher = PasswordHasher()
        clone = hasher.clone()
        assert clone is not hasher
        assert clone._version == hasher._version + 1

    def test_snapshot(self):
        hasher = PasswordHasher()
        snap = hasher.snapshot()
        assert snap["version"] == hasher._version
        assert "timestamp" in snap

    def test_version(self):
        hasher = PasswordHasher()
        assert hasher.version() == 1

    def test_audit_trail(self):
        hasher = PasswordHasher()
        hasher._record_audit("TEST", "user", {})
        trail = hasher.audit_trail()
        assert len(trail) == 1

    def test_touch(self):
        hasher = PasswordHasher()
        old = hasher._version
        hasher.touch("tester")
        assert hasher._version == old + 1
        assert hasher._audit_trail[-1]["action"] == "TOUCH"


# ============================================================================
# Tests for InMemoryUserStorage
# ============================================================================

class TestInMemoryUserStorage:
    def test_get_user_not_found(self):
        storage = InMemoryUserStorage()
        assert storage.get_user("nonexistent") is None

    def test_get_user_found(self):
        storage = InMemoryUserStorage()
        storage.users["user1"] = {"name": "test"}
        assert storage.get_user("user1") == {"name": "test"}

    def test_get_password_history_empty(self):
        storage = InMemoryUserStorage()
        assert storage.get_password_history("user1", 5) == []

    def test_get_password_history_with_data(self):
        storage = InMemoryUserStorage()
        storage.password_history["user1"] = ["h1", "h2", "h3"]
        assert storage.get_password_history("user1", 2) == ["h2", "h3"]

    def test_add_password_history_new(self):
        storage = InMemoryUserStorage()
        storage.add_password_history("user1", "hash1", 3)
        assert storage.password_history["user1"] == ["hash1"]

    def test_add_password_history_existing(self):
        storage = InMemoryUserStorage()
        storage.password_history["user1"] = ["old"]
        storage.add_password_history("user1", "new", 2)
        assert storage.password_history["user1"] == ["old", "new"]

    def test_add_password_history_limit(self):
        storage = InMemoryUserStorage()
        storage.password_history["user1"] = ["a", "b", "c"]
        storage.add_password_history("user1", "d", 2)
        assert storage.password_history["user1"] == ["c", "d"]

    def test_set_force_password_change_new_user(self):
        storage = InMemoryUserStorage()
        storage.set_force_password_change("user1", True)
        assert storage.users["user1"]["force_change"] is True

    def test_set_force_password_change_existing_user(self):
        storage = InMemoryUserStorage()
        storage.users["user1"] = {"name": "test"}
        storage.set_force_password_change("user1", False)
        assert storage.users["user1"]["force_change"] is False

    def test_validate(self):
        storage = InMemoryUserStorage()
        result = storage.validate()
        assert result["is_valid"] is True

    def test_to_dict(self):
        storage = InMemoryUserStorage()
        storage.users["u1"] = {}
        storage.password_history["u1"] = ["h1"]
        d = storage.to_dict()
        assert d["users_count"] == 1
        assert d["history_count"] == 1

    def test_clone(self):
        storage = InMemoryUserStorage()
        storage.users["u1"] = {"name": "test"}
        clone = storage.clone()
        assert clone is not storage
        assert clone.users == storage.users
        assert clone.password_history == storage.password_history

    def test_snapshot(self):
        storage = InMemoryUserStorage()
        storage.users["u1"] = {}
        snap = storage.snapshot()
        assert snap["users_count"] == 1

    def test_version(self):
        storage = InMemoryUserStorage()
        assert storage.version() == 1

    def test_touch(self):
        storage = InMemoryUserStorage()
        old = storage._version
        storage.touch("tester")
        assert storage._version == old + 1


# ============================================================================
# Tests for PasswordPolicyEnforcer
# ============================================================================

class TestPasswordPolicyEnforcer:
    # ---- validate_password_strength ----

    def test_validate_password_strength_valid(self, enforcer, strong_password):
        valid, errors = enforcer.validate_password_strength(strong_password)
        assert valid is True
        assert errors == []

    def test_validate_password_strength_too_short(self, enforcer):
        valid, errors = enforcer.validate_password_strength("Ab1!")
        assert valid is False
        assert any("at least 8" in e for e in errors)

    def test_validate_password_strength_no_uppercase(self, enforcer):
        valid, errors = enforcer.validate_password_strength("lowercase1!")
        assert valid is False
        assert any("uppercase" in e for e in errors)

    def test_validate_password_strength_no_lowercase(self, enforcer):
        valid, errors = enforcer.validate_password_strength("UPPERCASE1!")
        assert valid is False
        assert any("lowercase" in e for e in errors)

    def test_validate_password_strength_no_digit(self, enforcer):
        valid, errors = enforcer.validate_password_strength("NoDigit!")
        assert valid is False
        assert any("digit" in e for e in errors)

    def test_validate_password_strength_no_special(self, enforcer):
        valid, errors = enforcer.validate_password_strength("NoSpecial1")
        assert valid is False
        assert any("special" in e for e in errors)

    def test_validate_password_strength_common(self, enforcer):
        valid, errors = enforcer.validate_password_strength("password")
        assert valid is False
        assert any("common" in e for e in errors)

    def test_validate_password_strength_contains_username(self, enforcer):
        valid, errors = enforcer.validate_password_strength("myusername123!", username="myusername")
        assert valid is False
        assert any("contain username" in e for e in errors)

    def test_validate_password_strength_common_lowercase(self, enforcer):
        valid, errors = enforcer.validate_password_strength("PASSWORD")
        assert valid is False
        assert any("common" in e for e in errors)

    # ---- password expiry ----

    def test_is_password_expired_true(self, enforcer):
        old_date = datetime.now(UTC) - timedelta(days=100)
        assert enforcer.is_password_expired(old_date) is True

    def test_is_password_expired_false(self, enforcer):
        recent = datetime.now(UTC) - timedelta(days=10)
        assert enforcer.is_password_expired(recent) is False

    def test_get_days_until_expiry(self, enforcer):
        recent = datetime.now(UTC) - timedelta(days=10)
        days = enforcer.get_days_until_expiry(recent)
        # policy.max_age_days=90, so days left = 80
        assert days == 80

    def test_get_days_until_expiry_expired(self, enforcer):
        old = datetime.now(UTC) - timedelta(days=100)
        assert enforcer.get_days_until_expiry(old) == 0

    def test_check_password_expiry_not_expired(self, enforcer):
        recent = datetime.now(UTC) - timedelta(days=10)
        expired, days = enforcer.check_password_expiry(recent)
        assert expired is False
        assert days > 0

    def test_check_password_expiry_expired(self, enforcer):
        old = datetime.now(UTC) - timedelta(days=100)
        expired, days = enforcer.check_password_expiry(old)
        assert expired is True
        assert days == 0

    # ---- password history reuse ----

    def test_is_password_reused_with_storage(self, enforcer, storage):
        user_id = "user1"
        storage.password_history[user_id] = [PasswordHasher.hash("oldpass")]
        # Simulate that new password is "newpass" not reused
        reused = enforcer._is_password_reused(user_id, "newpass")
        assert reused is False

        # Now check with reused password
        reused2 = enforcer._is_password_reused(user_id, "oldpass")
        assert reused2 is True

    def test_is_password_reused_no_storage(self, enforcer):
        enforcer.storage = None
        reused = enforcer._is_password_reused("user", "pass")
        assert reused is False

    def test_store_password_history(self, enforcer, storage):
        enforcer._store_password_history("user1", "hash123")
        assert storage.password_history["user1"] == ["hash123"]

    def test_store_password_history_storage_none(self, enforcer):
        enforcer.storage = None
        # Should not raise
        enforcer._store_password_history("user1", "hash")

    # ---- failed attempts and lockout ----

    def test_get_failed_attempts_redis(self, enforcer, mock_redis):
        mock_redis.lrange.return_value = ["1234567890.0"]
        attempts = enforcer._get_failed_attempts("user1")
        assert len(attempts) == 1
        assert isinstance(attempts[0], datetime)

    def test_get_failed_attempts_memory(self, enforcer):
        # Disable redis by setting redis to None
        enforcer.redis = None
        enforcer._failed_attempts["user1"] = [datetime.now(UTC)]
        attempts = enforcer._get_failed_attempts("user1")
        assert len(attempts) == 1

    def test_add_failed_attempt_redis(self, enforcer, mock_redis):
        enforcer._add_failed_attempt("user1")
        mock_redis.lpush.assert_called_once()
        mock_redis.expire.assert_called_once()

    def test_add_failed_attempt_memory(self, enforcer):
        enforcer.redis = None
        enforcer._add_failed_attempt("user1")
        assert "user1" in enforcer._failed_attempts
        assert len(enforcer._failed_attempts["user1"]) == 1

    def test_add_failed_attempt_memory_prunes_old(self, enforcer):
        enforcer.redis = None
        # Add many attempts, older than lockout duration
        now = datetime.now(UTC)
        old = now - timedelta(minutes=40)
        enforcer._failed_attempts["user1"] = [old, old, old]
        enforcer._add_failed_attempt("user1")
        # Only the latest should remain? Actually the prune removes old, then appends new.
        # So list should have one new attempt and any within lockout window.
        # Since the old ones are outside 30 min, they are removed.
        assert len(enforcer._failed_attempts["user1"]) == 1

    def test_clear_failed_attempts_redis(self, enforcer, mock_redis):
        enforcer._clear_failed_attempts("user1")
        mock_redis.delete.assert_called_once_with("login_failures:user1")

    def test_clear_failed_attempts_memory(self, enforcer):
        enforcer.redis = None
        enforcer._failed_attempts["user1"] = [datetime.now(UTC)]
        enforcer._clear_failed_attempts("user1")
        assert "user1" not in enforcer._failed_attempts

    def test_is_account_locked_redis(self, enforcer, mock_redis):
        # Less than max attempts
        mock_redis.lrange.return_value = ["1", "2"]  # 2 attempts, max=3
        assert enforcer.is_account_locked("user1") is False
        # 3 attempts -> locked
        mock_redis.lrange.return_value = ["1", "2", "3"]
        assert enforcer.is_account_locked("user1") is True

    def test_is_account_locked_memory(self, enforcer):
        enforcer.redis = None
        enforcer._failed_attempts["user1"] = [datetime.now(UTC), datetime.now(UTC)]
        assert enforcer.is_account_locked("user1") is False
        enforcer._failed_attempts["user1"].append(datetime.now(UTC))
        assert enforcer.is_account_locked("user1") is True

    def test_record_failed_attempt(self, enforcer):
        enforcer._add_failed_attempt = MagicMock()
        enforcer._get_failed_attempts = MagicMock(return_value=[1, 2])
        count = enforcer.record_failed_attempt("user1")
        assert count == 2
        enforcer._add_failed_attempt.assert_called_once_with("user1")
        assert enforcer._audit_trail[-1]["action"] == "RECORD_FAILED_ATTEMPT"

    def test_record_successful_login(self, enforcer):
        enforcer._clear_failed_attempts = MagicMock()
        enforcer.record_successful_login("user1")
        enforcer._clear_failed_attempts.assert_called_once_with("user1")
        assert enforcer._audit_trail[-1]["action"] == "RECORD_SUCCESSFUL_LOGIN"

    def test_get_lockout_remaining_seconds_not_locked(self, enforcer):
        enforcer._get_failed_attempts = MagicMock(return_value=[datetime.now(UTC)])
        assert enforcer.get_lockout_remaining_seconds("user1") == 0

    def test_get_lockout_remaining_seconds_locked(self, enforcer):
        # 3 attempts, max=3 -> locked
        now = datetime.now(UTC)
        enforcer._get_failed_attempts = MagicMock(return_value=[now, now, now])
        remaining = enforcer.get_lockout_remaining_seconds("user1")
        # Should be close to 30 minutes (1800 seconds)
        assert 1700 <= remaining <= 1800

    def test_pre_login_check_not_locked(self, enforcer):
        enforcer.is_account_locked = MagicMock(return_value=False)
        # Should not raise
        enforcer.pre_login_check("user1")

    def test_pre_login_check_locked(self, enforcer):
        enforcer.is_account_locked = MagicMock(return_value=True)
        enforcer.get_lockout_remaining_seconds = MagicMock(return_value=123)
        with pytest.raises(AccountLockedError, match="123 seconds"):
            enforcer.pre_login_check("user1")

    # ---- enforce_new_password ----

    def test_enforce_new_password_success(self, enforcer, strong_password):
        enforcer.validate_password_strength = MagicMock(return_value=(True, []))
        enforcer._is_password_reused = MagicMock(return_value=False)
        enforcer._store_password_history = MagicMock()
        hashed = enforcer.enforce_new_password("user1", "username", strong_password)
        assert isinstance(hashed, str)
        enforcer._store_password_history.assert_called_once()

    def test_enforce_new_password_weak(self, enforcer):
        enforcer.validate_password_strength = MagicMock(return_value=(False, ["Too weak"]))
        with pytest.raises(WeakPasswordError, match="Too weak"):
            enforcer.enforce_new_password("user1", "username", "weak")

    def test_enforce_new_password_reused(self, enforcer):
        enforcer.validate_password_strength = MagicMock(return_value=(True, []))
        enforcer._is_password_reused = MagicMock(return_value=True)
        with pytest.raises(WeakPasswordError, match="Password has been used recently"):
            enforcer.enforce_new_password("user1", "username", "newpass")

    # ---- admin functions ----

    def test_force_password_change_with_storage(self, enforcer, storage):
        enforcer.force_password_change("user1")
        assert storage.users["user1"]["force_change"] is True
        assert enforcer._audit_trail[-1]["action"] == "FORCE_PASSWORD_CHANGE"

    def test_force_password_change_no_storage(self, enforcer):
        enforcer.storage = None
        # Should not raise
        enforcer.force_password_change("user1")

    def test_unlock_account(self, enforcer):
        enforcer._clear_failed_attempts = MagicMock()
        enforcer.unlock_account("user1")
        enforcer._clear_failed_attempts.assert_called_once_with("user1")
        assert enforcer._audit_trail[-1]["action"] == "UNLOCK_ACCOUNT"

    # ---- reporting ----

    def test_generate_report(self, enforcer):
        report = enforcer.generate_report()
        assert "policy" in report
        assert "hasher" in report
        assert "version" in report

    def test_get_statistics(self, enforcer):
        stats = enforcer.get_statistics()
        assert stats == enforcer.generate_report()

    # ---- entity methods ----

    def test_validate_valid(self, enforcer):
        result = enforcer.validate()
        assert result["is_valid"] is True

    def test_validate_invalid_policy(self, enforcer):
        enforcer.policy.min_length = 0
        result = enforcer.validate()
        assert result["is_valid"] is False
        assert any("Policy" in e for e in result["errors"])

    def test_to_dict(self, enforcer):
        d = enforcer.to_dict()
        assert "policy" in d
        assert "version" in d

    def test_from_dict(self):
        data = {"policy": {"min_length": 10, "version": 2}, "version": 5}
        enforcer = PasswordPolicyEnforcer.from_dict(data)
        assert enforcer.policy.min_length == 10
        assert enforcer._version == 5

    def test_clone(self, enforcer):
        clone = enforcer.clone()
        assert clone is not enforcer
        assert clone._version == enforcer._version + 1
        assert clone.policy._version == enforcer.policy._version + 1

    def test_snapshot(self, enforcer):
        snap = enforcer.snapshot()
        assert snap["version"] == enforcer._version
        assert snap["policy_version"] == enforcer.policy._version

    def test_version(self, enforcer):
        assert enforcer.version() == enforcer._version

    def test_audit_trail(self, enforcer):
        enforcer._record_audit("TEST", "user", {})
        trail = enforcer.audit_trail()
        assert len(trail) == 1

    def test_touch(self, enforcer):
        old = enforcer._version
        enforcer.touch("tester")
        assert enforcer._version == old + 1
        assert enforcer._audit_trail[-1]["action"] == "TOUCH"

    def test_reset(self, enforcer):
        enforcer._failed_attempts["user1"] = [datetime.now(UTC)]
        enforcer._version = 10
        enforcer._audit_trail = [{"action": "test"}]
        enforcer.reset()
        assert enforcer._failed_attempts == {}
        assert enforcer._version == 1
        assert enforcer._audit_trail == []
        assert enforcer._snapshots != []  # snapshots not cleared? Actually reset clears them
        # Check reset clears snapshots too? The implementation clears _snapshots as well.
        assert enforcer._snapshots == []
        assert enforcer._audit_trail[-1]["action"] == "RESET"

    # ---- integration: enforce_new_password full flow ----

    def test_enforce_new_password_full_flow(self, enforcer, storage, strong_password):
        # First password should work
        hashed1 = enforcer.enforce_new_password("user1", "username", strong_password)
        storage.users["user1"] = {"password": hashed1}
        # Second password same as first should be rejected
        with pytest.raises(WeakPasswordError, match="recently"):
            enforcer.enforce_new_password("user1", "username", strong_password)
        # Different strong password should work
        hashed2 = enforcer.enforce_new_password("user1", "username", "AnotherStr0ngP@ss!")
        assert hashed2 != hashed1

    # ---- lockout workflow ----

    def test_lockout_workflow(self, enforcer):
        user_id = "user1"
        # Record 3 failed attempts
        for _ in range(3):
            count = enforcer.record_failed_attempt(user_id)
        assert enforcer.is_account_locked(user_id) is True
        # Pre-login check raises
        with pytest.raises(AccountLockedError):
            enforcer.pre_login_check(user_id)
        # Successful login clears
        enforcer.record_successful_login(user_id)
        assert enforcer.is_account_locked(user_id) is False