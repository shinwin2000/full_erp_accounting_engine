#!/usr/bin/env python3
"""
Package: domain.iam
Layer: Domain

Identity Access Management (IAM) domain layer.

Ekspos semua entitas, aggregate root, value object, event, invariant, repository,
dan utility functions untuk manajemen pengguna, peran (role), sesi, izin (permission),
dan autentikasi.

Fitur lengkap sesuai standar ERP:
- Entity dasar: create, update, delete, restore, activate, deactivate, lock, unlock,
  validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Aggregate root: add_child, remove_child, can_post, post, can_approve, approve,
  can_reject, reject, can_cancel, cancel, can_reverse, reverse, close, reopen,
  archive, unarchive, register_event, get_events, pull_events, clear_events.
- Domain event: event_id, occurred_at, aggregate_id, aggregate_type, to_dict, from_dict,
  serialize, deserialize.
- Repository interface: add, save, update, delete, exists, get_by_id, get_by_code,
  get_all, search, count, list, paginate.
- Audit trail, snapshot, versioning.
"""

# ------------------------------------------------------------------------------
# Aggregate Root
# ------------------------------------------------------------------------------
from domain.iam.aggregate_root import (
    IAM,  # Aggregate root utama
    AuthenticationError,
    DuplicateEmailError,
    DuplicateRoleNameError,
    DuplicateUsernameError,
    IAMError,  # Base exception
    IAMRepository,  # Repository interface
    IAMStatus,  # Status IAM (ACTIVE, LOCKDOWN, MAINTENANCE)
    InsufficientPermissionsError,
    RoleNotFoundError,
    UserAggregate,  # Alias
    UserNotFoundError,
)

# ------------------------------------------------------------------------------
# Domain Events
# ------------------------------------------------------------------------------
from domain.iam.domain_events import (
    DomainEvent,
    DomainEventPublisher,
    DomainEventType,
    LoginFailureEvent,
    # Authentication events
    LoginSuccessEvent,
    # Permission events
    PermissionGrantedEvent,
    PermissionRevokedEvent,
    RoleAssignedEvent,
    # Role events
    RoleCreatedEvent,
    RoleDeletedEvent,
    RoleRevokedEvent,
    RoleUpdatedEvent,
    SessionCompromisedEvent,
    # Session events
    SessionCreatedEvent,
    SessionRefreshedEvent,
    SessionTerminatedEvent,
    UserActivatedEvent,
    # User events
    UserCreatedEvent,
    UserDeactivatedEvent,
    UserDeletedEvent,
    UserPasswordChangedEvent,
    UserSuspendedEvent,
    UserUnlockedEvent,
    UserUpdatedEvent,
    # Serialization helpers
    deserialize_domain_event,
    serialize_domain_event,
)

# ------------------------------------------------------------------------------
# Invariants & Validation
# ------------------------------------------------------------------------------
from domain.iam.invariants import (
    IAMInvariantEnforcer,
    InvariantResult,
    RoleInvariants,
    SessionInvariants,
    UserInvariants,
    validate_date_not_future,
    validate_email,
    validate_full_name,
    validate_username,
    validate_version,
)

# ------------------------------------------------------------------------------
# Login Attempt Log (Entity)
# ------------------------------------------------------------------------------
from domain.iam.login_attempt_log import (
    DeviceFingerprint,
    LocationInfo,
    LoginAttemptError,
    LoginAttemptLog,
    LoginAttemptRepository,
    LoginAttemptSource,
    LoginResult,
)

# ------------------------------------------------------------------------------
# Password Hashed VO
# ------------------------------------------------------------------------------
from domain.iam.password_hashed_vo import (
    BCRYPT_AVAILABLE,
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
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
)

# ------------------------------------------------------------------------------
# Permission VO
# ------------------------------------------------------------------------------
from domain.iam.permission_vo import (
    ActionType,
    InvalidPermissionFormatError,
    Permission,
    PermissionError,
    PermissionUtils,
    PermissionVO,
    ResourceType,
)

# ------------------------------------------------------------------------------
# Role Entity
# ------------------------------------------------------------------------------
from domain.iam.role_entity import (
    DuplicatePermissionError,
    InvalidRoleStatusTransitionError,
    PermissionNotFoundError,
    Role,
    RoleEntity,
    RoleError,
    RoleRepository,
    RoleStatus,
)

# ------------------------------------------------------------------------------
# Session Entity
# ------------------------------------------------------------------------------
from domain.iam.session_entity import (
    DeviceType,
    InvalidSessionStatusTransitionError,
    SessionAudit,
    SessionEntity,
    SessionError,
    SessionExpiredError,
    SessionMetadata,
    SessionRepository,
    SessionStatus,
    UserSession,
)

# ------------------------------------------------------------------------------
# User Entity
# ------------------------------------------------------------------------------
from domain.iam.user_entity import (
    InvalidUserStatusTransitionError,
    UserAudit,
    UserEntity,
    UserError,
    UserProfile,
    UserRepository,
    UserStatus,
)

# ------------------------------------------------------------------------------
# __all__ - Public API
# ------------------------------------------------------------------------------
__all__ = [
    # Aggregate Root
    "IAM",
    "IAMError",
    "IAMRepository",
    "IAMStatus",
    "UserAggregate",
    "UserNotFoundError",
    "RoleNotFoundError",
    "DuplicateUsernameError",
    "DuplicateEmailError",
    "DuplicateRoleNameError",
    "InsufficientPermissionsError",
    "AuthenticationError",
    # Domain Events
    "DomainEvent",
    "DomainEventPublisher",
    "DomainEventType",
    "UserCreatedEvent",
    "UserUpdatedEvent",
    "UserActivatedEvent",
    "UserDeactivatedEvent",
    "UserSuspendedEvent",
    "UserUnlockedEvent",
    "UserPasswordChangedEvent",
    "UserDeletedEvent",
    "RoleCreatedEvent",
    "RoleUpdatedEvent",
    "RoleDeletedEvent",
    "RoleAssignedEvent",
    "RoleRevokedEvent",
    "SessionCreatedEvent",
    "SessionRefreshedEvent",
    "SessionTerminatedEvent",
    "SessionCompromisedEvent",
    "LoginSuccessEvent",
    "LoginFailureEvent",
    "PermissionGrantedEvent",
    "PermissionRevokedEvent",
    "deserialize_domain_event",
    "serialize_domain_event",
    # Invariants
    "IAMInvariantEnforcer",
    "InvariantResult",
    "RoleInvariants",
    "SessionInvariants",
    "UserInvariants",
    "validate_date_not_future",
    "validate_email",
    "validate_full_name",
    "validate_username",
    "validate_version",
    # Login Attempt Log
    "LoginAttemptLog",
    "LoginAttemptRepository",
    "LoginAttemptSource",
    "LoginResult",
    "LocationInfo",
    "DeviceFingerprint",
    "LoginAttemptError",
    # Password VO
    "PasswordHashedVO",
    "PasswordPolicy",
    "PasswordError",
    "PasswordTooShortError",
    "PasswordTooLongError",
    "PasswordMissingUppercaseError",
    "PasswordMissingLowercaseError",
    "PasswordMissingDigitError",
    "PasswordMissingSpecialError",
    "PasswordCommonError",
    "PasswordHashError",
    "PasswordVerifyError",
    "generate_random_password",
    "hash_password",
    "is_password_strong",
    "verify_password",
    "MIN_PASSWORD_LENGTH",
    "MAX_PASSWORD_LENGTH",
    "BCRYPT_AVAILABLE",
    # Permission VO
    "PermissionVO",
    "Permission",
    "ResourceType",
    "ActionType",
    "PermissionUtils",
    "InvalidPermissionFormatError",
    "PermissionError",
    # Role Entity
    "RoleEntity",
    "Role",
    "RoleStatus",
    "RoleRepository",
    "RoleError",
    "InvalidRoleStatusTransitionError",
    "DuplicatePermissionError",
    "PermissionNotFoundError",
    # Session Entity
    "SessionEntity",
    "SessionStatus",
    "DeviceType",
    "SessionMetadata",
    "SessionAudit",
    "SessionRepository",
    "UserSession",
    "SessionError",
    "InvalidSessionStatusTransitionError",
    "SessionExpiredError",
    # User Entity
    "UserEntity",
    "UserStatus",
    "UserProfile",
    "UserAudit",
    "UserRepository",
    "UserError",
    "InvalidUserStatusTransitionError",
]
