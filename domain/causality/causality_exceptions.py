#!/usr/bin/env python3
"""
Module: causality_exceptions.py
Layer: Domain / Causality
Responsibility: Exception hierarchy untuk layer causality.
               Mendefinisikan semua error yang mungkin terjadi di causal node,
               causal chain builder, causality tracker, why query engine,
               dan audit story builder. Mendukung error codes, severity,
               serialisasi, dan factory methods.
"""

from __future__ import annotations

from enum import Enum, auto
from typing import Any

# ============================================================================
# ERROR CODES & SEVERITY
# ============================================================================


class CausalityErrorCode(Enum):
    """Kode error untuk causality layer."""

    # Node errors
    NODE_NOT_FOUND = auto()
    NODE_ALREADY_EXISTS = auto()
    NODE_INVALID_TYPE = auto()
    NODE_HASH_MISMATCH = auto()
    NODE_CORRUPTED = auto()

    # Chain errors
    CHAIN_INCOMPLETE = auto()
    CHAIN_CYCLE_DETECTED = auto()
    CHAIN_TOO_DEEP = auto()
    CHAIN_BROKEN = auto()
    CHAIN_EMPTY = auto()
    CHAIN_NOT_FOUND = auto()

    # Relationship errors
    RELATIONSHIP_NOT_FOUND = auto()
    RELATIONSHIP_ALREADY_EXISTS = auto()
    RELATIONSHIP_INVALID = auto()
    CIRCULAR_REFERENCE_DETECTED = auto()
    RELATIONSHIP_STRENGTH_INVALID = auto()

    # Query errors
    QUERY_FAILED = auto()
    QUERY_TIMEOUT = auto()
    INVALID_QUERY_DEPTH = auto()
    QUERY_CACHE_ERROR = auto()

    # Traversal errors
    TRAVERSAL_TOO_DEEP = auto()
    PATH_NOT_FOUND = auto()
    INVALID_DIRECTION = auto()

    # Explanation errors
    EXPLANATION_GENERATION_FAILED = auto()
    UNSUPPORTED_LANGUAGE = auto()
    UNSUPPORTED_FORMAT = auto()

    # General
    CAUSALITY_NOT_FOUND = auto()
    CAUSALITY_INCONSISTENT = auto()
    UNKNOWN_CAUSALITY_ERROR = auto()


class CausalitySeverity(Enum):
    """Severity untuk causality error."""

    CRITICAL = 80  # Error fatal, rantai kausalitas rusak
    HIGH = 60  # Error serius, perlu investigasi
    MEDIUM = 40  # Error yang dapat direcovery
    LOW = 20  # Warning, tidak menghentikan operasi


# ============================================================================
# BASE EXCEPTION
# ============================================================================


class CausalityError(Exception):
    """
    Base exception untuk semua error di causality layer.
    """

    def __init__(
        self,
        message: str,
        error_code: CausalityErrorCode,
        severity: CausalitySeverity = CausalitySeverity.MEDIUM,
        component: str | None = None,
        details: dict[str, Any] | None = None,
        cause: Exception | None = None,
    ):
        self.error_code = error_code
        self.severity = severity
        self.component = component
        self.details = details or {}
        self.cause = cause

        full_message = f"[{severity.name}][{error_code.name}] {message}"
        if component:
            full_message = f"[{component}] {full_message}"
        super().__init__(full_message)
        self._original_message = message

    @property
    def original_message(self) -> str:
        return self._original_message

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.__class__.__name__,
            "error_code": self.error_code.name,
            "severity": self.severity.name,
            "message": self._original_message,
            "component": self.component,
            "details": self.details,
            "cause": str(self.cause) if self.cause else None,
        }

    def is_critical(self) -> bool:
        return self.severity == CausalitySeverity.CRITICAL

    def is_high(self) -> bool:
        return self.severity == CausalitySeverity.HIGH


# ============================================================================
# NODE EXCEPTIONS
# ============================================================================


class CausalNodeNotFoundError(CausalityError):
    """Node kausalitas tidak ditemukan."""

    def __init__(
        self,
        node_id: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        **kwargs,
    ):
        if node_id:
            message = f"Causal node {node_id} not found"
        elif entity_type and entity_id:
            message = f"Causal node for {entity_type} {entity_id} not found"
        else:
            message = "Causal node not found"
        super().__init__(
            message=message,
            error_code=CausalityErrorCode.NODE_NOT_FOUND,
            severity=CausalitySeverity.HIGH,
            component="causal_node",
            details={"node_id": node_id, "entity_type": entity_type, "entity_id": entity_id},
            **kwargs,
        )
        self.node_id = node_id


class CausalNodeAlreadyExistsError(CausalityError):
    """Node kausalitas sudah ada."""

    def __init__(self, node_id: str, **kwargs):
        super().__init__(
            message=f"Causal node {node_id} already exists",
            error_code=CausalityErrorCode.NODE_ALREADY_EXISTS,
            severity=CausalitySeverity.MEDIUM,
            component="causal_node",
            details={"node_id": node_id},
            **kwargs,
        )
        self.node_id = node_id


class CausalNodeInvalidTypeError(CausalityError):
    """Tipe node kausalitas tidak valid."""

    def __init__(self, node_type: str, valid_types: list[str], **kwargs):
        super().__init__(
            message=f"Invalid causal node type: {node_type}. Valid types: {valid_types}",
            error_code=CausalityErrorCode.NODE_INVALID_TYPE,
            severity=CausalitySeverity.HIGH,
            component="causal_node",
            details={"node_type": node_type, "valid_types": valid_types},
            **kwargs,
        )
        self.node_type = node_type


class CausalNodeHashMismatchError(CausalityError):
    """Hash kriptografis node tidak cocok (tamper detection)."""

    def __init__(self, node_id: str, expected_hash: str, actual_hash: str, **kwargs):
        super().__init__(
            message=f"Hash mismatch for node {node_id}: expected {expected_hash[:16]}..., got {actual_hash[:16]}...",
            error_code=CausalityErrorCode.NODE_HASH_MISMATCH,
            severity=CausalitySeverity.CRITICAL,
            component="causal_node",
            details={
                "node_id": node_id,
                "expected_hash": expected_hash,
                "actual_hash": actual_hash,
            },
            **kwargs,
        )
        self.node_id = node_id


class CausalNodeCorruptedError(CausalityError):
    """Node kausalitas korup (data tidak konsisten)."""

    def __init__(self, node_id: str, reason: str, **kwargs):
        super().__init__(
            message=f"Causal node {node_id} is corrupted: {reason}",
            error_code=CausalityErrorCode.NODE_CORRUPTED,
            severity=CausalitySeverity.CRITICAL,
            component="causal_node",
            details={"node_id": node_id, "reason": reason},
            **kwargs,
        )
        self.node_id = node_id


# ============================================================================
# CHAIN EXCEPTIONS
# ============================================================================


class CausalChainIncompleteError(CausalityError):
    """Rantai kausalitas tidak lengkap."""

    def __init__(self, start_id: str, end_id: str, missing_nodes: list[str], **kwargs):
        super().__init__(
            message=f"Causal chain incomplete between {start_id} and {end_id}. Missing nodes: {missing_nodes}",
            error_code=CausalityErrorCode.CHAIN_INCOMPLETE,
            severity=CausalitySeverity.HIGH,
            component="causal_chain",
            details={"start_id": start_id, "end_id": end_id, "missing_nodes": missing_nodes},
            **kwargs,
        )
        self.start_id = start_id
        self.end_id = end_id


class CausalChainCycleDetectedError(CausalityError):
    """Siklus terdeteksi dalam rantai kausalitas."""

    def __init__(self, cycle_nodes: list[str], **kwargs):
        super().__init__(
            message=f"Causal cycle detected: {' -> '.join(cycle_nodes)}",
            error_code=CausalityErrorCode.CHAIN_CYCLE_DETECTED,
            severity=CausalitySeverity.CRITICAL,
            component="causal_chain",
            details={"cycle": cycle_nodes},
            **kwargs,
        )
        self.cycle_nodes = cycle_nodes


class CausalChainTooDeepError(CausalityError):
    """Rantai kausalitas terlalu dalam melebihi batas."""

    def __init__(self, max_depth: int, actual_depth: int, **kwargs):
        super().__init__(
            message=f"Causal chain exceeds maximum depth of {max_depth}. Actual depth: {actual_depth}",
            error_code=CausalityErrorCode.CHAIN_TOO_DEEP,
            severity=CausalitySeverity.MEDIUM,
            component="causal_chain",
            details={"max_depth": max_depth, "actual_depth": actual_depth},
            **kwargs,
        )
        self.max_depth = max_depth


class CausalChainBrokenError(CausalityError):
    """Rantai kausalitas putus di suatu titik."""

    def __init__(self, node_id: str, expected_next: str | None, actual_next: str | None, **kwargs):
        super().__init__(
            message=f"Causal chain broken at node {node_id}: expected next {expected_next}, got {actual_next}",
            error_code=CausalityErrorCode.CHAIN_BROKEN,
            severity=CausalitySeverity.HIGH,
            component="causal_chain",
            details={
                "node_id": node_id,
                "expected_next": expected_next,
                "actual_next": actual_next,
            },
            **kwargs,
        )
        self.node_id = node_id


class CausalChainEmptyError(CausalityError):
    """Rantai kausalitas kosong."""

    def __init__(self, entity_id: str, entity_type: str, **kwargs):
        super().__init__(
            message=f"No causal chain found for {entity_type} {entity_id}",
            error_code=CausalityErrorCode.CHAIN_EMPTY,
            severity=CausalitySeverity.MEDIUM,
            component="causal_chain",
            details={"entity_id": entity_id, "entity_type": entity_type},
            **kwargs,
        )
        self.entity_id = entity_id


class CausalChainNotFoundError(CausalityError):
    """Rantai kausalitas tidak ditemukan."""

    def __init__(self, chain_id: str, **kwargs):
        super().__init__(
            message=f"Causal chain {chain_id} not found",
            error_code=CausalityErrorCode.CHAIN_NOT_FOUND,
            severity=CausalitySeverity.MEDIUM,
            component="causal_chain",
            details={"chain_id": chain_id},
            **kwargs,
        )
        self.chain_id = chain_id


# ============================================================================
# RELATIONSHIP EXCEPTIONS
# ============================================================================


class CausalRelationshipNotFoundError(CausalityError):
    """Hubungan kausal tidak ditemukan."""

    def __init__(self, source_id: str, target_id: str, **kwargs):
        super().__init__(
            message=f"Causal relationship not found between {source_id} and {target_id}",
            error_code=CausalityErrorCode.RELATIONSHIP_NOT_FOUND,
            severity=CausalitySeverity.MEDIUM,
            component="causality_tracker",
            details={"source_id": source_id, "target_id": target_id},
            **kwargs,
        )
        self.source_id = source_id
        self.target_id = target_id


class CausalRelationshipAlreadyExistsError(CausalityError):
    """Hubungan kausal sudah ada."""

    def __init__(self, source_id: str, target_id: str, **kwargs):
        super().__init__(
            message=f"Causal relationship already exists between {source_id} and {target_id}",
            error_code=CausalityErrorCode.RELATIONSHIP_ALREADY_EXISTS,
            severity=CausalitySeverity.LOW,
            component="causality_tracker",
            details={"source_id": source_id, "target_id": target_id},
            **kwargs,
        )
        self.source_id = source_id
        self.target_id = target_id


class CausalRelationshipInvalidError(CausalityError):
    """Hubungan kausal tidak valid (misal source == target)."""

    def __init__(self, source_id: str, target_id: str, reason: str, **kwargs):
        super().__init__(
            message=f"Invalid causal relationship between {source_id} and {target_id}: {reason}",
            error_code=CausalityErrorCode.RELATIONSHIP_INVALID,
            severity=CausalitySeverity.HIGH,
            component="causality_tracker",
            details={"source_id": source_id, "target_id": target_id, "reason": reason},
            **kwargs,
        )
        self.source_id = source_id
        self.target_id = target_id


class CircularReferenceDetectedError(CausalityError):
    """Referensi sirkular terdeteksi dalam hubungan kausal."""

    def __init__(self, entities: list[str], **kwargs):
        super().__init__(
            message=f"Circular reference detected in causal relationships: {' -> '.join(entities)}",
            error_code=CausalityErrorCode.CIRCULAR_REFERENCE_DETECTED,
            severity=CausalitySeverity.HIGH,
            component="causality_tracker",
            details={"circular_chain": entities},
            **kwargs,
        )
        self.entities = entities


class RelationshipStrengthInvalidError(CausalityError):
    """Kekuatan hubungan kausal tidak valid (harus 0-1)."""

    def __init__(self, strength: float, **kwargs):
        super().__init__(
            message=f"Invalid relationship strength: {strength}. Must be between 0 and 1.",
            error_code=CausalityErrorCode.RELATIONSHIP_STRENGTH_INVALID,
            severity=CausalitySeverity.MEDIUM,
            component="causality_tracker",
            details={"strength": strength},
            **kwargs,
        )
        self.strength = strength


# ============================================================================
# QUERY EXCEPTIONS
# ============================================================================


class WhyQueryFailedError(CausalityError):
    """Query "why" gagal dijalankan."""

    def __init__(self, entity_id: str, reason: str, **kwargs):
        super().__init__(
            message=f"Why query failed for entity {entity_id}: {reason}",
            error_code=CausalityErrorCode.QUERY_FAILED,
            severity=CausalitySeverity.MEDIUM,
            component="why_query_engine",
            details={"entity_id": entity_id, "reason": reason},
            **kwargs,
        )
        self.entity_id = entity_id


class WhyQueryTimeoutError(CausalityError):
    """Query "why" timeout."""

    def __init__(self, entity_id: str, timeout_ms: int, **kwargs):
        super().__init__(
            message=f"Why query for entity {entity_id} timed out after {timeout_ms}ms",
            error_code=CausalityErrorCode.QUERY_TIMEOUT,
            severity=CausalitySeverity.MEDIUM,
            component="why_query_engine",
            details={"entity_id": entity_id, "timeout_ms": timeout_ms},
            **kwargs,
        )
        self.entity_id = entity_id


class InvalidQueryDepthError(CausalityError):
    """Kedalaman query tidak valid."""

    def __init__(self, depth: int, max_depth: int, **kwargs):
        super().__init__(
            message=f"Invalid query depth: {depth}. Max allowed depth: {max_depth}",
            error_code=CausalityErrorCode.INVALID_QUERY_DEPTH,
            severity=CausalitySeverity.LOW,
            component="why_query_engine",
            details={"depth": depth, "max_depth": max_depth},
            **kwargs,
        )
        self.depth = depth


# ============================================================================
# TRAVERSAL EXCEPTIONS
# ============================================================================


class TraversalTooDeepError(CausalityError):
    """Traversal melebihi batas kedalaman."""

    def __init__(self, start_id: str, max_depth: int, **kwargs):
        super().__init__(
            message=f"Traversal from {start_id} exceeded max depth {max_depth}",
            error_code=CausalityErrorCode.TRAVERSAL_TOO_DEEP,
            severity=CausalitySeverity.LOW,
            component="causality_tracker",
            details={"start_id": start_id, "max_depth": max_depth},
            **kwargs,
        )
        self.start_id = start_id


class PathNotFoundError(CausalityError):
    """Jalur kausal tidak ditemukan antara dua entitas."""

    def __init__(self, source_id: str, target_id: str, **kwargs):
        super().__init__(
            message=f"No causal path found between {source_id} and {target_id}",
            error_code=CausalityErrorCode.PATH_NOT_FOUND,
            severity=CausalitySeverity.MEDIUM,
            component="causality_tracker",
            details={"source_id": source_id, "target_id": target_id},
            **kwargs,
        )
        self.source_id = source_id
        self.target_id = target_id


class InvalidDirectionError(CausalityError):
    """Arah traversal tidak valid."""

    def __init__(self, direction: str, valid_directions: list[str], **kwargs):
        super().__init__(
            message=f"Invalid traversal direction: {direction}. Valid: {valid_directions}",
            error_code=CausalityErrorCode.INVALID_DIRECTION,
            severity=CausalitySeverity.LOW,
            component="causality_tracker",
            details={"direction": direction, "valid_directions": valid_directions},
            **kwargs,
        )
        self.direction = direction


# ============================================================================
# EXPLANATION EXCEPTIONS
# ============================================================================


class ExplanationGenerationFailedError(CausalityError):
    """Gagal menghasilkan penjelasan."""

    def __init__(self, entity_id: str, entity_type: str, reason: str, **kwargs):
        super().__init__(
            message=f"Failed to generate explanation for {entity_type} {entity_id}: {reason}",
            error_code=CausalityErrorCode.EXPLANATION_GENERATION_FAILED,
            severity=CausalitySeverity.MEDIUM,
            component="explanation_generator",
            details={"entity_id": entity_id, "entity_type": entity_type, "reason": reason},
            **kwargs,
        )
        self.entity_id = entity_id


class UnsupportedLanguageError(CausalityError):
    """Bahasa tidak didukung."""

    def __init__(self, language: str, supported: list[str], **kwargs):
        super().__init__(
            message=f"Unsupported language: {language}. Supported: {supported}",
            error_code=CausalityErrorCode.UNSUPPORTED_LANGUAGE,
            severity=CausalitySeverity.LOW,
            component="explanation_generator",
            details={"language": language, "supported": supported},
            **kwargs,
        )
        self.language = language


class UnsupportedFormatError(CausalityError):
    """Format output tidak didukung."""

    def __init__(self, format: str, supported: list[str], **kwargs):
        super().__init__(
            message=f"Unsupported output format: {format}. Supported: {supported}",
            error_code=CausalityErrorCode.UNSUPPORTED_FORMAT,
            severity=CausalitySeverity.LOW,
            component="explanation_generator",
            details={"format": format, "supported": supported},
            **kwargs,
        )
        self.format = format


# ============================================================================
# GENERAL EXCEPTIONS
# ============================================================================


class CausalityNotFoundError(CausalityError):
    """Kausalitas tidak ditemukan untuk entitas."""

    def __init__(self, entity_id: str, entity_type: str, **kwargs):
        super().__init__(
            message=f"No causal information found for {entity_type} {entity_id}",
            error_code=CausalityErrorCode.CAUSALITY_NOT_FOUND,
            severity=CausalitySeverity.MEDIUM,
            component="general",
            details={"entity_id": entity_id, "entity_type": entity_type},
            **kwargs,
        )
        self.entity_id = entity_id


class CausalityInconsistentError(CausalityError):
    """Data kausalitas tidak konsisten."""

    def __init__(self, reason: str, **kwargs):
        super().__init__(
            message=f"Causality data inconsistent: {reason}",
            error_code=CausalityErrorCode.CAUSALITY_INCONSISTENT,
            severity=CausalitySeverity.HIGH,
            component="general",
            details={"reason": reason},
            **kwargs,
        )
        self.reason = reason


# ============================================================================
# EXCEPTION FACTORY
# ============================================================================


class CausalityExceptionFactory:
    """
    Factory untuk membuat causality exceptions dengan konsistensi.
    """

    @staticmethod
    def node_not_found(
        node_id: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        **kwargs,
    ) -> CausalNodeNotFoundError:
        return CausalNodeNotFoundError(
            node_id=node_id, entity_type=entity_type, entity_id=entity_id, **kwargs
        )

    @staticmethod
    def node_already_exists(node_id: str, **kwargs) -> CausalNodeAlreadyExistsError:
        return CausalNodeAlreadyExistsError(node_id=node_id, **kwargs)

    @staticmethod
    def node_invalid_type(
        node_type: str, valid_types: list[str], **kwargs
    ) -> CausalNodeInvalidTypeError:
        return CausalNodeInvalidTypeError(node_type=node_type, valid_types=valid_types, **kwargs)

    @staticmethod
    def chain_incomplete(
        start_id: str, end_id: str, missing_nodes: list[str], **kwargs
    ) -> CausalChainIncompleteError:
        return CausalChainIncompleteError(
            start_id=start_id, end_id=end_id, missing_nodes=missing_nodes, **kwargs
        )

    @staticmethod
    def cycle_detected(cycle_nodes: list[str], **kwargs) -> CausalChainCycleDetectedError:
        return CausalChainCycleDetectedError(cycle_nodes=cycle_nodes, **kwargs)

    @staticmethod
    def relationship_not_found(
        source_id: str, target_id: str, **kwargs
    ) -> CausalRelationshipNotFoundError:
        return CausalRelationshipNotFoundError(source_id=source_id, target_id=target_id, **kwargs)

    @staticmethod
    def circular_reference(entities: list[str], **kwargs) -> CircularReferenceDetectedError:
        return CircularReferenceDetectedError(entities=entities, **kwargs)

    @staticmethod
    def why_query_failed(entity_id: str, reason: str, **kwargs) -> WhyQueryFailedError:
        return WhyQueryFailedError(entity_id=entity_id, reason=reason, **kwargs)

    @staticmethod
    def causality_not_found(entity_id: str, entity_type: str, **kwargs) -> CausalityNotFoundError:
        return CausalityNotFoundError(entity_id=entity_id, entity_type=entity_type, **kwargs)

    @staticmethod
    def invalid_relationship_strength(
        strength: float, **kwargs
    ) -> RelationshipStrengthInvalidError:
        return RelationshipStrengthInvalidError(strength=strength, **kwargs)


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "CausalChainBrokenError",
    "CausalChainCycleDetectedError",
    "CausalChainEmptyError",
    "CausalChainIncompleteError",
    "CausalChainNotFoundError",
    "CausalChainTooDeepError",
    "CausalNodeAlreadyExistsError",
    "CausalNodeCorruptedError",
    "CausalNodeHashMismatchError",
    "CausalNodeInvalidTypeError",
    "CausalNodeNotFoundError",
    "CausalRelationshipAlreadyExistsError",
    "CausalRelationshipInvalidError",
    "CausalRelationshipNotFoundError",
    "CausalityError",
    "CausalityErrorCode",
    "CausalityExceptionFactory",
    "CausalityInconsistentError",
    "CausalityNotFoundError",
    "CausalitySeverity",
    "CircularReferenceDetectedError",
    "ExplanationGenerationFailedError",
    "InvalidDirectionError",
    "InvalidQueryDepthError",
    "PathNotFoundError",
    "RelationshipStrengthInvalidError",
    "TraversalTooDeepError",
    "UnsupportedFormatError",
    "UnsupportedLanguageError",
    "WhyQueryFailedError",
    "WhyQueryTimeoutError",
]
