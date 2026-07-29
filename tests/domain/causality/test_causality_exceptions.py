# test_causality_exceptions.py
# Comprehensive tests for domain/causality/causality_exceptions.py



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

# =============================================================================
# Enum Tests
# =============================================================================

class TestCausalityErrorCode:
    def test_members_exist(self) -> None:
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

    def test_member_is_instance(self) -> None:
        assert isinstance(CausalityErrorCode.NODE_NOT_FOUND, CausalityErrorCode)


class TestCausalitySeverity:
    def test_members_exist(self) -> None:
        assert hasattr(CausalitySeverity, 'CRITICAL')
        assert hasattr(CausalitySeverity, 'HIGH')
        assert hasattr(CausalitySeverity, 'MEDIUM')
        assert hasattr(CausalitySeverity, 'LOW')

    def test_member_is_instance(self) -> None:
        assert isinstance(CausalitySeverity.CRITICAL, CausalitySeverity)

    def test_values(self) -> None:
        assert CausalitySeverity.CRITICAL.value == 80
        assert CausalitySeverity.HIGH.value == 60
        assert CausalitySeverity.MEDIUM.value == 40
        assert CausalitySeverity.LOW.value == 20


# =============================================================================
# Base Exception Tests
# =============================================================================

class TestCausalityError:
    def test_construction_minimal(self) -> None:
        exc = CausalityError(
            message="Test error",
            error_code=CausalityErrorCode.UNKNOWN_CAUSALITY_ERROR,
        )
        assert exc.original_message == "Test error"
        assert exc.error_code == CausalityErrorCode.UNKNOWN_CAUSALITY_ERROR
        assert exc.severity == CausalitySeverity.MEDIUM  # default
        assert exc.component is None
        assert exc.details == {}
        assert exc.cause is None
        assert "Test error" in str(exc)

    def test_construction_full(self) -> None:
        cause = ValueError("original")
        exc = CausalityError(
            message="Test error",
            error_code=CausalityErrorCode.NODE_NOT_FOUND,
            severity=CausalitySeverity.HIGH,
            component="test_component",
            details={"key": "value"},
            cause=cause,
        )
        assert exc.original_message == "Test error"
        assert exc.error_code == CausalityErrorCode.NODE_NOT_FOUND
        assert exc.severity == CausalitySeverity.HIGH
        assert exc.component == "test_component"
        assert exc.details == {"key": "value"}
        assert exc.cause is cause
        assert "Test error" in str(exc)

    def test_to_dict(self) -> None:
        exc = CausalityError(
            message="Test error",
            error_code=CausalityErrorCode.QUERY_FAILED,
            severity=CausalitySeverity.CRITICAL,
            component="test",
            details={"a": 1},
            cause=ValueError("nested"),
        )
        d = exc.to_dict()
        assert d["type"] == "CausalityError"
        assert d["error_code"] == "QUERY_FAILED"
        assert d["severity"] == "CRITICAL"
        assert d["message"] == "Test error"
        assert d["component"] == "test"
        assert d["details"] == {"a": 1}
        assert d["cause"] == "nested"

    def test_is_critical(self) -> None:
        exc_critical = CausalityError("", CausalityErrorCode.UNKNOWN_CAUSALITY_ERROR, CausalitySeverity.CRITICAL)
        exc_high = CausalityError("", CausalityErrorCode.UNKNOWN_CAUSALITY_ERROR, CausalitySeverity.HIGH)
        assert exc_critical.is_critical() is True
        assert exc_high.is_critical() is False

    def test_is_high(self) -> None:
        exc_high = CausalityError("", CausalityErrorCode.UNKNOWN_CAUSALITY_ERROR, CausalitySeverity.HIGH)
        exc_medium = CausalityError("", CausalityErrorCode.UNKNOWN_CAUSALITY_ERROR, CausalitySeverity.MEDIUM)
        assert exc_high.is_high() is True
        assert exc_medium.is_high() is False


# =============================================================================
# Specific Exception Tests
# =============================================================================

class TestCausalNodeNotFoundError:
    def test_construction_with_node_id(self) -> None:
        exc = CausalNodeNotFoundError(node_id="n123")
        assert exc.node_id == "n123"
        assert exc.error_code == CausalityErrorCode.NODE_NOT_FOUND
        assert exc.severity == CausalitySeverity.HIGH
        assert "n123" in str(exc)

    def test_construction_with_entity(self) -> None:
        exc = CausalNodeNotFoundError(entity_type="journal", entity_id="j456")
        assert exc.node_id is None
        assert exc.details["entity_type"] == "journal"
        assert exc.details["entity_id"] == "j456"
        assert "journal" in str(exc)

    def test_construction_fallback(self) -> None:
        exc = CausalNodeNotFoundError()
        assert exc.node_id is None
        assert exc.message == "Causal node not found"


class TestCausalNodeAlreadyExistsError:
    def test_construction(self) -> None:
        exc = CausalNodeAlreadyExistsError(node_id="n123")
        assert exc.node_id == "n123"
        assert exc.error_code == CausalityErrorCode.NODE_ALREADY_EXISTS
        assert exc.severity == CausalitySeverity.MEDIUM
        assert "n123" in str(exc)


class TestCausalNodeInvalidTypeError:
    def test_construction(self) -> None:
        exc = CausalNodeInvalidTypeError(node_type="bad", valid_types=["good1", "good2"])
        assert exc.node_type == "bad"
        assert exc.details["valid_types"] == ["good1", "good2"]
        assert exc.error_code == CausalityErrorCode.NODE_INVALID_TYPE
        assert exc.severity == CausalitySeverity.HIGH


class TestCausalNodeHashMismatchError:
    def test_construction(self) -> None:
        exc = CausalNodeHashMismatchError(
            node_id="n123", expected_hash="abc123", actual_hash="def456"
        )
        assert exc.node_id == "n123"
        assert exc.details["expected_hash"] == "abc123"
        assert exc.details["actual_hash"] == "def456"
        assert exc.error_code == CausalityErrorCode.NODE_HASH_MISMATCH
        assert exc.severity == CausalitySeverity.CRITICAL
        assert "n123" in str(exc)


class TestCausalNodeCorruptedError:
    def test_construction(self) -> None:
        exc = CausalNodeCorruptedError(node_id="n123", reason="missing data")
        assert exc.node_id == "n123"
        assert exc.details["reason"] == "missing data"
        assert exc.error_code == CausalityErrorCode.NODE_CORRUPTED
        assert exc.severity == CausalitySeverity.CRITICAL


class TestCausalChainIncompleteError:
    def test_construction(self) -> None:
        exc = CausalChainIncompleteError(
            start_id="s1", end_id="e1", missing_nodes=["a", "b"]
        )
        assert exc.start_id == "s1"
        assert exc.end_id == "e1"
        assert exc.details["missing_nodes"] == ["a", "b"]
        assert exc.error_code == CausalityErrorCode.CHAIN_INCOMPLETE
        assert exc.severity == CausalitySeverity.HIGH


class TestCausalChainCycleDetectedError:
    def test_construction(self) -> None:
        exc = CausalChainCycleDetectedError(cycle_nodes=["a", "b", "c", "a"])
        assert exc.cycle_nodes == ["a", "b", "c", "a"]
        assert exc.error_code == CausalityErrorCode.CHAIN_CYCLE_DETECTED
        assert exc.severity == CausalitySeverity.CRITICAL
        assert "a -> b" in str(exc)


class TestCausalChainTooDeepError:
    def test_construction(self) -> None:
        exc = CausalChainTooDeepError(max_depth=5, actual_depth=10)
        assert exc.max_depth == 5
        assert exc.actual_depth == 10
        assert exc.error_code == CausalityErrorCode.CHAIN_TOO_DEEP
        assert exc.severity == CausalitySeverity.MEDIUM


class TestCausalChainBrokenError:
    def test_construction(self) -> None:
        exc = CausalChainBrokenError(
            node_id="n1", expected_next="n2", actual_next="n3"
        )
        assert exc.node_id == "n1"
        assert exc.details["expected_next"] == "n2"
        assert exc.details["actual_next"] == "n3"
        assert exc.error_code == CausalityErrorCode.CHAIN_BROKEN
        assert exc.severity == CausalitySeverity.HIGH


class TestCausalChainEmptyError:
    def test_construction(self) -> None:
        exc = CausalChainEmptyError(entity_id="e1", entity_type="journal")
        assert exc.entity_id == "e1"
        assert exc.details["entity_type"] == "journal"
        assert exc.error_code == CausalityErrorCode.CHAIN_EMPTY
        assert exc.severity == CausalitySeverity.MEDIUM


class TestCausalChainNotFoundError:
    def test_construction(self) -> None:
        exc = CausalChainNotFoundError(chain_id="c1")
        assert exc.chain_id == "c1"
        assert exc.error_code == CausalityErrorCode.CHAIN_NOT_FOUND
        assert exc.severity == CausalitySeverity.MEDIUM


class TestCausalRelationshipNotFoundError:
    def test_construction(self) -> None:
        exc = CausalRelationshipNotFoundError(source_id="s1", target_id="t1")
        assert exc.source_id == "s1"
        assert exc.target_id == "t1"
        assert exc.error_code == CausalityErrorCode.RELATIONSHIP_NOT_FOUND
        assert exc.severity == CausalitySeverity.MEDIUM


class TestCausalRelationshipAlreadyExistsError:
    def test_construction(self) -> None:
        exc = CausalRelationshipAlreadyExistsError(source_id="s1", target_id="t1")
        assert exc.source_id == "s1"
        assert exc.target_id == "t1"
        assert exc.error_code == CausalityErrorCode.RELATIONSHIP_ALREADY_EXISTS
        assert exc.severity == CausalitySeverity.LOW


class TestCausalRelationshipInvalidError:
    def test_construction(self) -> None:
        exc = CausalRelationshipInvalidError(
            source_id="s1", target_id="t1", reason="self-loop not allowed"
        )
        assert exc.source_id == "s1"
        assert exc.target_id == "t1"
        assert exc.details["reason"] == "self-loop not allowed"
        assert exc.error_code == CausalityErrorCode.RELATIONSHIP_INVALID
        assert exc.severity == CausalitySeverity.HIGH


class TestCircularReferenceDetectedError:
    def test_construction(self) -> None:
        exc = CircularReferenceDetectedError(entities=["a", "b", "c", "a"])
        assert exc.entities == ["a", "b", "c", "a"]
        assert exc.error_code == CausalityErrorCode.CIRCULAR_REFERENCE_DETECTED
        assert exc.severity == CausalitySeverity.HIGH


class TestRelationshipStrengthInvalidError:
    def test_construction(self) -> None:
        exc = RelationshipStrengthInvalidError(strength=1.5)
        assert exc.strength == 1.5
        assert exc.error_code == CausalityErrorCode.RELATIONSHIP_STRENGTH_INVALID
        assert exc.severity == CausalitySeverity.MEDIUM


class TestWhyQueryFailedError:
    def test_construction(self) -> None:
        exc = WhyQueryFailedError(entity_id="e1", reason="timeout")
        assert exc.entity_id == "e1"
        assert exc.details["reason"] == "timeout"
        assert exc.error_code == CausalityErrorCode.QUERY_FAILED
        assert exc.severity == CausalitySeverity.MEDIUM


class TestWhyQueryTimeoutError:
    def test_construction(self) -> None:
        exc = WhyQueryTimeoutError(entity_id="e1", timeout_ms=5000)
        assert exc.entity_id == "e1"
        assert exc.details["timeout_ms"] == 5000
        assert exc.error_code == CausalityErrorCode.QUERY_TIMEOUT
        assert exc.severity == CausalitySeverity.MEDIUM


class TestInvalidQueryDepthError:
    def test_construction(self) -> None:
        exc = InvalidQueryDepthError(depth=10, max_depth=5)
        assert exc.depth == 10
        assert exc.details["max_depth"] == 5
        assert exc.error_code == CausalityErrorCode.INVALID_QUERY_DEPTH
        assert exc.severity == CausalitySeverity.LOW


class TestTraversalTooDeepError:
    def test_construction(self) -> None:
        exc = TraversalTooDeepError(start_id="s1", max_depth=3)
        assert exc.start_id == "s1"
        assert exc.details["max_depth"] == 3
        assert exc.error_code == CausalityErrorCode.TRAVERSAL_TOO_DEEP
        assert exc.severity == CausalitySeverity.LOW


class TestPathNotFoundError:
    def test_construction(self) -> None:
        exc = PathNotFoundError(source_id="s1", target_id="t1")
        assert exc.source_id == "s1"
        assert exc.target_id == "t1"
        assert exc.error_code == CausalityErrorCode.PATH_NOT_FOUND
        assert exc.severity == CausalitySeverity.MEDIUM


class TestInvalidDirectionError:
    def test_construction(self) -> None:
        exc = InvalidDirectionError(direction="up", valid_directions=["down", "both"])
        assert exc.direction == "up"
        assert exc.details["valid_directions"] == ["down", "both"]
        assert exc.error_code == CausalityErrorCode.INVALID_DIRECTION
        assert exc.severity == CausalitySeverity.LOW


class TestExplanationGenerationFailedError:
    def test_construction(self) -> None:
        exc = ExplanationGenerationFailedError(
            entity_id="e1", entity_type="journal", reason="no data"
        )
        assert exc.entity_id == "e1"
        assert exc.details["entity_type"] == "journal"
        assert exc.details["reason"] == "no data"
        assert exc.error_code == CausalityErrorCode.EXPLANATION_GENERATION_FAILED
        assert exc.severity == CausalitySeverity.MEDIUM


class TestUnsupportedLanguageError:
    def test_construction(self) -> None:
        exc = UnsupportedLanguageError(language="fr", supported=["en", "id"])
        assert exc.language == "fr"
        assert exc.details["supported"] == ["en", "id"]
        assert exc.error_code == CausalityErrorCode.UNSUPPORTED_LANGUAGE
        assert exc.severity == CausalitySeverity.LOW


class TestUnsupportedFormatError:
    def test_construction(self) -> None:
        exc = UnsupportedFormatError(format="xml", supported=["json", "yaml"])
        assert exc.format == "xml"
        assert exc.details["supported"] == ["json", "yaml"]
        assert exc.error_code == CausalityErrorCode.UNSUPPORTED_FORMAT
        assert exc.severity == CausalitySeverity.LOW


class TestCausalityNotFoundError:
    def test_construction(self) -> None:
        exc = CausalityNotFoundError(entity_id="e1", entity_type="account")
        assert exc.entity_id == "e1"
        assert exc.details["entity_type"] == "account"
        assert exc.error_code == CausalityErrorCode.CAUSALITY_NOT_FOUND
        assert exc.severity == CausalitySeverity.MEDIUM


class TestCausalityInconsistentError:
    def test_construction(self) -> None:
        exc = CausalityInconsistentError(reason="version mismatch")
        assert exc.reason == "version mismatch"
        assert exc.details["reason"] == "version mismatch"
        assert exc.error_code == CausalityErrorCode.CAUSALITY_INCONSISTENT
        assert exc.severity == CausalitySeverity.HIGH


# =============================================================================
# Exception Factory Tests
# =============================================================================

class TestCausalityExceptionFactory:
    def test_node_not_found_with_id(self) -> None:
        exc = CausalityExceptionFactory.node_not_found(node_id="n1")
        assert isinstance(exc, CausalNodeNotFoundError)
        assert exc.node_id == "n1"

    def test_node_not_found_with_entity(self) -> None:
        exc = CausalityExceptionFactory.node_not_found(entity_type="journal", entity_id="j1")
        assert isinstance(exc, CausalNodeNotFoundError)
        assert exc.details["entity_type"] == "journal"
        assert exc.details["entity_id"] == "j1"

    def test_node_already_exists(self) -> None:
        exc = CausalityExceptionFactory.node_already_exists(node_id="n1")
        assert isinstance(exc, CausalNodeAlreadyExistsError)
        assert exc.node_id == "n1"

    def test_node_invalid_type(self) -> None:
        exc = CausalityExceptionFactory.node_invalid_type(
            node_type="bad", valid_types=["good1", "good2"]
        )
        assert isinstance(exc, CausalNodeInvalidTypeError)
        assert exc.node_type == "bad"
        assert exc.details["valid_types"] == ["good1", "good2"]

    def test_chain_incomplete(self) -> None:
        exc = CausalityExceptionFactory.chain_incomplete(
            start_id="s1", end_id="e1", missing_nodes=["a", "b"]
        )
        assert isinstance(exc, CausalChainIncompleteError)
        assert exc.start_id == "s1"
        assert exc.end_id == "e1"

    def test_cycle_detected(self) -> None:
        exc = CausalityExceptionFactory.cycle_detected(cycle_nodes=["a", "b", "c", "a"])
        assert isinstance(exc, CausalChainCycleDetectedError)
        assert exc.cycle_nodes == ["a", "b", "c", "a"]

    def test_relationship_not_found(self) -> None:
        exc = CausalityExceptionFactory.relationship_not_found(source_id="s1", target_id="t1")
        assert isinstance(exc, CausalRelationshipNotFoundError)
        assert exc.source_id == "s1"
        assert exc.target_id == "t1"

    def test_circular_reference(self) -> None:
        exc = CausalityExceptionFactory.circular_reference(entities=["a", "b", "a"])
        assert isinstance(exc, CircularReferenceDetectedError)
        assert exc.entities == ["a", "b", "a"]

    def test_why_query_failed(self) -> None:
        exc = CausalityExceptionFactory.why_query_failed(entity_id="e1", reason="timeout")
        assert isinstance(exc, WhyQueryFailedError)
        assert exc.entity_id == "e1"
        assert exc.details["reason"] == "timeout"

    def test_causality_not_found(self) -> None:
        exc = CausalityExceptionFactory.causality_not_found(entity_id="e1", entity_type="account")
        assert isinstance(exc, CausalityNotFoundError)
        assert exc.entity_id == "e1"
        assert exc.details["entity_type"] == "account"

    def test_invalid_relationship_strength(self) -> None:
        exc = CausalityExceptionFactory.invalid_relationship_strength(strength=1.2)
        assert isinstance(exc, RelationshipStrengthInvalidError)
        assert exc.strength == 1.2

    # Additional factory methods (if any exist in source) - they are already covered above
    # Also test that all factory methods return the correct error_code
    def test_factory_sets_error_code(self) -> None:
        exc = CausalityExceptionFactory.node_not_found(node_id="n1")
        assert exc.error_code == CausalityErrorCode.NODE_NOT_FOUND

        exc = CausalityExceptionFactory.cycle_detected(["a"])
        assert exc.error_code == CausalityErrorCode.CHAIN_CYCLE_DETECTED

        exc = CausalityExceptionFactory.relationship_not_found("s", "t")
        assert exc.error_code == CausalityErrorCode.RELATIONSHIP_NOT_FOUND

        exc = CausalityExceptionFactory.circular_reference(["a"])
        assert exc.error_code == CausalityErrorCode.CIRCULAR_REFERENCE_DETECTED

        exc = CausalityExceptionFactory.why_query_failed("e", "r")
        assert exc.error_code == CausalityErrorCode.QUERY_FAILED

        exc = CausalityExceptionFactory.causality_not_found("e", "a")
        assert exc.error_code == CausalityErrorCode.CAUSALITY_NOT_FOUND

        exc = CausalityExceptionFactory.invalid_relationship_strength(1.5)
        assert exc.error_code == CausalityErrorCode.RELATIONSHIP_STRENGTH_INVALID
