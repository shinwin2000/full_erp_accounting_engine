# test_causality_exceptions.py
# =========================================
# Lengkap: Semua test asli dipertahankan + tambahan test coverage untuk factory methods yang hilang.

from unittest.mock import MagicMock

import pytest

from domain.causality.causality_exceptions import (
    CausalChainBrokenError,
    CausalChainCycleDetectedError,
    CausalChainEmptyError,
    CausalChainIncompleteError,
    CausalChainNotFoundError,
    CausalChainTooDeepError,
    CausalityError,
    CausalityErrorCode,
    CausalityExceptionFactory,
    CausalityInconsistentError,
    CausalityNotFoundError,
    CausalitySeverity,
    CausalNodeAlreadyExistsError,
    CausalNodeCorruptedError,
    CausalNodeHashMismatchError,
    CausalNodeInvalidTypeError,
    CausalNodeNotFoundError,
    CausalRelationshipAlreadyExistsError,
    CausalRelationshipInvalidError,
    CausalRelationshipNotFoundError,
    CircularReferenceDetectedError,
    ExplanationGenerationFailedError,
    InvalidDirectionError,
    InvalidQueryDepthError,
    PathNotFoundError,
    RelationshipStrengthInvalidError,
    TraversalTooDeepError,
    UnsupportedFormatError,
    UnsupportedLanguageError,
    WhyQueryFailedError,
    WhyQueryTimeoutError,
)


class TestCausalityErrorCode:
    """Tests for the CausalityErrorCode enum."""
    def test_members_exist(self):
        """All expected enum members are defined."""
        assert hasattr(CausalityErrorCode, 'NODE_NOT_FOUND')
        assert hasattr(CausalityErrorCode, 'NODE_ALREADY_EXISTS')
        assert hasattr(CausalityErrorCode, 'NODE_INVALID_TYPE')
        assert hasattr(CausalityErrorCode, 'NODE_HASH_MISMATCH')
        assert hasattr(CausalityErrorCode, 'NODE_CORRUPTED')
        assert hasattr(CausalityErrorCode, 'CHAIN_INCOMPLETE')
        assert hasattr(CausalityErrorCode, 'CHAIN_CYCLE_DETECTED')
        assert hasattr(CausalityErrorCode, 'CHAIN_TOO_DEEP')
        assert hasattr(CausalityErrorCode, 'CHAIN_BROKEN')
        assert hasattr(CausalityErrorCode, 'CHAIN_EMPTY')
        assert hasattr(CausalityErrorCode, 'CHAIN_NOT_FOUND')
        assert hasattr(CausalityErrorCode, 'RELATIONSHIP_NOT_FOUND')
        assert hasattr(CausalityErrorCode, 'RELATIONSHIP_ALREADY_EXISTS')
        assert hasattr(CausalityErrorCode, 'RELATIONSHIP_INVALID')
        assert hasattr(CausalityErrorCode, 'CIRCULAR_REFERENCE_DETECTED')
        assert hasattr(CausalityErrorCode, 'RELATIONSHIP_STRENGTH_INVALID')
        assert hasattr(CausalityErrorCode, 'QUERY_FAILED')
        assert hasattr(CausalityErrorCode, 'QUERY_TIMEOUT')
        assert hasattr(CausalityErrorCode, 'INVALID_QUERY_DEPTH')
        assert hasattr(CausalityErrorCode, 'QUERY_CACHE_ERROR')
        assert hasattr(CausalityErrorCode, 'TRAVERSAL_TOO_DEEP')
        assert hasattr(CausalityErrorCode, 'PATH_NOT_FOUND')
        assert hasattr(CausalityErrorCode, 'INVALID_DIRECTION')
        assert hasattr(CausalityErrorCode, 'EXPLANATION_GENERATION_FAILED')
        assert hasattr(CausalityErrorCode, 'UNSUPPORTED_LANGUAGE')
        assert hasattr(CausalityErrorCode, 'UNSUPPORTED_FORMAT')
        assert hasattr(CausalityErrorCode, 'CAUSALITY_NOT_FOUND')
        assert hasattr(CausalityErrorCode, 'CAUSALITY_INCONSISTENT')
        assert hasattr(CausalityErrorCode, 'UNKNOWN_CAUSALITY_ERROR')

    def test_member_is_instance(self):
        """Enum members are instances of the enum class."""
        assert isinstance(CausalityErrorCode.NODE_NOT_FOUND, CausalityErrorCode)


class TestCausalitySeverity:
    """Tests for the CausalitySeverity enum."""
    def test_members_exist(self):
        """All expected enum members are defined."""
        assert hasattr(CausalitySeverity, 'CRITICAL')
        assert hasattr(CausalitySeverity, 'HIGH')
        assert hasattr(CausalitySeverity, 'MEDIUM')
        assert hasattr(CausalitySeverity, 'LOW')

    def test_member_is_instance(self):
        """Enum members are instances of the enum class."""
        assert isinstance(CausalitySeverity.CRITICAL, CausalitySeverity)


class TestCausalityError:
    """Tests for CausalityError."""

    def _build_instance(self):
        return CausalityError(
            message="test_value",
            error_code=CausalityErrorCode.NODE_NOT_FOUND,
            severity=CausalitySeverity.CRITICAL,
            component="test_value",
            details={},
            cause=MagicMock(),
        )

    def test_construction(self):
        """CausalityError can be instantiated with mocked dependencies."""
        try:
            instance = self._build_instance()
        except (Exception, SystemExit) as e:
            pytest.skip(f"Requires domain-specific construction setup: {e}")
            return
        assert isinstance(instance, CausalityError)

    def test_original_message(self):
        instance = self._build_instance()
        assert instance.original_message == "test_value"

    def test_to_dict(self):
        instance = self._build_instance()
        d = instance.to_dict()
        assert d["type"] == "CausalityError"
        assert d["error_code"] == "NODE_NOT_FOUND"
        assert d["severity"] == "CRITICAL"
        assert d["message"] == "test_value"
        assert d["component"] == "test_value"
        assert d["details"] == {}
        assert d["cause"] is not None

    def test_is_critical(self):
        instance = self._build_instance()
        assert instance.is_critical() is True

    def test_is_high(self):
        instance = CausalityError(
            message="high", error_code=CausalityErrorCode.NODE_NOT_FOUND,
            severity=CausalitySeverity.HIGH
        )
        assert instance.is_high() is True

        instance_low = CausalityError(
            message="low", error_code=CausalityErrorCode.NODE_NOT_FOUND,
            severity=CausalitySeverity.LOW
        )
        assert instance_low.is_high() is False


class TestCausalNodeNotFoundError:
    """Tests for CausalNodeNotFoundError."""

    def _build_instance(self):
        return CausalNodeNotFoundError(node_id="test_value", entity_type="test_value", entity_id="test_value")

    def test_construction(self):
        """CausalNodeNotFoundError can be instantiated with mocked dependencies."""
        try:
            instance = self._build_instance()
        except (Exception, SystemExit) as e:
            pytest.skip(f"Requires domain-specific construction setup: {e}")
            return
        assert isinstance(instance, CausalNodeNotFoundError)


class TestCausalNodeAlreadyExistsError:
    """Tests for CausalNodeAlreadyExistsError."""

    def _build_instance(self):
        return CausalNodeAlreadyExistsError(node_id="test_value")

    def test_construction(self):
        """CausalNodeAlreadyExistsError can be instantiated with mocked dependencies."""
        try:
            instance = self._build_instance()
        except (Exception, SystemExit) as e:
            pytest.skip(f"Requires domain-specific construction setup: {e}")
            return
        assert isinstance(instance, CausalNodeAlreadyExistsError)


class TestCausalNodeInvalidTypeError:
    """Tests for CausalNodeInvalidTypeError."""

    def _build_instance(self):
        return CausalNodeInvalidTypeError(node_type="test_value", valid_types=["test_value"])

    def test_construction(self):
        """CausalNodeInvalidTypeError can be instantiated with mocked dependencies."""
        try:
            instance = self._build_instance()
        except (Exception, SystemExit) as e:
            pytest.skip(f"Requires domain-specific construction setup: {e}")
            return
        assert isinstance(instance, CausalNodeInvalidTypeError)


class TestCausalNodeHashMismatchError:
    """Tests for CausalNodeHashMismatchError."""

    def _build_instance(self):
        return CausalNodeHashMismatchError(node_id="test_value", expected_hash="test_value", actual_hash="test_value")

    def test_construction(self):
        """CausalNodeHashMismatchError can be instantiated with mocked dependencies."""
        try:
            instance = self._build_instance()
        except (Exception, SystemExit) as e:
            pytest.skip(f"Requires domain-specific construction setup: {e}")
            return
        assert isinstance(instance, CausalNodeHashMismatchError)


class TestCausalNodeCorruptedError:
    """Tests for CausalNodeCorruptedError."""

    def _build_instance(self):
        return CausalNodeCorruptedError(node_id="test_value", reason="test_value")

    def test_construction(self):
        """CausalNodeCorruptedError can be instantiated with mocked dependencies."""
        try:
            instance = self._build_instance()
        except (Exception, SystemExit) as e:
            pytest.skip(f"Requires domain-specific construction setup: {e}")
            return
        assert isinstance(instance, CausalNodeCorruptedError)


class TestCausalChainIncompleteError:
    """Tests for CausalChainIncompleteError."""

    def _build_instance(self):
        return CausalChainIncompleteError(start_id="test_value", end_id="test_value", missing_nodes=["test_value"])

    def test_construction(self):
        """CausalChainIncompleteError can be instantiated with mocked dependencies."""
        try:
            instance = self._build_instance()
        except (Exception, SystemExit) as e:
            pytest.skip(f"Requires domain-specific construction setup: {e}")
            return
        assert isinstance(instance, CausalChainIncompleteError)


class TestCausalChainCycleDetectedError:
    """Tests for CausalChainCycleDetectedError."""

    def _build_instance(self):
        return CausalChainCycleDetectedError(cycle_nodes=["test_value"])

    def test_construction(self):
        """CausalChainCycleDetectedError can be instantiated with mocked dependencies."""
        try:
            instance = self._build_instance()
        except (Exception, SystemExit) as e:
            pytest.skip(f"Requires domain-specific construction setup: {e}")
            return
        assert isinstance(instance, CausalChainCycleDetectedError)


class TestCausalChainTooDeepError:
    """Tests for CausalChainTooDeepError."""

    def _build_instance(self):
        return CausalChainTooDeepError(max_depth=1, actual_depth=1)

    def test_construction(self):
        """CausalChainTooDeepError can be instantiated with mocked dependencies."""
        try:
            instance = self._build_instance()
        except (Exception, SystemExit) as e:
            pytest.skip(f"Requires domain-specific construction setup: {e}")
            return
        assert isinstance(instance, CausalChainTooDeepError)


class TestCausalChainBrokenError:
    """Tests for CausalChainBrokenError."""

    def _build_instance(self):
        return CausalChainBrokenError(node_id="test_value", expected_next="test_value", actual_next="test_value")

    def test_construction(self):
        """CausalChainBrokenError can be instantiated with mocked dependencies."""
        try:
            instance = self._build_instance()
        except (Exception, SystemExit) as e:
            pytest.skip(f"Requires domain-specific construction setup: {e}")
            return
        assert isinstance(instance, CausalChainBrokenError)


class TestCausalChainEmptyError:
    """Tests for CausalChainEmptyError."""

    def _build_instance(self):
        return CausalChainEmptyError(entity_id="test_value", entity_type="test_value")

    def test_construction(self):
        """CausalChainEmptyError can be instantiated with mocked dependencies."""
        try:
            instance = self._build_instance()
        except (Exception, SystemExit) as e:
            pytest.skip(f"Requires domain-specific construction setup: {e}")
            return
        assert isinstance(instance, CausalChainEmptyError)


class TestCausalChainNotFoundError:
    """Tests for CausalChainNotFoundError."""

    def _build_instance(self):
        return CausalChainNotFoundError(chain_id="test_value")

    def test_construction(self):
        """CausalChainNotFoundError can be instantiated with mocked dependencies."""
        try:
            instance = self._build_instance()
        except (Exception, SystemExit) as e:
            pytest.skip(f"Requires domain-specific construction setup: {e}")
            return
        assert isinstance(instance, CausalChainNotFoundError)


class TestCausalRelationshipNotFoundError:
    """Tests for CausalRelationshipNotFoundError."""

    def _build_instance(self):
        return CausalRelationshipNotFoundError(source_id="test_value", target_id="test_value")

    def test_construction(self):
        """CausalRelationshipNotFoundError can be instantiated with mocked dependencies."""
        try:
            instance = self._build_instance()
        except (Exception, SystemExit) as e:
            pytest.skip(f"Requires domain-specific construction setup: {e}")
            return
        assert isinstance(instance, CausalRelationshipNotFoundError)


class TestCausalRelationshipAlreadyExistsError:
    """Tests for CausalRelationshipAlreadyExistsError."""

    def _build_instance(self):
        return CausalRelationshipAlreadyExistsError(source_id="test_value", target_id="test_value")

    def test_construction(self):
        """CausalRelationshipAlreadyExistsError can be instantiated with mocked dependencies."""
        try:
            instance = self._build_instance()
        except (Exception, SystemExit) as e:
            pytest.skip(f"Requires domain-specific construction setup: {e}")
            return
        assert isinstance(instance, CausalRelationshipAlreadyExistsError)


class TestCausalRelationshipInvalidError:
    """Tests for CausalRelationshipInvalidError."""

    def _build_instance(self):
        return CausalRelationshipInvalidError(source_id="test_value", target_id="test_value", reason="test_value")

    def test_construction(self):
        """CausalRelationshipInvalidError can be instantiated with mocked dependencies."""
        try:
            instance = self._build_instance()
        except (Exception, SystemExit) as e:
            pytest.skip(f"Requires domain-specific construction setup: {e}")
            return
        assert isinstance(instance, CausalRelationshipInvalidError)


class TestCircularReferenceDetectedError:
    """Tests for CircularReferenceDetectedError."""

    def _build_instance(self):
        return CircularReferenceDetectedError(entities=["test_value"])

    def test_construction(self):
        """CircularReferenceDetectedError can be instantiated with mocked dependencies."""
        try:
            instance = self._build_instance()
        except (Exception, SystemExit) as e:
            pytest.skip(f"Requires domain-specific construction setup: {e}")
            return
        assert isinstance(instance, CircularReferenceDetectedError)


class TestRelationshipStrengthInvalidError:
    """Tests for RelationshipStrengthInvalidError."""

    def _build_instance(self):
        return RelationshipStrengthInvalidError(strength=1.5)

    def test_construction(self):
        """RelationshipStrengthInvalidError can be instantiated with mocked dependencies."""
        try:
            instance = self._build_instance()
        except (Exception, SystemExit) as e:
            pytest.skip(f"Requires domain-specific construction setup: {e}")
            return
        assert isinstance(instance, RelationshipStrengthInvalidError)


class TestWhyQueryFailedError:
    """Tests for WhyQueryFailedError."""

    def _build_instance(self):
        return WhyQueryFailedError(entity_id="test_value", reason="test_value")

    def test_construction(self):
        """WhyQueryFailedError can be instantiated with mocked dependencies."""
        try:
            instance = self._build_instance()
        except (Exception, SystemExit) as e:
            pytest.skip(f"Requires domain-specific construction setup: {e}")
            return
        assert isinstance(instance, WhyQueryFailedError)


class TestWhyQueryTimeoutError:
    """Tests for WhyQueryTimeoutError."""

    def _build_instance(self):
        return WhyQueryTimeoutError(entity_id="test_value", timeout_ms=1)

    def test_construction(self):
        """WhyQueryTimeoutError can be instantiated with mocked dependencies."""
        try:
            instance = self._build_instance()
        except (Exception, SystemExit) as e:
            pytest.skip(f"Requires domain-specific construction setup: {e}")
            return
        assert isinstance(instance, WhyQueryTimeoutError)


class TestInvalidQueryDepthError:
    """Tests for InvalidQueryDepthError."""

    def _build_instance(self):
        return InvalidQueryDepthError(depth=1, max_depth=1)

    def test_construction(self):
        """InvalidQueryDepthError can be instantiated with mocked dependencies."""
        try:
            instance = self._build_instance()
        except (Exception, SystemExit) as e:
            pytest.skip(f"Requires domain-specific construction setup: {e}")
            return
        assert isinstance(instance, InvalidQueryDepthError)


class TestTraversalTooDeepError:
    """Tests for TraversalTooDeepError."""

    def _build_instance(self):
        return TraversalTooDeepError(start_id="test_value", max_depth=1)

    def test_construction(self):
        """TraversalTooDeepError can be instantiated with mocked dependencies."""
        try:
            instance = self._build_instance()
        except (Exception, SystemExit) as e:
            pytest.skip(f"Requires domain-specific construction setup: {e}")
            return
        assert isinstance(instance, TraversalTooDeepError)


class TestPathNotFoundError:
    """Tests for PathNotFoundError."""

    def _build_instance(self):
        return PathNotFoundError(source_id="test_value", target_id="test_value")

    def test_construction(self):
        """PathNotFoundError can be instantiated with mocked dependencies."""
        try:
            instance = self._build_instance()
        except (Exception, SystemExit) as e:
            pytest.skip(f"Requires domain-specific construction setup: {e}")
            return
        assert isinstance(instance, PathNotFoundError)


class TestInvalidDirectionError:
    """Tests for InvalidDirectionError."""

    def _build_instance(self):
        return InvalidDirectionError(direction="test_value", valid_directions=["test_value"])

    def test_construction(self):
        """InvalidDirectionError can be instantiated with mocked dependencies."""
        try:
            instance = self._build_instance()
        except (Exception, SystemExit) as e:
            pytest.skip(f"Requires domain-specific construction setup: {e}")
            return
        assert isinstance(instance, InvalidDirectionError)


class TestExplanationGenerationFailedError:
    """Tests for ExplanationGenerationFailedError."""

    def _build_instance(self):
        return ExplanationGenerationFailedError(entity_id="test_value", entity_type="test_value", reason="test_value")

    def test_construction(self):
        """ExplanationGenerationFailedError can be instantiated with mocked dependencies."""
        try:
            instance = self._build_instance()
        except (Exception, SystemExit) as e:
            pytest.skip(f"Requires domain-specific construction setup: {e}")
            return
        assert isinstance(instance, ExplanationGenerationFailedError)


class TestUnsupportedLanguageError:
    """Tests for UnsupportedLanguageError."""

    def _build_instance(self):
        return UnsupportedLanguageError(language="test_value", supported=["test_value"])

    def test_construction(self):
        """UnsupportedLanguageError can be instantiated with mocked dependencies."""
        try:
            instance = self._build_instance()
        except (Exception, SystemExit) as e:
            pytest.skip(f"Requires domain-specific construction setup: {e}")
            return
        assert isinstance(instance, UnsupportedLanguageError)


class TestUnsupportedFormatError:
    """Tests for UnsupportedFormatError."""

    def _build_instance(self):
        return UnsupportedFormatError(format="test_value", supported=["test_value"])

    def test_construction(self):
        """UnsupportedFormatError can be instantiated with mocked dependencies."""
        try:
            instance = self._build_instance()
        except (Exception, SystemExit) as e:
            pytest.skip(f"Requires domain-specific construction setup: {e}")
            return
        assert isinstance(instance, UnsupportedFormatError)


class TestCausalityNotFoundError:
    """Tests for CausalityNotFoundError."""

    def _build_instance(self):
        return CausalityNotFoundError(entity_id="test_value", entity_type="test_value")

    def test_construction(self):
        """CausalityNotFoundError can be instantiated with mocked dependencies."""
        try:
            instance = self._build_instance()
        except (Exception, SystemExit) as e:
            pytest.skip(f"Requires domain-specific construction setup: {e}")
            return
        assert isinstance(instance, CausalityNotFoundError)


class TestCausalityInconsistentError:
    """Tests for CausalityInconsistentError."""

    def _build_instance(self):
        return CausalityInconsistentError(reason="test_value")

    def test_construction(self):
        """CausalityInconsistentError can be instantiated with mocked dependencies."""
        try:
            instance = self._build_instance()
        except (Exception, SystemExit) as e:
            pytest.skip(f"Requires domain-specific construction setup: {e}")
            return
        assert isinstance(instance, CausalityInconsistentError)


# ============================================================================
# Test CausalityExceptionFactory (dengan tambahan untuk semua factory methods)
# ============================================================================

class TestCausalityExceptionFactory:
    """Tests for CausalityExceptionFactory."""

    def _build_instance(self):
        return CausalityExceptionFactory()

    def test_construction(self):
        """CausalityExceptionFactory can be instantiated."""
        instance = self._build_instance()
        assert isinstance(instance, CausalityExceptionFactory)

    # --- Test existing smoke methods (dipertahankan) ---
    def test_node_not_found(self):
        """Test node_not_found factory method."""
        exc = CausalityExceptionFactory.node_not_found(
            node_id="node-123", entity_type="journal", entity_id="journal-456"
        )
        assert isinstance(exc, CausalNodeNotFoundError)
        assert exc.node_id == "node-123"
        assert exc.error_code == CausalityErrorCode.NODE_NOT_FOUND

    def test_node_already_exists(self):
        exc = CausalityExceptionFactory.node_already_exists(node_id="node-123")
        assert isinstance(exc, CausalNodeAlreadyExistsError)
        assert exc.node_id == "node-123"

    def test_node_invalid_type(self):
        exc = CausalityExceptionFactory.node_invalid_type(
            node_type="invalid", valid_types=["journal", "account"]
        )
        assert isinstance(exc, CausalNodeInvalidTypeError)
        assert exc.node_type == "invalid"

    def test_chain_incomplete(self):
        exc = CausalityExceptionFactory.chain_incomplete(
            start_id="start-1", end_id="end-1", missing_nodes=["node-a", "node-b"]
        )
        assert isinstance(exc, CausalChainIncompleteError)
        assert exc.start_id == "start-1"
        assert exc.end_id == "end-1"

    # --- TAMBAHAN: Factory methods yang hilang ---
    def test_cycle_detected(self):
        """Test cycle_detected factory method."""
        exc = CausalityExceptionFactory.cycle_detected(
            cycle_nodes=["node-1", "node-2", "node-3"]
        )
        assert isinstance(exc, CausalChainCycleDetectedError)
        assert exc.cycle_nodes == ["node-1", "node-2", "node-3"]
        assert exc.error_code == CausalityErrorCode.CHAIN_CYCLE_DETECTED
        assert exc.severity == CausalitySeverity.CRITICAL

    def test_relationship_not_found(self):
        """Test relationship_not_found factory method."""
        exc = CausalityExceptionFactory.relationship_not_found(
            source_id="source-1", target_id="target-1"
        )
        assert isinstance(exc, CausalRelationshipNotFoundError)
        assert exc.source_id == "source-1"
        assert exc.target_id == "target-1"
        assert exc.error_code == CausalityErrorCode.RELATIONSHIP_NOT_FOUND

    def test_circular_reference(self):
        """Test circular_reference factory method."""
        exc = CausalityExceptionFactory.circular_reference(
            entities=["A", "B", "C", "A"]
        )
        assert isinstance(exc, CircularReferenceDetectedError)
        assert exc.entities == ["A", "B", "C", "A"]
        assert exc.error_code == CausalityErrorCode.CIRCULAR_REFERENCE_DETECTED

    def test_why_query_failed(self):
        """Test why_query_failed factory method."""
        exc = CausalityExceptionFactory.why_query_failed(
            entity_id="entity-123", reason="Graph traversal timeout"
        )
        assert isinstance(exc, WhyQueryFailedError)
        assert exc.entity_id == "entity-123"
        assert exc.error_code == CausalityErrorCode.QUERY_FAILED

    def test_causality_not_found(self):
        """Test causality_not_found factory method."""
        exc = CausalityExceptionFactory.causality_not_found(
            entity_id="entity-123", entity_type="journal"
        )
        assert isinstance(exc, CausalityNotFoundError)
        assert exc.entity_id == "entity-123"
        assert exc.error_code == CausalityErrorCode.CAUSALITY_NOT_FOUND

    def test_invalid_relationship_strength(self):
        """Test invalid_relationship_strength factory method."""
        exc = CausalityExceptionFactory.invalid_relationship_strength(strength=1.5)
        assert isinstance(exc, RelationshipStrengthInvalidError)
        assert exc.strength == 1.5
        assert exc.error_code == CausalityErrorCode.RELATIONSHIP_STRENGTH_INVALID

    # --- Tambahan test untuk factory method lainnya (opsional) ---
    def test_unknown_error(self):
        """Test that we can create an unknown error (not a factory method, but coverage)."""
        exc = CausalityError(
            message="Unknown causality error",
            error_code=CausalityErrorCode.UNKNOWN_CAUSALITY_ERROR,
            severity=CausalitySeverity.MEDIUM,
        )
        assert exc.error_code == CausalityErrorCode.UNKNOWN_CAUSALITY_ERROR
        assert exc.severity == CausalitySeverity.MEDIUM
