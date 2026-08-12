#!/usr/bin/env python3
"""
Package: domain.causality
Layer: Domain / Causality

Responsibility:
    Mendefinisikan model kausalitas untuk melacak hubungan sebab-akibat
    antara intent, economic events, dan journal entries. Menyediakan
    kemampuan untuk membangun rantai kausalitas, query "why", dan
    menghasilkan narasi audit yang dapat dipahami manusia.

Audit:
    Setiap node kausalitas, hubungan, dan query tercatat.
"""

from __future__ import annotations

import logging

# ==================== AUDIT STORY BUILDER ====================
from .audit_story_builder import (
    AuditStory,
    AuditStoryBuilder,
    AuditStoryFormat,
    AuditStorySection,
    get_audit_story_builder,
)

# ==================== CAUSAL CHAIN BUILDER ====================
from .causal_chain_builder import (
    CausalChainBuilder,
    get_causal_chain_builder,
)

# ==================== CAUSAL NODE ====================
from .causal_node import (
    CausalDirection,
    CausalNode,
    CausalNodeService,
    CausalNodeType,
    get_causal_node_service,
)

# ==================== EXCEPTIONS ====================
from .causality_exceptions import (
    CausalChainCycleDetectedError,
    CausalChainIncompleteError,
    CausalChainTooDeepError,
    CausalityError,
    CausalityErrorCode,
    CausalityExceptionFactory,
    CausalityNotFoundError,
    CausalitySeverity,
    CausalNodeInvalidTypeError,
    CausalNodeNotFoundError,
    CausalRelationshipNotFoundError,
    CircularReferenceDetectedError,
    WhyQueryFailedError,
    WhyQueryTimeoutError,
)

# ==================== CAUSALITY TRACKER ====================
from .causality_tracker import (
    CausalityTracker,
    CausalRelationship,
    RelationshipType,
    get_causality_tracker,
)

# ==================== EXPLANATION GENERATOR ====================
from .explanation_generator import (
    ExplanationGenerator,
    ExplanationLanguage,
    ExplanationLevel,
    get_explanation_generator,
)

# ==================== WHY QUERY ENGINE ====================
from .why_query_engine import (
    WhyQueryDepth,
    WhyQueryEngine,
    WhyQueryResult,
    WhyQueryResultStatus,
    get_why_query_engine,
)

# ==================== LOGGING ====================
logger = logging.getLogger(__name__)

__version__ = "1.0.0"
__author__ = "ERP Accounting Engine Team"

logger.info(f"Domain Causality package loaded (version {__version__})")

# ==================== EXPORTS ====================
__all__ = [
    # Audit Story Builder
    "AuditStory",
    "AuditStoryBuilder",
    "AuditStoryFormat",
    "AuditStorySection",
    # Causal Chain Builder
    "CausalChainBuilder",
    # Causal Chain Exceptions
    "CausalChainCycleDetectedError",
    "CausalChainIncompleteError",
    "CausalChainTooDeepError",
    # Causal Node
    "CausalDirection",
    "CausalNode",
    "CausalNodeInvalidTypeError",
    "CausalNodeNotFoundError",
    "CausalNodeService",
    "CausalNodeType",
    # Causality Tracker
    "CausalRelationship",
    "CausalRelationshipNotFoundError",
    # Causality Exceptions
    "CausalityError",
    "CausalityErrorCode",
    "CausalityExceptionFactory",
    "CausalityNotFoundError",
    "CausalitySeverity",
    # Causality Tracker
    "CausalityTracker",
    "CircularReferenceDetectedError",
    # Explanation Generator
    "ExplanationGenerator",
    "ExplanationLanguage",
    "ExplanationLevel",
    # Relationship Type
    "RelationshipType",
    # Why Query Engine
    "WhyQueryDepth",
    "WhyQueryEngine",
    "WhyQueryFailedError",
    "WhyQueryResult",
    "WhyQueryResultStatus",
    "WhyQueryTimeoutError",
    # Getters
    "get_audit_story_builder",
    "get_causal_chain_builder",
    "get_causal_node_service",
    "get_causality_tracker",
    "get_explanation_generator",
    "get_why_query_engine",
]
