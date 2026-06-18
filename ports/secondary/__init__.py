#!/usr/bin/env python3
"""
Package: ports.secondary
Layer: Ports (Secondary)

Responsibility:
    Mendefinisikan antarmuka (ports) yang diimplementasikan oleh adapter
    sekunder (misalnya repository implementations, message brokers, file storage,
    external API clients). Ports ini adalah abstraksi yang digunakan oleh
    lapisan application dan domain untuk berkomunikasi dengan infrastruktur
    dan sistem eksternal.

Modules exported:
    - read_model_projection_port   : Projection & read model handling
    - snapshot_store_port          : Snapshot storage for aggregate states
    - cqrs_query_handler_port      : Query bus and handler for CQRS read side
    - analytics_export_port        : Data export to various formats and destinations

Audit:
    Setiap penggunaan port ini akan tercatat dalam audit log masing-masing.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import UUID

# ==================== ANALYTICS EXPORT ====================
from .analytics_export_port import (
    AnalyticsExportPort,
    CompressionType,
    DeliveryMethod,
    ExportFormat,
    ExportJob,
    ExportStatus,
)

# ==================== CQRS QUERY HANDLER ====================
from .cqrs_query_handler_port import (
    BaseQueryHandler,
    CQRSQueryHandlerPort,
    FilterCondition,
    Pagination,
    Query,
    QueryCacheStrategy,
    QueryHandler,
    QueryResult,
    QueryStatus,
    apply_filters,
    apply_pagination,
    apply_sorting,
)

# ==================== READ MODEL PROJECTION ====================
from .read_model_projection_port import (
    BaseProjector,
    Checkpoint,
    ProjectionError,
    ProjectionEvent,
    ProjectionStatus,
    ProjectionVersion,
    Projector,
    ReadModelProjectionPort,
)

# ==================== SNAPSHOT STORE ====================
from .snapshot_store_port import (
    Snapshot,
    SnapshotCompression,
    SnapshotMetadata,
    SnapshotStatus,
    SnapshotStorePort,
)

# ==================== LOGGER ====================

logger = logging.getLogger(__name__)

# ==================== EXPORTS ====================

__all__ = [
    # Read Model Projection
    "ReadModelProjectionPort",
    "Projector",
    "BaseProjector",
    "ProjectionEvent",
    "Checkpoint",
    "ProjectionStatus",
    "ProjectionVersion",
    "ProjectionError",
    # Snapshot Store
    "SnapshotStorePort",
    "Snapshot",
    "SnapshotMetadata",
    "SnapshotCompression",
    "SnapshotStatus",
    # CQRS Query Handler
    "CQRSQueryHandlerPort",
    "QueryHandler",
    "BaseQueryHandler",
    "Query",
    "QueryResult",
    "Pagination",
    "FilterCondition",
    "QueryStatus",
    "QueryCacheStrategy",
    "apply_filters",
    "apply_sorting",
    "apply_pagination",
    # Analytics Export
    "AnalyticsExportPort",
    "ExportJob",
    "ExportFormat",
    "CompressionType",
    "DeliveryMethod",
    "ExportStatus",
]

# ==================== MODULE INFO ====================

__version__ = "1.0.0"
__author__ = "ERP Accounting Engine Team"

logger.info(f"Ports secondary package loaded (version {__version__})")
