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
from uuid import UUID

# ==================== LOGGING ====================
logger = logging.getLogger(__name__)

__version__ = "1.0.0"
__author__ = "ERP Accounting Engine Team"

# ==================== CAUSAL NODE ====================
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

# ==================== LOG PACKAGE LOADED ====================
logger.info(f"Domain Causality package loaded (version {__version__})")

# ==================== EXPORTS ====================
__all__ = [
    # Causal Node
    "CausalNodeType",
    "CausalDirection",
    "CausalNode",
    "CausalNodeService",
    "get_causal_node_service",
    # Causal Chain Builder
    "CausalChainBuilder",
    "get_causal_chain_builder",
    # Causality Tracker
    "RelationshipType",
    "CausalRelationship",
    "CausalityTracker",
    "get_causality_tracker",
    # Explanation Generator
    "ExplanationLevel",
    "ExplanationLanguage",
    "ExplanationGenerator",
    "get_explanation_generator",
    # Why Query Engine
    "WhyQueryDepth",
    "WhyQueryResultStatus",
    "WhyQueryResult",
    "WhyQueryEngine",
    "get_why_query_engine",
    # Audit Story Builder
    "AuditStoryFormat",
    "AuditStorySection",
    "AuditStory",
    "AuditStoryBuilder",
    "get_audit_story_builder",
    # Exceptions
    "CausalityErrorCode",
    "CausalitySeverity",
    "CausalityError",
    "CausalNodeNotFoundError",
    "CausalNodeInvalidTypeError",
    "CausalChainIncompleteError",
    "CausalChainCycleDetectedError",
    "CausalChainTooDeepError",
    "CausalRelationshipNotFoundError",
    "CircularReferenceDetectedError",
    "WhyQueryFailedError",
    "WhyQueryTimeoutError",
    "CausalityNotFoundError",
    "CausalityExceptionFactory",
]
