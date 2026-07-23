# test_password_hashed_vo.py
# Comprehensive tests for domain/iam/password_hashed_vo.py
# Covers all classes, methods, edge cases, exceptions, and helper functions.

import hashlib
import hmac
import secrets
from datetime import UTC, datetime
from unittest.mock import patch, MagicMock

import pytest

from domain.iam.password_hashed_vo import (
    BCRYPT_AVAILABLE,
    PasswordCommonError,
    PasswordError,
    PasswordHashedVO,
    PasswordHashError,
    PasswordMissingDigitError,
    PasswordMissingLowercaseError,
    PasswordMissingSpecialError,
    PasswordMissingUppercaseError,
    PasswordPolicy,
    PasswordTooLongError,
    PasswordTooShortError,
    PasswordVerifyError,
    generate_random_password,
    hash_password,
    is_password_strong,
    verify_password,
    COMMON_PASSWORDS,
    MIN_PASSWORD_LENGTH,
    MAX_PASSWORD_LENGTH,
    SPECIAL_CHARS,
    DEFAULT_PBKDF2_ITERATIONS,
    DEFAULT_BCRYPT_ROUNDS,
    ARGON2_AVAILABLE,
)


# -------------------- Fixtures --------------------
@pytest.fixture
def default_policy():
    return PasswordPolicy()


@pytest.fixture
def strict_policy():
    return PasswordPolicy(
        min_length=10,
        max_length=20,
        require_uppercase=True,
        require_lowercase=True,
        require_digit=True,
        require_special=True,
        forbid_common=True,
        forbid_username=True,
        max_repeated_chars=2,
    )


@pytest.fixture
def valid_password():
    return "SecureP@ssw0rd123!"


@pytest.fixture
def valid_password_username():
    return "SecureP@ssw0rd123!"


@pytest.fixture
def username():
    return "john_doe"


# -------------------- Tests for Exceptions --------------------
class TestExceptions:
    def test_password_error(self):
        with pytest.raises(PasswordError):
            raise PasswordError("test")

    def test_password_too_short(self):
        with pytest.raises(PasswordTooShortError):
            raise PasswordTooShortError("short")

    def test_password_too_long(self):
        with pytest.raises(PasswordTooLongError):
            raise PasswordTooLongError("long")

    def test_password_missing_uppercase(self):
        with pytest.raises(PasswordMissingUppercaseError):
            raise PasswordMissingUppercaseError("no upper")

    def test_password_missing_lowercase(self):
        with pytest.raises(PasswordMissingLowercaseError):
            raise PasswordMissingLowercaseError("no lower")

    def test_password_missing_digit(self):
        with pytest.raises(PasswordMissingDigitError):
            raise PasswordMissingDigitError("no digit")

    def test_password_missing_special(self):
        with pytest.raises(PasswordMissingSpecialError):
            raise PasswordMissingSpecialError("no special")

    def test_password_common(self):
        with pytest.raises(PasswordCommonError):
            raise PasswordCommonError("common")

    def test_password_hash_error(self):
        with pytest.raises(PasswordHashError):
            raise PasswordHashError("hash error")

    def test_password_verify_error(self):
        with pytest.raises(PasswordVerifyError):
            raise PasswordVerifyError("verify error")


# -------------------- Tests for PasswordPolicy --------------------
class TestPasswordPolicy:
    def test_default_policy(self, default_policy):
        assert default_policy.min_length == 8
        assert default_policy.max_length == 128
        assert default_policy.require_uppercase is True
        assert default_policy.require_lowercase is True
        assert default_policy.require_digit is True
        assert default_policy.require_special is True
        assert default_policy.forbid_common is True
        assert default_policy.forbid_username is True
        assert default_policy.max_repeated_chars == 3

    def test_validate_valid_password(self, default_policy, valid_password):
        # Should not raise
        default_policy.validate(valid_password)

    def test_validate_empty_password(self, default_policy):
        with pytest.raises(PasswordError, match="Password cannot be empty"):
            default_policy.validate("")

    def test_validate_too_short(self, default_policy):
        with pytest.raises(PasswordTooShortError, match="at least 8 characters"):
            default_policy.validate("Abc12!")

    def test_validate_too_long(self, default_policy):
        long_pwd = "A" * 129
        with pytest.raises(PasswordTooLongError, match="cannot exceed 128 characters"):
            default_policy.validate(long_pwd)

    def test_validate_no_uppercase(self, default_policy):
        with pytest.raises(PasswordMissingUppercaseError, match="uppercase letter"):
            default_policy.validate("lowercase123!")

    def test_validate_no_lowercase(self, default_policy):
        with pytest.raises(PasswordMissingLowercaseError, match="lowercase letter"):
            default_policy.validate("UPPERCASE123!")

    def test_validate_no_digit(self, default_policy):
        with pytest.raises(PasswordMissingDigitError, match="digit"):
            default_policy.validate("NoDigit!")

    def test_validate_no_special(self, default_policy):
        with pytest.raises(PasswordMissingSpecialError, match="special character"):
            default_policy.validate("NoSpecial123")

    def test_validate_repeated_chars(self, default_policy):
        with pytest.raises(PasswordError, match="more than 3 repeated characters"):
            default_policy.validate("aaaa123!")

    def test_validate_common_password(self, default_policy):
        with pytest.raises(PasswordCommonError, match="too common"):
            default_policy.validate("password")

    def test_validate_contains_username(self, default_policy, username):
        with pytest.raises(PasswordError, match="cannot contain username"):
            default_policy.validate(f"{username}123!", username)

    def test_custom_policy(self, strict_policy):
        # min length 10
        with pytest.raises(PasswordTooShortError):
            strict_policy.validate("Abc123!!", username=None)
        # max length 20
        long_pwd = "A" * 21
        with pytest.raises(PasswordTooLongError):
            strict_policy.validate(long_pwd)
        # max repeated chars 2
        with pytest.raises(PasswordError, match="more than 2 repeated"):
            strict_policy.validate("aaA123!!", username=None)


# -------------------- Tests for PasswordHashedVO --------------------
class TestPasswordHashedVO:
    def test_construction_valid_bcrypt(self):
        # For bcrypt, we need a valid hash. We'll mock bcrypt to create one.
        with patch("domain.iam.password_hashed_vo.BCRYPT_AVAILABLE", True):
            with patch("domain.iam.password_hashed_vo.bcrypt") as mock_bcrypt:
                mock_bcrypt.gensalt.return_value = b"salt"
                mock_bcrypt.hashpw.return_value = b"$2b$12$hash..."
                pwd = PasswordHashedVO.create_from_plain("ValidP@ss123")
                # Now test construction with that hash
                vo = PasswordHashedVO(
                    hashed_value=pwd.hashed_value,
                    algorithm="bcrypt",
                    salt="somesalt",
                    iterations=12,
                )
                assert vo.hashed_value == pwd.hashed_value
                assert vo.algorithm == "bcrypt"

    def test_construction_invalid_hash_short(self):
        with pytest.raises(PasswordHashError, match="Invalid password hash"):
            PasswordHashedVO(hashed_value="short", algorithm="pbkdf2_sha256")

    def test_construction_invalid_iterations_bcrypt(self):
        with pytest.raises(PasswordHashError, match="Invalid bcrypt rounds"):
            PasswordHashedVO(
                hashed_value="somehash1234567890",
                algorithm="bcrypt",
                iterations=3,
            )

    def test_construction_invalid_iterations_pbkdf2(self):
        with pytest.raises(PasswordHashError, match="Invalid iterations"):
            PasswordHashedVO(
                hashed_value="somehash1234567890",
                algorithm="pbkdf2_sha256",
                iterations=500,
            )

    def test_set_and_get_policy(self):
        new_policy = PasswordPolicy(min_length=12)
        PasswordHashedVO.set_policy(new_policy)
        assert PasswordHashedVO.get_policy() is new_policy
        # Reset to default for other tests
        PasswordHashedVO.set_policy(PasswordPolicy())

    # ---- create_from_plain ----
    def test_create_from_plain_bcrypt(self):
        with patch("domain.iam.password_hashed_vo.BCRYPT_AVAILABLE", True):
            with patch("domain.iam.password_hashed_vo.bcrypt") as mock_bcrypt:
                mock_bcrypt.gensalt.return_value = b"salt"
                mock_bcrypt.hashpw.return_value = b"$2b$12$hash"
                vo = PasswordHashedVO.create_from_plain("ValidP@ss123")
                assert vo.algorithm == "bcrypt"
                assert vo.salt is not None
                assert vo.iterations == DEFAULT_BCRYPT_ROUNDS

    def test_create_from_plain_pbkdf2_fallback(self):
        with patch("domain.iam.password_hashed_vo.BCRYPT_AVAILABLE", False):
            with patch("domain.iam.password_hashed_vo.ARGON2_AVAILABLE", False):
                vo = PasswordHashedVO.create_from_plain("ValidP@ss123")
                assert vo.algorithm == "pbkdf2_sha256"
                assert vo.salt is not None
                assert vo.iterations == DEFAULT_PBKDF2_ITERATIONS
                # Check hash format
                parts = vo.hashed_value.split("$")
                assert len(parts) == 4
                assert parts[0] == "pbkdf2_sha256"
                assert int(parts[1]) == DEFAULT_PBKDF2_ITERATIONS
                assert len(parts[2]) > 0
                assert len(parts[3]) > 0

    def test_create_from_plain_argon2(self):
        with patch("domain.iam.password_hashed_vo.ARGON2_AVAILABLE", True):
            with patch("domain.iam.password_hashed_vo.argon2") as mock_argon2:
                mock_hasher = MagicMock()
                mock_hasher.hash.return_value = "argon2_hash"
                mock_argon2.PasswordHasher.return_value = mock_hasher
                vo = PasswordHashedVO.create_from_plain(
                    "ValidP@ss123", algorithm="argon2"
                )
                assert vo.algorithm == "argon2"
                assert vo.hashed_value == "argon2_hash"
                assert vo.iterations == 2  # default time_cost

    def test_create_from_plain_invalid_password_policy(self):
        with pytest.raises(PasswordTooShortError):
            PasswordHashedVO.create_from_plain("Abc12!")

    def test_create_from_plain_unknown_algorithm(self):
        # Should fallback to PBKDF2 if algorithm unknown
        with patch("domain.iam.password_hashed_vo.BCRYPT_AVAILABLE", False):
            with patch("domain.iam.password_hashed_vo.ARGON2_AVAILABLE", False):
                vo = PasswordHashedVO.create_from_plain(
                    "ValidP@ss123", algorithm="unknown"
                )
                assert vo.algorithm == "pbkdf2_sha256"

    # ---- _hash_bcrypt ----
    def test_hash_bcrypt(self):
        with patch("domain.iam.password_hashed_vo.bcrypt") as mock_bcrypt:
            mock_bcrypt.gensalt.return_value = b"salt"
            mock_bcrypt.hashpw.return_value = b"$2b$12$hash"
            vo = PasswordHashedVO._hash_bcrypt("password")
            assert vo.hashed_value == "$2b$12$hash"
            assert vo.algorithm == "bcrypt"
            assert vo.salt == "salt"
            assert vo.iterations == DEFAULT_BCRYPT_ROUNDS

    # ---- _hash_argon2 ----
    def test_hash_argon2(self):
        with patch("domain.iam.password_hashed_vo.argon2") as mock_argon2:
            mock_hasher = MagicMock()
            mock_hasher.hash.return_value = "argon2_hash"
            mock_argon2.PasswordHasher.return_value = mock_hasher
            vo = PasswordHashedVO._hash_argon2("password")
            assert vo.hashed_value == "argon2_hash"
            assert vo.algorithm == "argon2"
            assert vo.iterations == 2

    # ---- _hash_pbkdf2 ----
    def test_hash_pbkdf2(self):
        with patch("secrets.token_bytes") as mock_token:
            mock_token.return_value = b"salt123"
            vo = PasswordHashedVO._hash_pbkdf2("password")
            parts = vo.hashed_value.split("$")
            assert parts[0] == "pbkdf2_sha256"
            assert int(parts[1]) == DEFAULT_PBKDF2_ITERATIONS
            assert parts[2] == "73616c74313233"  # hex of "salt123"
            assert len(parts[3]) > 0
            assert vo.algorithm == "pbkdf2_sha256"
            assert vo.salt == "73616c74313233"

    # ---- verify ----
    def test_verify_bcrypt_success(self):
        with patch("domain.iam.password_hashed_vo.BCRYPT_AVAILABLE", True):
            with patch("domain.iam.password_hashed_vo.bcrypt") as mock_bcrypt:
                mock_bcrypt.checkpw.return_value = True
                vo = PasswordHashedVO(
                    hashed_value="$2b$12$hash",
                    algorithm="bcrypt",
                    iterations=12,
                )
                assert vo.verify("password") is True
                mock_bcrypt.checkpw.assert_called_once()

    def test_verify_bcrypt_failure(self):
        with patch("domain.iam.password_hashed_vo.BCRYPT_AVAILABLE", True):
            with patch("domain.iam.password_hashed_vo.bcrypt") as mock_bcrypt:
                mock_bcrypt.checkpw.return_value = False
                vo = PasswordHashedVO(
                    hashed_value="$2b$12$hash",
                    algorithm="bcrypt",
                    iterations=12,
                )
                assert vo.verify("wrong") is False

    def test_verify_argon2_success(self):
        with patch("domain.iam.password_hashed_vo.ARGON2_AVAILABLE", True):
            with patch("domain.iam.password_hashed_vo.argon2") as mock_argon2:
                mock_hasher = MagicMock()
                mock_hasher.verify.return_value = None
                mock_argon2.PasswordHasher.return_value = mock_hasher
                vo = PasswordHashedVO(
                    hashed_value="argon2_hash",
                    algorithm="argon2",
                )
                assert vo.verify("password") is True

    def test_verify_argon2_failure(self):
        with patch("domain.iam.password_hashed_vo.ARGON2_AVAILABLE", True):
            with patch("domain.iam.password_hashed_vo.argon2") as mock_argon2:
                mock_hasher = MagicMock()
                mock_hasher.verify.side_effect = mock_argon2.exceptions.VerificationError()
                mock_argon2.PasswordHasher.return_value = mock_hasher
                mock_argon2.exceptions.VerificationError = Exception
                vo = PasswordHashedVO(
                    hashed_value="argon2_hash",
                    algorithm="argon2",
                )
                assert vo.verify("wrong") is False

    def test_verify_pbkdf2_success(self):
        # Create a known hash
        salt = b"salt123"
        iterations = 100000
        password = "password"
        hash_obj = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
        hashed_value = f"pbkdf2_sha256${iterations}${salt.hex()}${hash_obj.hex()}"
        vo = PasswordHashedVO(
            hashed_value=hashed_value,
            algorithm="pbkdf2_sha256",
            salt=salt.hex(),
            iterations=iterations,
        )
        assert vo.verify(password) is True

    def test_verify_pbkdf2_wrong_password(self):
        salt = b"salt123"
        iterations = 100000
        password = "password"
        hash_obj = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
        hashed_value = f"pbkdf2_sha256${iterations}${salt.hex()}${hash_obj.hex()}"
        vo = PasswordHashedVO(hashed_value=hashed_value, algorithm="pbkdf2_sha256")
        assert vo.verify("wrong") is False

    def test_verify_pbkdf2_invalid_format(self):
        vo = PasswordHashedVO(
            hashed_value="invalid_format",
            algorithm="pbkdf2_sha256",
        )
        assert vo.verify("password") is False

    def test_verify_pbkdf2_invalid_salt(self):
        salt = b"salt123"
        iterations = 100000
        password = "password"
        hash_obj = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
        hashed_value = f"pbkdf2_sha256${iterations}${salt.hex()}${hash_obj.hex()}"
        vo = PasswordHashedVO(hashed_value=hashed_value, algorithm="pbkdf2_sha256")
        # Modify salt in object to corrupt
        object.__setattr__(vo, "salt", "invalid")
        # The verification will parse from hashed_value, so salt in object is not used.
        # Instead, we can create a corrupted hashed_value.
        corrupted = f"pbkdf2_sha256${iterations}${'a'*10}${hash_obj.hex()}"
        vo2 = PasswordHashedVO(hashed_value=corrupted, algorithm="pbkdf2_sha256")
        assert vo2.verify(password) is False

    def test_verify_unknown_algorithm(self):
        vo = PasswordHashedVO(
            hashed_value="hash",
            algorithm="unknown",
        )
        assert vo.verify("password") is False

    def test_verify_empty_password(self):
        vo = PasswordHashedVO(
            hashed_value="somehash1234567890",
            algorithm="pbkdf2_sha256",
        )
        assert vo.verify("") is False

    def test_verify_handles_exception(self):
        # Simulate an error in bcrypt.checkpw
        with patch("domain.iam.password_hashed_vo.BCRYPT_AVAILABLE", True):
            with patch("domain.iam.password_hashed_vo.bcrypt") as mock_bcrypt:
                mock_bcrypt.checkpw.side_effect = ValueError("bad")
                vo = PasswordHashedVO(
                    hashed_value="$2b$12$hash",
                    algorithm="bcrypt",
                    iterations=12,
                )
                # Should return False (not raise)
                assert vo.verify("password") is False

    # ---- needs_rehash ----
    def test_needs_rehash_bcrypt_ok(self):
        with patch("domain.iam.password_hashed_vo.BCRYPT_AVAILABLE", True):
            vo = PasswordHashedVO(
                hashed_value="$2b$12$hash",
                algorithm="bcrypt",
                iterations=12,
            )
            # DEFAULT_BCRYPT_ROUNDS is also 12, so False
            assert vo.needs_rehash() is False

    def test_needs_rehash_bcrypt_low_rounds(self):
        with patch("domain.iam.password_hashed_vo.BCRYPT_AVAILABLE", True):
            vo = PasswordHashedVO(
                hashed_value="$2b$10$hash",
                algorithm="bcrypt",
                iterations=10,
            )
            assert vo.needs_rehash() is True

    def test_needs_rehash_bcrypt_invalid_format(self):
        with patch("domain.iam.password_hashed_vo.BCRYPT_AVAILABLE", True):
            vo = PasswordHashedVO(
                hashed_value="invalid",
                algorithm="bcrypt",
                iterations=12,
            )
            # Should return True if parsing fails
            assert vo.needs_rehash() is True

    def test_needs_rehash_argon2(self):
        vo = PasswordHashedVO(
            hashed_value="argon2_hash",
            algorithm="argon2",
        )
        assert vo.needs_rehash() is False

    def test_needs_rehash_pbkdf2_low_iterations(self):
        vo = PasswordHashedVO(
            hashed_value="somehash",
            algorithm="pbkdf2_sha256",
            iterations=10000,
        )
        assert vo.needs_rehash() is True  # lower than DEFAULT_PBKDF2_ITERATIONS

    def test_needs_rehash_pbkdf2_ok(self):
        vo = PasswordHashedVO(
            hashed_value="somehash",
            algorithm="pbkdf2_sha256",
            iterations=100000,
        )
        assert vo.needs_rehash() is False

    def test_needs_rehash_unknown(self):
        vo = PasswordHashedVO(
            hashed_value="somehash",
            algorithm="unknown",
        )
        assert vo.needs_rehash() is True

    # ---- upgrade_hash ----
    def test_upgrade_hash(self):
        with patch("domain.iam.password_hashed_vo.BCRYPT_AVAILABLE", False):
            with patch("domain.iam.password_hashed_vo.ARGON2_AVAILABLE", False):
                # Create an old hash with low iterations
                salt = b"salt123"
                iterations = 10000
                password = "password"
                hash_obj = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
                hashed_value = f"pbkdf2_sha256${iterations}${salt.hex()}${hash_obj.hex()}"
                vo = PasswordHashedVO(
                    hashed_value=hashed_value,
                    algorithm="pbkdf2_sha256",
                    salt=salt.hex(),
                    iterations=iterations,
                )
                upgraded = vo.upgrade_hash(password)
                assert upgraded is not vo
                assert upgraded.algorithm == "pbkdf2_sha256"
                assert upgraded.iterations == DEFAULT_PBKDF2_ITERATIONS
                # Verify that the upgraded hash still verifies
                assert upgraded.verify(password) is True

    # ---- from_dict ----
    def test_from_dict(self):
        data = {
            "hashed_value": "hash123",
            "algorithm": "bcrypt",
            "salt": "somesalt",
            "iterations": 12,
            "created_at": "2025-01-01T00:00:00+00:00",
        }
        vo = PasswordHashedVO.from_dict(data)
        assert vo.hashed_value == "hash123"
        assert vo.algorithm == "bcrypt"
        assert vo.salt == "somesalt"
        assert vo.iterations == 12
        assert vo.created_at == datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)

    def test_from_dict_missing_created_at(self):
        data = {
            "hashed_value": "hash123",
            "algorithm": "bcrypt",
        }
        vo = PasswordHashedVO.from_dict(data)
        assert vo.created_at is not None
        assert vo.created_at.tzinfo == UTC

    # ---- to_dict ----
    def test_to_dict(self):
        vo = PasswordHashedVO(
            hashed_value="hash123",
            algorithm="bcrypt",
            salt="somesalt",
            iterations=12,
            created_at=datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC),
        )
        d = vo.to_dict()
        assert d["hashed_value"] == "hash123"
        assert d["algorithm"] == "bcrypt"
        assert d["salt"] == "somesalt"
        assert d["iterations"] == 12
        assert d["created_at"] == "2025-01-01T00:00:00+00:00"

    # ---- to_db_record ----
    def test_to_db_record(self):
        vo = PasswordHashedVO(
            hashed_value="hash123",
            algorithm="bcrypt",
            salt="somesalt",
            iterations=12,
            created_at=datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC),
        )
        rec = vo.to_db_record()
        assert rec["password_hash"] == "hash123"
        assert rec["password_algorithm"] == "bcrypt"
        assert rec["password_salt"] == "somesalt"
        assert rec["password_iterations"] == 12
        assert rec["password_created_at"] == datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)

    # ---- dunder methods ----
    def test_str_and_repr(self):
        vo = PasswordHashedVO(
            hashed_value="hash1234567890",
            algorithm="bcrypt",
        )
        assert str(vo).startswith("PasswordHashedVO(algorithm=bcrypt, hash=hash1234567890...")
        assert repr(vo).startswith("PasswordHashedVO(algorithm=bcrypt, hash_length=")

    def test_equality(self):
        vo1 = PasswordHashedVO(hashed_value="hash1", algorithm="bcrypt")
        vo2 = PasswordHashedVO(hashed_value="hash1", algorithm="bcrypt")
        vo3 = PasswordHashedVO(hashed_value="hash2", algorithm="bcrypt")
        assert vo1 == vo2
        assert vo1 != vo3
        assert vo1 != "not a vo"

    def test_hash(self):
        vo = PasswordHashedVO(hashed_value="hash1", algorithm="bcrypt")
        assert hash(vo) == hash("hash1")


# -------------------- Tests for Helper Functions --------------------
class TestHelpers:
    def test_generate_random_password_default(self):
        pwd = generate_random_password()
        assert len(pwd) == 12
        # Check contains special chars (since default include_special=True)
        assert any(c in SPECIAL_CHARS for c in pwd)

    def test_generate_random_password_no_special(self):
        pwd = generate_random_password(length=15, include_special=False)
        assert len(pwd) == 15
        assert not any(c in SPECIAL_CHARS for c in pwd)

    def test_generate_random_password_uses_secrets(self):
        with patch("secrets.choice") as mock_choice:
            mock_choice.return_value = "A"
            pwd = generate_random_password(length=5)
            assert pwd == "AAAAA"
            mock_choice.assert_called()

    def test_hash_password(self):
        with patch("domain.iam.password_hashed_vo.PasswordHashedVO.create_from_plain") as mock_create:
            mock_create.return_value = MagicMock()
            result = hash_password("password", "user")
            mock_create.assert_called_once_with("password", "user")
            assert result is mock_create.return_value

    def test_verify_password(self):
        mock_vo = MagicMock()
        mock_vo.verify.return_value = True
        result = verify_password("password", mock_vo)
        mock_vo.verify.assert_called_once_with("password")
        assert result is True

    def test_is_password_strong_valid(self):
        # Use a password that satisfies default policy
        strong = is_password_strong("ValidP@ss123")
        assert strong is True

    def test_is_password_strong_invalid(self):
        weak = is_password_strong("weak")
        assert weak is False