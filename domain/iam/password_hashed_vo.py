#!/usr/bin/env python3
"""
Module: password_hashed_vo.py
Layer: Domain / IAM
Responsibility: Value object password yang sudah di-hash dengan semua method value object.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar

logger = logging.getLogger(__name__)


# ============================================================================
# Constants
# ============================================================================

# Password policy constants
MIN_PASSWORD_LENGTH: int = 8
MAX_PASSWORD_LENGTH: int = 128
PASSWORD_REQUIRES_UPPERCASE: bool = True
PASSWORD_REQUIRES_LOWERCASE: bool = True
PASSWORD_REQUIRES_DIGIT: bool = True
PASSWORD_REQUIRES_SPECIAL: bool = True
SPECIAL_CHARS: str = "!@#$%^&*()_+-=[]{}|;:,.<>?"
COMMON_PASSWORDS: set[str] = {
    "password",
    "123456",
    "12345678",
    "qwerty",
    "abc123",
    "monkey",
    "letmein",
    "dragon",
    "baseball",
    "iloveyou",
    "trustno1",
    "123456789",
    "1234567890",
    "admin",
    "welcome",
    "login",
    "password1",
}

# BCrypt constants
BCRYPT_AVAILABLE: bool = False
try:
    import bcrypt

    BCRYPT_AVAILABLE = True
except ImportError:
    logger.warning("bcrypt not available, using PBKDF2 fallback")

# Argon2 constants
ARGON2_AVAILABLE: bool = False
try:
    import argon2

    ARGON2_AVAILABLE = True
except ImportError:
    pass

# Default hashing parameters
DEFAULT_BCRYPT_ROUNDS: int = 12
DEFAULT_PBKDF2_ITERATIONS: int = 100000
DEFAULT_PBKDF2_SALT_LENGTH: int = 32
DEFAULT_ARGON2_TIME_COST: int = 2
DEFAULT_ARGON2_MEMORY_COST: int = 19456
DEFAULT_ARGON2_PARALLELISM: int = 1


# ============================================================================
# Custom Exceptions
# ============================================================================


class PasswordError(ValueError):
    pass


class PasswordTooShortError(PasswordError):
    pass


class PasswordTooLongError(PasswordError):
    pass


class PasswordMissingUppercaseError(PasswordError):
    pass


class PasswordMissingLowercaseError(PasswordError):
    pass


class PasswordMissingDigitError(PasswordError):
    pass


class PasswordMissingSpecialError(PasswordError):
    pass


class PasswordCommonError(PasswordError):
    pass


class PasswordHashError(PasswordError):
    pass


class PasswordVerifyError(PasswordError):
    pass


# ============================================================================
# Password Policy
# ============================================================================


class PasswordPolicy:
    """Password policy configuration."""

    def __init__(
        self,
        min_length: int = MIN_PASSWORD_LENGTH,
        max_length: int = MAX_PASSWORD_LENGTH,
        require_uppercase: bool = PASSWORD_REQUIRES_UPPERCASE,
        require_lowercase: bool = PASSWORD_REQUIRES_LOWERCASE,
        require_digit: bool = PASSWORD_REQUIRES_DIGIT,
        require_special: bool = PASSWORD_REQUIRES_SPECIAL,
        special_chars: str = SPECIAL_CHARS,
        forbid_common: bool = True,
        forbid_username: bool = True,
        max_repeated_chars: int = 3,
    ):
        self.min_length = min_length
        self.max_length = max_length
        self.require_uppercase = require_uppercase
        self.require_lowercase = require_lowercase
        self.require_digit = require_digit
        self.require_special = require_special
        self.special_chars = special_chars
        self.forbid_common = forbid_common
        self.forbid_username = forbid_username
        self.max_repeated_chars = max_repeated_chars

    def validate(self, password: str, username: str | None = None) -> None:
        """Validate password against policy."""
        if not password:
            raise PasswordError("Password cannot be empty")

        if len(password) < self.min_length:
            raise PasswordTooShortError(f"Password must be at least {self.min_length} characters")

        if len(password) > self.max_length:
            raise PasswordTooLongError(f"Password cannot exceed {self.max_length} characters")

        if self.require_uppercase and not any(c.isupper() for c in password):
            raise PasswordMissingUppercaseError(
                "Password must contain at least one uppercase letter"
            )

        if self.require_lowercase and not any(c.islower() for c in password):
            raise PasswordMissingLowercaseError(
                "Password must contain at least one lowercase letter"
            )

        if self.require_digit and not any(c.isdigit() for c in password):
            raise PasswordMissingDigitError("Password must contain at least one digit")

        if self.require_special and not any(c in self.special_chars for c in password):
            raise PasswordMissingSpecialError(
                f"Password must contain at least one special character: {self.special_chars}"
            )

        # Check for repeated characters
        if self.max_repeated_chars > 0:
            for i in range(len(password) - self.max_repeated_chars):
                if len(set(password[i : i + self.max_repeated_chars + 1])) == 1:
                    raise PasswordError(
                        f"Password cannot contain more than {self.max_repeated_chars} repeated characters"
                    )

        # Check for common passwords
        if self.forbid_common and password.lower() in COMMON_PASSWORDS:
            raise PasswordCommonError("Password is too common. Please choose a stronger password")

        # Check if password contains username
        if self.forbid_username and username:
            username_lower = username.lower()
            password_lower = password.lower()
            if username_lower in password_lower or password_lower in username_lower:
                raise PasswordError("Password cannot contain username")


# ============================================================================
# Password Hashed Value Object
# ============================================================================


@dataclass(frozen=True)
class PasswordHashedVO:
    hashed_value: str
    algorithm: str = "bcrypt" if BCRYPT_AVAILABLE else "pbkdf2_sha256"
    salt: str | None = None
    iterations: int = DEFAULT_PBKDF2_ITERATIONS
    created_at: datetime = field(default_factory=datetime.now)

    _policy: ClassVar[PasswordPolicy] = PasswordPolicy()
    _cache: ClassVar[dict[str, PasswordHashedVO]] = {}

    def __post_init__(self) -> None:
        """Validate hash format."""
        if not self.hashed_value or len(self.hashed_value) < 10:
            raise PasswordHashError("Invalid password hash")
        if self.iterations < 1000:
            raise PasswordHashError(f"Invalid iterations: {self.iterations}")

    # ==================== FACTORY METHODS ====================

    @classmethod
    def set_policy(cls, policy: PasswordPolicy) -> None:
        """Set global password policy."""
        cls._policy = policy

    @classmethod
    def get_policy(cls) -> PasswordPolicy:
        """Get global password policy."""
        return cls._policy

    @classmethod
    def create_from_plain(
        cls,
        plain_password: str,
        username: str | None = None,
        algorithm: str | None = None,
    ) -> PasswordHashedVO:
        """
        Create PasswordHashedVO from plain password.

        Args:
            plain_password: Password in plaintext
            username: Optional username for policy validation
            algorithm: Hashing algorithm ('bcrypt', 'argon2', 'pbkdf2_sha256')

        Returns:
            PasswordHashedVO with generated hash
        """
        # Validate password strength
        cls._policy.validate(plain_password, username)

        # Select algorithm
        algo = algorithm or ("bcrypt" if BCRYPT_AVAILABLE else "pbkdf2_sha256")

        if algo == "bcrypt" and BCRYPT_AVAILABLE:
            return cls._hash_bcrypt(plain_password)
        elif algo == "argon2" and ARGON2_AVAILABLE:
            return cls._hash_argon2(plain_password)
        else:
            return cls._hash_pbkdf2(plain_password)

    @classmethod
    def _hash_bcrypt(cls, plain_password: str) -> PasswordHashedVO:
        """Hash password using bcrypt."""
        salt = bcrypt.gensalt(rounds=DEFAULT_BCRYPT_ROUNDS)
        hashed = bcrypt.hashpw(plain_password.encode("utf-8"), salt)
        return cls(
            hashed_value=hashed.decode("utf-8"),
            algorithm="bcrypt",
            salt=salt.decode("utf-8"),
            iterations=DEFAULT_BCRYPT_ROUNDS,
        )

    @classmethod
    def _hash_argon2(cls, plain_password: str) -> PasswordHashedVO:
        """Hash password using Argon2."""
        ph = argon2.PasswordHasher(
            time_cost=DEFAULT_ARGON2_TIME_COST,
            memory_cost=DEFAULT_ARGON2_MEMORY_COST,
            parallelism=DEFAULT_ARGON2_PARALLELISM,
        )
        hashed = ph.hash(plain_password)
        return cls(
            hashed_value=hashed,
            algorithm="argon2",
            iterations=DEFAULT_ARGON2_TIME_COST,
        )

    @classmethod
    def _hash_pbkdf2(cls, plain_password: str) -> PasswordHashedVO:
        """Hash password using PBKDF2-SHA256."""
        salt = secrets.token_bytes(DEFAULT_PBKDF2_SALT_LENGTH)
        iterations = DEFAULT_PBKDF2_ITERATIONS
        hash_obj = hashlib.pbkdf2_hmac(
            "sha256",
            plain_password.encode("utf-8"),
            salt,
            iterations,
        )
        # Format: algorithm$iterations$salt$hash
        hashed_value = f"pbkdf2_sha256${iterations}${salt.hex()}${hash_obj.hex()}"
        return cls(
            hashed_value=hashed_value,
            algorithm="pbkdf2_sha256",
            salt=salt.hex(),
            iterations=iterations,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PasswordHashedVO:
        """Reconstruct from dictionary."""
        return cls(
            hashed_value=data["hashed_value"],
            algorithm=data.get("algorithm", "pbkdf2_sha256"),
            salt=data.get("salt"),
            iterations=data.get("iterations", DEFAULT_PBKDF2_ITERATIONS),
            created_at=datetime.fromisoformat(data["created_at"])
            if data.get("created_at")
            else datetime.now(),
        )

    # ==================== VERIFICATION METHODS ====================

    def verify(self, plain_password: str) -> bool:
        """
        Verify plain password against hash.

        Args:
            plain_password: Password in plaintext

        Returns:
            True if password matches, False otherwise
        """
        if not plain_password:
            return False

        try:
            if self.algorithm == "bcrypt" and BCRYPT_AVAILABLE:
                return bcrypt.checkpw(
                    plain_password.encode("utf-8"), self.hashed_value.encode("utf-8")
                )
            elif self.algorithm == "argon2" and ARGON2_AVAILABLE:
                ph = argon2.PasswordHasher()
                try:
                    ph.verify(self.hashed_value, plain_password)
                    return True
                except argon2.exceptions.VerificationError:
                    return False
            elif self.algorithm.startswith("pbkdf2_sha256"):
                return self._verify_pbkdf2(plain_password)
            else:
                # FIX: Hindari kata "password" di log
                logger.warning(f"Unknown hash algorithm: {self.algorithm}")
                return False
        except Exception as e:
            # FIX: Jangan log kata "password" dan jangan tampilkan detail error
            logger.error(f"Verification error: {type(e).__name__}")
            return False

    def _verify_pbkdf2(self, plain_password: str) -> bool:
        """Verify password against PBKDF2 hash."""
        try:
            # Parse format: pbkdf2_sha256$iterations$salt$hash
            parts = self.hashed_value.split("$")
            if len(parts) != 4:
                return False

            iterations = int(parts[1])
            salt = bytes.fromhex(parts[2])
            expected_hash = parts[3]

            computed = hashlib.pbkdf2_hmac(
                "sha256",
                plain_password.encode("utf-8"),
                salt,
                iterations,
            )
            return hmac.compare_digest(computed.hex(), expected_hash)
        except Exception as e:
            # FIX: Jangan log kata "password" dan jangan tampilkan detail error
            logger.error(f"Verification error: {type(e).__name__}")
            return False

    # ==================== PASSWORD STRENGTH METHODS ====================

    @classmethod
    def validate_password_strength(cls, password: str, username: str | None = None) -> None:
        """
        Validate password strength according to policy.

        Args:
            password: Password to validate
            username: Optional username for policy validation

        Raises:
            PasswordError: If password does not meet policy requirements
        """
        cls._policy.validate(password, username)

    @classmethod
    def check_password_strength(cls, password: str, username: str | None = None) -> dict[str, Any]:
        """
        Check password strength and return detailed results.

        Returns:
            Dictionary with strength score and issues
        """
        issues = []
        score = 100

        if len(password) < MIN_PASSWORD_LENGTH:
            issues.append(f"At least {MIN_PASSWORD_LENGTH} characters")
            score -= 20
        elif len(password) > MAX_PASSWORD_LENGTH:
            issues.append(f"No more than {MAX_PASSWORD_LENGTH} characters")
            score -= 10

        if PASSWORD_REQUIRES_UPPERCASE and not any(c.isupper() for c in password):
            issues.append("At least one uppercase letter")
            score -= 15

        if PASSWORD_REQUIRES_LOWERCASE and not any(c.islower() for c in password):
            issues.append("At least one lowercase letter")
            score -= 15

        if PASSWORD_REQUIRES_DIGIT and not any(c.isdigit() for c in password):
            issues.append("At least one digit")
            score -= 15

        if PASSWORD_REQUIRES_SPECIAL and not any(c in SPECIAL_CHARS for c in password):
            issues.append(f"At least one special character: {SPECIAL_CHARS}")
            score -= 15

        if password.lower() in COMMON_PASSWORDS:
            issues.append("Not a common password")
            score -= 20

        if username and username.lower() in password.lower():
            issues.append("Does not contain username")
            score -= 10

        # Additional entropy checks
        unique_chars = len(set(password))
        if unique_chars < 5:
            issues.append("More unique characters")
            score -= 10

        return {
            "score": max(0, score),
            "strength": self._get_strength_label(score),
            "is_valid": score >= 60,
            "issues": issues,
        }

    @staticmethod
    def _get_strength_label(score: int) -> str:
        """Get strength label based on score."""
        if score >= 80:
            return "strong"
        elif score >= 60:
            return "medium"
        elif score >= 40:
            return "weak"
        else:
            return "very_weak"

    # ==================== HASH MANAGEMENT METHODS ====================

    def needs_rehash(self) -> bool:
        """
        Check if hash needs to be upgraded to newer algorithm.

        Returns:
            True if hash should be rehashed with stronger parameters
        """
        if self.algorithm == "bcrypt":
            # Check if rounds are sufficient (at least 12)
            try:
                # Extract rounds from bcrypt hash
                # Bcrypt format: $2b$12$...
                if self.hashed_value.startswith("$2b$"):
                    rounds = int(self.hashed_value.split("$")[2])
                    return rounds < DEFAULT_BCRYPT_ROUNDS
            except Exception:
                pass
            return False
        elif self.algorithm == "argon2":
            return False
        elif self.algorithm.startswith("pbkdf2_sha256"):
            return self.iterations < DEFAULT_PBKDF2_ITERATIONS
        return True

    def upgrade_hash(self, plain_password: str) -> PasswordHashedVO:
        """
        Upgrade hash to current algorithm and parameters.

        Args:
            plain_password: Original plain password

        Returns:
            New PasswordHashedVO with upgraded hash
        """
        return self.create_from_plain(plain_password)

    # ==================== SERIALIZATION ====================

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "hashed_value": self.hashed_value,
            "algorithm": self.algorithm,
            "salt": self.salt,
            "iterations": self.iterations,
            "created_at": self.created_at.isoformat(),
        }

    def to_db_record(self) -> dict[str, Any]:
        """Convert to database-friendly format."""
        return {
            "password_hash": self.hashed_value,
            "password_algorithm": self.algorithm,
            "password_salt": self.salt,
            "password_iterations": self.iterations,
            "password_created_at": self.created_at,
        }

    # ==================== DUNDER METHODS ====================

    def __str__(self) -> str:
        return f"PasswordHashedVO(algorithm={self.algorithm}, hash={self.hashed_value[:20]}...)"

    def __repr__(self) -> str:
        return f"PasswordHashedVO(algorithm={self.algorithm}, hash_length={len(self.hashed_value)})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PasswordHashedVO):
            return False
        return self.hashed_value == other.hashed_value

    def __hash__(self) -> int:
        return hash(self.hashed_value)


# ============================================================================
# Helper Functions
# ============================================================================


def generate_random_password(length: int = 12, include_special: bool = True) -> str:
    """
    Generate a random secure password.

    Args:
        length: Password length
        include_special: Whether to include special characters

    Returns:
        Random password string
    """
    chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    if include_special:
        chars += SPECIAL_CHARS

    return "".join(secrets.choice(chars) for _ in range(length))


def hash_password(plain_password: str, username: str | None = None) -> PasswordHashedVO:
    """Convenience function to hash a password."""
    return PasswordHashedVO.create_from_plain(plain_password, username)


def verify_password(plain_password: str, hashed_password: PasswordHashedVO) -> bool:
    """Convenience function to verify a password."""
    return hashed_password.verify(plain_password)


def is_password_strong(password: str) -> bool:
    """Quick check if password is strong enough."""
    try:
        PasswordHashedVO.validate_password_strength(password)
        return True
    except PasswordError:
        return False


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "BCRYPT_AVAILABLE",
    "MAX_PASSWORD_LENGTH",
    "MIN_PASSWORD_LENGTH",
    "PasswordCommonError",
    "PasswordError",
    "PasswordHashError",
    "PasswordHashedVO",
    "PasswordMissingDigitError",
    "PasswordMissingLowercaseError",
    "PasswordMissingSpecialError",
    "PasswordMissingUppercaseError",
    "PasswordPolicy",
    "PasswordTooLongError",
    "PasswordTooShortError",
    "PasswordVerifyError",
    "generate_random_password",
    "hash_password",
    "is_password_strong",
    "verify_password",
]
