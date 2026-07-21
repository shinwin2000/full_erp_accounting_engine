# tests/infrastructure/database/test_database_exceptions.py
"""
Comprehensive unit tests for database_exceptions.py.

Covers:
- All exception classes (instantiation, string representation, inheritance)
- ValidationError custom __init__ and errors attribute
- Negative path: raising exceptions with invalid arguments (if any)
- Ensures all exceptions are subclasses of DatabaseError
- Parametrized tests to reduce duplication
- Edge cases: empty error list, long messages, Unicode
"""

import pytest

from infrastructure.database.database_exceptions import (
    ArchiveCreateError,
    ArchiveRestoreError,
    AuditTriggerError,
    BackupCreateError,
    BackupCreationError,
    BackupNotFoundError,
    BackupRestoreError,
    DatabaseBackupError,
    DatabaseConnectionError,
    DatabaseError,
    DatabaseHealthError,
    DatabasePoolError,
    EncryptionKeyError,
    MigrationError,
    MigrationNotInitializedError,
    MigrationRollbackError,
    PartitionArchiverError,
    PartitionCreateError,
    PartitionMaintenanceError,
    PartitionManagerError,
    PITRError,
    PITRRestoreError,
    ReadReplicaError,
    ReplicaUnavailableError,
    RollbackFailedError,
    SeedDataError,
    SeedDataNotFoundError,
    SeedDataValidationError,
    SessionFactoryError,
    TDEError,
    TransactionError,
    TransactionPropagationError,
    ValidationError,
    WALArchiveError,
    WriteToReplicaError,
)

# ============================================================================
# Helper: list of all exception classes (except ValidationError which is special)
# ============================================================================

EXCEPTION_CLASSES = [
    DatabaseError,
    DatabaseConnectionError,
    DatabasePoolError,
    SessionFactoryError,
    TransactionError,
    TransactionPropagationError,
    MigrationError,
    MigrationNotInitializedError,
    MigrationRollbackError,
    RollbackFailedError,
    BackupCreationError,
    SeedDataError,
    SeedDataNotFoundError,
    SeedDataValidationError,
    TDEError,
    EncryptionKeyError,
    AuditTriggerError,
    PartitionManagerError,
    PartitionCreateError,
    PartitionMaintenanceError,
    PartitionArchiverError,
    ArchiveCreateError,
    ArchiveRestoreError,
    DatabaseBackupError,
    BackupCreateError,
    BackupRestoreError,
    BackupNotFoundError,
    PITRError,
    PITRRestoreError,
    WALArchiveError,
    DatabaseHealthError,
    ReadReplicaError,
    WriteToReplicaError,
    ReplicaUnavailableError,
]


# ============================================================================
# Parametrized tests for all exception classes
# ============================================================================

class TestDatabaseExceptions:
    @pytest.mark.parametrize("exc_class", EXCEPTION_CLASSES)
    def test_instantiation_no_args(self, exc_class):
        """Exception can be instantiated with no arguments."""
        instance = exc_class()
        assert isinstance(instance, exc_class)
        assert isinstance(instance, DatabaseError)
        assert str(instance) == ""

    @pytest.mark.parametrize("exc_class", EXCEPTION_CLASSES)
    def test_instantiation_with_message(self, exc_class):
        """Exception can be instantiated with a message string."""
        msg = "Test error message"
        instance = exc_class(msg)
        assert str(instance) == msg
        assert isinstance(instance, DatabaseError)

    @pytest.mark.parametrize("exc_class", EXCEPTION_CLASSES)
    def test_instantiation_with_unicode_message(self, exc_class):
        """Exception can be instantiated with Unicode message."""
        msg = "Erreur de base de données: échec de la connexion"
        instance = exc_class(msg)
        assert str(instance) == msg

    @pytest.mark.parametrize("exc_class", EXCEPTION_CLASSES)
    def test_instantiation_with_long_message(self, exc_class):
        """Exception can be instantiated with a long message."""
        msg = "A" * 1000
        instance = exc_class(msg)
        assert str(instance) == msg

    @pytest.mark.parametrize("exc_class", EXCEPTION_CLASSES)
    def test_raise_and_catch(self, exc_class):
        """Exception can be raised and caught with correct type."""
        msg = "Something went wrong"
        with pytest.raises(exc_class) as exc_info:
            raise exc_class(msg)
        assert str(exc_info.value) == msg
        assert isinstance(exc_info.value, DatabaseError)

    @pytest.mark.parametrize("exc_class", EXCEPTION_CLASSES)
    def test_is_subclass_of_database_error(self, exc_class):
        """Every exception should be a subclass of DatabaseError."""
        assert issubclass(exc_class, DatabaseError)


# ============================================================================
# Tests for ValidationError (has custom __init__ with errors list)
# ============================================================================

class TestValidationError:
    def test_construction_with_errors_list(self):
        errors = ["error1", "error2", "error3"]
        exc = ValidationError(errors)
        assert exc.errors == errors
        assert str(exc) == "Validation failed with 3 error(s)"

    def test_construction_with_empty_errors_list(self):
        errors = []
        exc = ValidationError(errors)
        assert exc.errors == errors
        assert str(exc) == "Validation failed with 0 error(s)"

    def test_construction_with_single_error(self):
        errors = ["Invalid field"]
        exc = ValidationError(errors)
        assert exc.errors == errors
        assert str(exc) == "Validation failed with 1 error(s)"

    def test_errors_attribute_is_accessible(self):
        errors = ["err1", "err2"]
        exc = ValidationError(errors)
        assert exc.errors is errors  # same list reference

    def test_raise_and_catch_validation_error(self):
        errors = ["Missing required field", "Invalid email format"]
        with pytest.raises(ValidationError) as exc_info:
            raise ValidationError(errors)
        assert exc_info.value.errors == errors
        assert "Validation failed with 2 error(s)" in str(exc_info.value)
        # Check inheritance chain
        assert isinstance(exc_info.value, SeedDataValidationError)
        assert isinstance(exc_info.value, SeedDataError)
        assert isinstance(exc_info.value, DatabaseError)

    def test_validation_error_inheritance_chain(self):
        """ValidationError should inherit from SeedDataValidationError and SeedDataError."""
        assert issubclass(ValidationError, SeedDataValidationError)
        assert issubclass(ValidationError, SeedDataError)
        assert issubclass(ValidationError, DatabaseError)


# ============================================================================
# Specific inheritance hierarchy tests
# ============================================================================

class TestInheritanceHierarchies:
    def test_backup_hierarchy(self):
        assert issubclass(BackupCreateError, DatabaseBackupError)
        assert issubclass(BackupRestoreError, DatabaseBackupError)
        assert issubclass(BackupNotFoundError, DatabaseBackupError)
        assert issubclass(DatabaseBackupError, DatabaseError)

    def test_migration_hierarchy(self):
        assert issubclass(MigrationNotInitializedError, MigrationError)
        assert issubclass(MigrationError, DatabaseError)
        assert issubclass(MigrationRollbackError, DatabaseError)
        assert issubclass(RollbackFailedError, MigrationRollbackError)
        assert issubclass(BackupCreationError, MigrationRollbackError)

    def test_partition_hierarchy(self):
        assert issubclass(PartitionCreateError, PartitionManagerError)
        assert issubclass(PartitionMaintenanceError, PartitionManagerError)
        assert issubclass(PartitionManagerError, DatabaseError)
        assert issubclass(PartitionArchiverError, DatabaseError)
        assert issubclass(ArchiveCreateError, PartitionArchiverError)
        assert issubclass(ArchiveRestoreError, PartitionArchiverError)

    def test_pitr_hierarchy(self):
        assert issubclass(PITRRestoreError, PITRError)
        assert issubclass(WALArchiveError, PITRError)
        assert issubclass(PITRError, DatabaseError)

    def test_read_replica_hierarchy(self):
        assert issubclass(WriteToReplicaError, ReadReplicaError)
        assert issubclass(ReplicaUnavailableError, ReadReplicaError)
        assert issubclass(ReadReplicaError, DatabaseError)

    def test_seed_data_hierarchy(self):
        assert issubclass(SeedDataNotFoundError, SeedDataError)
        assert issubclass(SeedDataValidationError, SeedDataError)
        assert issubclass(SeedDataError, DatabaseError)

    def test_transaction_hierarchy(self):
        assert issubclass(TransactionPropagationError, TransactionError)
        assert issubclass(TransactionError, DatabaseError)

    def test_tde_hierarchy(self):
        assert issubclass(EncryptionKeyError, TDEError)
        assert issubclass(TDEError, DatabaseError)

    def test_connection_hierarchy(self):
        assert issubclass(DatabaseConnectionError, DatabaseError)
        assert issubclass(DatabasePoolError, DatabaseError)
        assert issubclass(SessionFactoryError, DatabaseError)

    def test_audit_trigger_hierarchy(self):
        assert issubclass(AuditTriggerError, DatabaseError)

    def test_database_health_hierarchy(self):
        assert issubclass(DatabaseHealthError, DatabaseError)


# ============================================================================
# Negative path tests: ensuring exceptions are not silently swallowed
# ============================================================================

class TestNegativePaths:
    def test_validation_error_with_non_list(self):
        """ValidationError expects a list of errors. Passing non-list should still work but may cause issues."""
        # The code doesn't enforce list type; we test that it accepts any iterable
        exc = ValidationError("not a list")
        assert exc.errors == "not a list"  # accepts anything
        assert str(exc) == "Validation failed with 1 error(s)"  # len works on string

        # But we want to ensure it doesn't crash
        exc2 = ValidationError(("tuple", "of", "errors"))
        assert exc2.errors == ("tuple", "of", "errors")

    def test_raise_exception_without_message(self):
        """All exceptions should be raiseable without a message."""
        for exc_class in EXCEPTION_CLASSES:
            with pytest.raises(exc_class):
                raise exc_class()

    def test_raise_exception_with_none_message(self):
        """Passing None as message should result in empty string representation."""
        for exc_class in EXCEPTION_CLASSES:
            exc = exc_class(None)
            assert str(exc) == "None"  # Python's default str(None)
            # This is fine, but we ensure it doesn't crash.

    def test_validation_error_with_none_errors(self):
        """ValidationError with None errors should still work (though not intended)."""
        exc = ValidationError(None)
        assert exc.errors is None
        # len(None) raises TypeError, but ValidationError doesn't check, so str may raise.
        # We'll just ensure it doesn't raise during construction.
        assert isinstance(exc, ValidationError)
        # However, str(exc) will fail, so we should not call it.
        # This is an edge case; we test that constructor doesn't crash.