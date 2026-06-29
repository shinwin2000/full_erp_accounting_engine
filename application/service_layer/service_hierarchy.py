# service_hierarchy.py - Complete service for Hierarchy management

#!/usr/bin/env python3

"""
Module: service_hierarchy.py

Layer: 8 - Application / Service Layer

Responsibility:
    Service untuk mengelola hierarki (organisasi, akun, dll).
    Mempublikasikan HierarchyChangedEvent setiap perubahan struktur hierarki.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from ports.primary.event_publisher_port import EventPublisherPort

# Import domain events
from application.events import HierarchyChangedEvent

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class HierarchyType(str, Enum):
    """Jenis hierarki yang dikelola."""

    ORGANIZATION = "organization"
    ACCOUNT = "account"
    PRODUCT = "product"
    LOCATION = "location"
    COST_CENTER = "cost_center"


class HierarchyAction(str, Enum):
    """Action yang dilakukan pada hierarki."""

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    MOVE = "move"
    REORDER = "reorder"


# ============================================================================
# Domain Models
# ============================================================================


@dataclass(kw_only=True)
class HierarchyNode:
    """Node dalam hierarki."""

    id: UUID = field(default_factory=uuid4)
    parent_id: UUID | None = None
    name: str
    code: str
    hierarchy_type: HierarchyType
    level: int = 0
    description: str | None = None
    is_active: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID | None = None
    version: int = 1


# ============================================================================
# Exceptions
# ============================================================================


class HierarchyServiceError(Exception):
    pass


class HierarchyNodeNotFoundError(HierarchyServiceError):
    pass


class HierarchyCycleDetectedError(HierarchyServiceError):
    pass


# ============================================================================
# Main Service
# ============================================================================


class HierarchyService:
    """
    Service untuk mengelola hierarki.
    Mempublikasikan HierarchyChangedEvent setiap perubahan.
    """

    def __init__(self, event_publisher: EventPublisherPort | None = None):
        self._nodes: dict[UUID, HierarchyNode] = {}
        self._event_publisher = event_publisher
        self._stats = {"nodes_created": 0, "nodes_updated": 0, "nodes_deleted": 0}

        logger.info("HierarchyService initialized")

    async def create_node(
        self,
        name: str,
        code: str,
        hierarchy_type: str,
        parent_id: UUID | None = None,
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
        created_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> HierarchyNode:
        """Create a new node in the hierarchy."""
        # Check cycle
        if parent_id:
            await self._check_cycle(parent_id, None)

        # Determine level
        level = 0
        if parent_id:
            parent = self._nodes.get(parent_id)
            if parent:
                level = parent.level + 1

        node = HierarchyNode(
            parent_id=parent_id,
            name=name,
            code=code,
            hierarchy_type=HierarchyType(hierarchy_type),
            level=level,
            description=description,
            metadata=metadata or {},
            created_by=created_by,
            version=1,
        )

        self._nodes[node.id] = node
        self._stats["nodes_created"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            try:
                event = HierarchyChangedEvent(
                    aggregate_id=node.id,
                    aggregate_version=node.version,
                    node_id=node.id,
                    parent_id=node.parent_id,
                    node_name=node.name,
                    action=HierarchyAction.CREATE.value,
                    old_data=None,
                    new_data=node.__dict__,
                    hierarchy_type=node.hierarchy_type.value,
                    user_id=str(created_by) if created_by else "system",
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event, correlation_id)
                logger.debug(f"Published HierarchyChangedEvent for create {node.code}")
            except Exception as e:
                logger.warning(f"Failed to publish HierarchyChangedEvent: {e}")

        logger.info(f"Hierarchy node created: {node.code} ({node.hierarchy_type.value})")
        return node

    async def update_node(
        self,
        node_id: UUID,
        name: str | None = None,
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
        is_active: bool | None = None,
        updated_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> HierarchyNode:
        """Update an existing node."""
        node = self._nodes.get(node_id)
        if not node:
            raise HierarchyNodeNotFoundError(f"Node {node_id} not found")

        old_data = node.__dict__.copy()
        changes = {}

        if name is not None and name != node.name:
            changes["name"] = {"old": node.name, "new": name}
            node.name = name
        if description is not None and description != node.description:
            changes["description"] = {"old": node.description, "new": description}
            node.description = description
        if metadata is not None:
            changes["metadata"] = {"old": node.metadata, "new": metadata}
            node.metadata = metadata
        if is_active is not None and is_active != node.is_active:
            changes["is_active"] = {"old": node.is_active, "new": is_active}
            node.is_active = is_active

        if not changes:
            return node

        node.updated_at = datetime.now(UTC)
        node.version += 1
        self._nodes[node_id] = node
        self._stats["nodes_updated"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            try:
                event = HierarchyChangedEvent(
                    aggregate_id=node.id,
                    aggregate_version=node.version,
                    node_id=node.id,
                    parent_id=node.parent_id,
                    node_name=node.name,
                    action=HierarchyAction.UPDATE.value,
                    old_data=old_data,
                    new_data=node.__dict__,
                    hierarchy_type=node.hierarchy_type.value,
                    user_id=str(updated_by) if updated_by else "system",
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event, correlation_id)
                logger.debug(f"Published HierarchyChangedEvent for update {node.code}")
            except Exception as e:
                logger.warning(f"Failed to publish HierarchyChangedEvent: {e}")

        return node

    async def move_node(
        self,
        node_id: UUID,
        new_parent_id: UUID | None,
        moved_by: UUID,
        correlation_id: str | None = None,
    ) -> HierarchyNode:
        """Move a node to a different parent."""
        node = self._nodes.get(node_id)
        if not node:
            raise HierarchyNodeNotFoundError(f"Node {node_id} not found")

        old_parent_id = node.parent_id
        old_data = node.__dict__.copy()

        await self._check_cycle(new_parent_id, node_id)

        node.parent_id = new_parent_id
        node.updated_at = datetime.now(UTC)
        node.version += 1

        # Recalculate levels for subtree (simplified - just update level)
        if new_parent_id:
            parent = self._nodes.get(new_parent_id)
            node.level = parent.level + 1 if parent else 0
        else:
            node.level = 0

        self._nodes[node_id] = node
        self._stats["nodes_updated"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            try:
                event = HierarchyChangedEvent(
                    aggregate_id=node.id,
                    aggregate_version=node.version,
                    node_id=node.id,
                    parent_id=node.parent_id,
                    node_name=node.name,
                    action=HierarchyAction.MOVE.value,
                    old_data=old_data,
                    new_data=node.__dict__,
                    hierarchy_type=node.hierarchy_type.value,
                    user_id=str(moved_by),
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event, correlation_id)
                logger.debug(f"Published HierarchyChangedEvent for move {node.code}")
            except Exception as e:
                logger.warning(f"Failed to publish HierarchyChangedEvent: {e}")

        return node

    async def delete_node(
        self,
        node_id: UUID,
        deleted_by: UUID,
        correlation_id: str | None = None,
    ) -> bool:
        """Delete a node (only if it has no children)."""
        node = self._nodes.get(node_id)
        if not node:
            raise HierarchyNodeNotFoundError(f"Node {node_id} not found")

        # Check children
        children = [n for n in self._nodes.values() if n.parent_id == node_id]
        if children:
            raise HierarchyServiceError(f"Cannot delete node with {len(children)} children")

        old_data = node.__dict__.copy()
        del self._nodes[node_id]
        self._stats["nodes_deleted"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            try:
                event = HierarchyChangedEvent(
                    aggregate_id=node.id,
                    aggregate_version=node.version + 1,
                    node_id=node.id,
                    parent_id=node.parent_id,
                    node_name=node.name,
                    action=HierarchyAction.DELETE.value,
                    old_data=old_data,
                    new_data=None,
                    hierarchy_type=node.hierarchy_type.value,
                    user_id=str(deleted_by),
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event, correlation_id)
                logger.debug(f"Published HierarchyChangedEvent for delete {node.code}")
            except Exception as e:
                logger.warning(f"Failed to publish HierarchyChangedEvent: {e}")

        return True

    async def get_node(self, node_id: UUID) -> HierarchyNode | None:
        return self._nodes.get(node_id)

    async def get_children(self, parent_id: UUID) -> list[HierarchyNode]:
        return [n for n in self._nodes.values() if n.parent_id == parent_id]

    async def get_tree(self, root_id: UUID | None = None) -> list[dict[str, Any]]:
        """Get hierarchy tree starting from root."""
        if root_id is None:
            # Find root nodes (no parent)
            roots = [n for n in self._nodes.values() if n.parent_id is None]
            return [self._build_tree(r.id) for r in roots]

        return [self._build_tree(root_id)]

    def _build_tree(self, node_id: UUID) -> dict[str, Any]:
        node = self._nodes.get(node_id)
        if not node:
            return {}
        children = self.get_children(node_id)
        return {
            "id": str(node.id),
            "name": node.name,
            "code": node.code,
            "level": node.level,
            "children": [self._build_tree(c.id) for c in children],
        }

    async def _check_cycle(self, new_parent_id: UUID | None, node_id: UUID | None) -> None:
        """Check if moving node would create a cycle."""
        if new_parent_id is None:
            return
        if node_id is not None and new_parent_id == node_id:
            raise HierarchyCycleDetectedError("Node cannot be its own parent")

        # Traverse up from new parent
        current = new_parent_id
        visited = set()
        while current:
            if current in visited:
                raise HierarchyCycleDetectedError("Cycle detected in hierarchy")
            visited.add(current)
            if node_id is not None and current == node_id:
                raise HierarchyCycleDetectedError("Moving would create a cycle")
            parent_node = self._nodes.get(current)
            if not parent_node:
                break
            current = parent_node.parent_id

    def get_stats(self) -> dict[str, int]:
        return self._stats.copy()


# ============================================================================
# Factory
# ============================================================================


async def create_hierarchy_service(
    event_publisher: EventPublisherPort | None = None,
) -> HierarchyService:
    return HierarchyService(event_publisher=event_publisher)


__all__ = [
    "HierarchyNode",
    "HierarchyNodeNotFoundError",
    "HierarchyService",
    "HierarchyServiceError",
    "HierarchyType",
    "HierarchyAction",
    "create_hierarchy_service",
]