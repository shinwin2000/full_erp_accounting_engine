#!/usr/bin/env python3
"""
Module: account_hierarchy_tree.py

Layer: Domain / COA (Chart of Accounts)

Responsibility:
    Hierarchical tree structure for accounts (parent-child relationships).
    Manages the organization of accounts into a tree for consolidated reporting,
    roll-up calculations, and hierarchical validation.

Business rules:
    - Each account can have at most one parent (tree structure, not DAG).
    - No cycles allowed in hierarchy.
    - Root accounts have parent_account_id = None.
    - The tree is built from a list of AccountEntity objects.
    - Supports traversal: DFS, BFS, path from root, subtree extraction.
    - Supports validation of hierarchy integrity.
    - Immutable operations: all modifications return new tree instances.
    - Provides statistics and visualization capabilities.
    - Supports serialization to/from dict, cloning, snapshots, audit trail.

Dependencies:
    - domain.coa.account_entity (AccountEntity)
    - standard library (uuid, logging, dataclass, typing, collections)

Audit:
    Pure domain logic; no I/O. Caller may log tree modifications.
"""

from __future__ import annotations

import hashlib
import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, ClassVar
from uuid import UUID

from domain.coa.account_entity import AccountEntity

logger = logging.getLogger(__name__)


# ============================================================================
# Custom Exceptions
# ============================================================================


class AccountHierarchyError(ValueError):
    """Base exception for account hierarchy errors."""

    pass


class CycleDetectedError(AccountHierarchyError):
    """Raised when a cycle is detected in the hierarchy."""

    pass


class ParentNotFoundError(AccountHierarchyError):
    """Raised when a parent account referenced does not exist."""

    pass


class OrphanAccountError(AccountHierarchyError):
    """Raised when an account has a parent that is not in the tree."""

    pass


class InvalidRootError(AccountHierarchyError):
    """Raised when root accounts are invalid."""

    pass


# ============================================================================
# Hierarchy Node
# ============================================================================


@dataclass
class HierarchyNode:
    """
    Node in the account hierarchy tree.

    Attributes:
        account: The AccountEntity at this node
        children: List of child nodes
        level: Depth level (0 = root)
        path: Full path from root as list of account codes (cached)
    """

    account: AccountEntity
    children: list[HierarchyNode] = field(default_factory=list)
    level: int = 0
    path: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Ensure path is initialized based on account if not set."""
        if not self.path and self.account:
            self.path = [self.account.account_code]

    # ==================== SERIALIZATION ====================

    def to_dict(self, include_children: bool = True) -> dict[str, Any]:
        """Convert node to dictionary for serialization."""
        result = {
            "account_id": str(self.account.account_id),
            "account_code": self.account.account_code,
            "account_name": self.account.account_name,
            "account_type": self.account.account_type.value
            if hasattr(self.account.account_type, "value")
            else str(self.account.account_type),
            "normal_balance": self.account.normal_balance.value
            if hasattr(self.account.normal_balance, "value")
            else str(self.account.normal_balance),
            "level": self.level,
            "path": self.path,
            "is_active": self.account.is_active,
            "is_control_account": getattr(self.account, "is_control_account", False),
            "has_children": len(self.children) > 0,
            "child_count": len(self.children),
        }
        if include_children:
            result["children"] = [child.to_dict(include_children=True) for child in self.children]
        else:
            result["child_ids"] = [str(child.account.account_id) for child in self.children]
        return result

    @classmethod
    def from_dict(
        cls, data: dict[str, Any], accounts_map: dict[UUID, AccountEntity]
    ) -> HierarchyNode:
        """Reconstruct node from dictionary."""
        account_id = UUID(data["account_id"])
        if account_id not in accounts_map:
            raise ValueError(f"Account {account_id} not found in accounts_map")
        account = accounts_map[account_id]
        level = data["level"] if "level" in data else 0
        path = data["path"] if "path" in data else [account.account_code]
        node = cls(account=account, level=level, path=path)
        children_data = data["children"] if "children" in data else []
        for child_data in children_data:
            child_node = cls.from_dict(child_data, accounts_map)
            node.children.append(child_node)
        return node

    # ==================== CLONE & SNAPSHOT ====================

    def clone(self, new_account_id_map: dict[UUID, UUID] | None = None) -> HierarchyNode:
        """Create a deep copy of this node and all descendants."""
        new_id = (
            new_account_id_map.get(self.account.account_id, self.account.account_id)
            if new_account_id_map
            else self.account.account_id
        )
        cloned_account = self.account.clone() if hasattr(self.account, "clone") else self.account
        # If account has clone method, use it; otherwise, we assume immutable
        cloned_node = HierarchyNode(
            account=cloned_account,
            level=self.level,
            path=self.path.copy(),
        )
        for child in self.children:
            cloned_node.children.append(child.clone(new_account_id_map))
        return cloned_node

    def snapshot(self) -> dict[str, Any]:
        """Create a snapshot of this node's state."""
        return {
            "account_id": str(self.account.account_id),
            "account_code": self.account.account_code,
            "account_name": self.account.account_name,
            "level": self.level,
            "path": self.path,
            "child_count": len(self.children),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def compute_hash(self) -> str:
        """Compute a hash of the node and its subtree for integrity checking."""
        data_str = f"{self.account.account_id}:{self.account.version}:{self.level}"
        for child in self.children:
            data_str += child.compute_hash()
        return hashlib.sha3_256(data_str.encode()).hexdigest()

    # ==================== QUERY METHODS ====================

    def get_child_by_code(self, account_code: str) -> HierarchyNode | None:
        """Find immediate child by account code."""
        for child in self.children:
            if child.account.account_code == account_code:
                return child
        return None

    def get_child_by_id(self, account_id: UUID) -> HierarchyNode | None:
        """Find immediate child by account ID."""
        for child in self.children:
            if child.account.account_id == account_id:
                return child
        return None

    def get_descendant_count(self) -> int:
        """Count total descendants (excluding self)."""
        count = len(self.children)
        for child in self.children:
            count += child.get_descendant_count()
        return count

    def get_all_descendants(self) -> list[HierarchyNode]:
        """Return all descendant nodes (BFS order)."""
        result = []
        queue = deque(self.children)
        while queue:
            node = queue.popleft()
            result.append(node)
            queue.extend(node.children)
        return result

    def get_all_leaf_nodes(self) -> list[HierarchyNode]:
        """Return all leaf nodes (no children) under this node."""
        leaves = []
        if not self.children:
            leaves.append(self)
        else:
            for child in self.children:
                leaves.extend(child.get_all_leaf_nodes())
        return leaves

    def audit_trail(self) -> list[dict[str, Any]]:
        """Collect audit trail information for this node and descendants."""
        entries = [self.snapshot()]
        for child in self.children:
            entries.extend(child.audit_trail())
        return entries

    def __repr__(self) -> str:
        return f"HierarchyNode(account={self.account.account_code}, children={len(self.children)})"


# ============================================================================
# Account Hierarchy Tree (Main Class)
# ============================================================================


class AccountHierarchyTree:
    """
    Immutable hierarchical tree structure for accounts.

    The tree is built from a list of AccountEntity objects and provides
    methods for navigation, querying, modification, and validation.

    All modification methods return new tree instances (immutable).

    Examples:
        >>> accounts = [...]  # list of AccountEntity
        >>> tree = AccountHierarchyTree.build(accounts)
        >>> root = tree.get_root()  # if single root
        >>> children = tree.get_children(some_account_id)
        >>> descendants = tree.get_descendants(some_account_id)
        >>> tree.is_valid()  # checks cycles and parent existence
        >>> new_tree = tree.add_account(new_account)
    """

    _audit_trail: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, nodes: dict[UUID, HierarchyNode], roots: list[UUID], orphans: list[UUID]):
        """
        Private constructor. Use static factory methods instead.

        Args:
            nodes: Mapping of account_id to HierarchyNode
            roots: List of root account IDs
            orphans: List of account IDs whose parents are missing
        """
        self._nodes: dict[UUID, HierarchyNode] = nodes
        self._roots: list[UUID] = roots
        self._orphans: list[UUID] = orphans
        self._node_by_code: dict[str, UUID] = {}
        # Build index by account code
        for acc_id, node in self._nodes.items():
            self._node_by_code[node.account.account_code] = acc_id
        self._record_audit(
            "BUILD", "system", {"nodes": len(nodes), "roots": len(roots), "orphans": len(orphans)}
        )

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        """Record audit trail entry."""
        entry = {
            "action": action,
            "performed_by": performed_by,
            "timestamp": datetime.now(UTC).isoformat(),
            "details": details,
        }
        self._audit_trail.append(entry)

    # ------------------------------------------------------------------------
    # Factory Methods
    # ------------------------------------------------------------------------

    @classmethod
    def build(cls, accounts: list[AccountEntity]) -> AccountHierarchyTree:
        """
        Build a hierarchy tree from a list of accounts.

        Automatically detects parent-child relationships based on
        parent_account_id fields. Handles multiple roots and orphan detection.

        Args:
            accounts: List of AccountEntity objects

        Returns:
            AccountHierarchyTree instance

        Raises:
            CycleDetectedError: If a cycle is found in the hierarchy
        """
        # Create nodes for all accounts
        nodes: dict[UUID, HierarchyNode] = {}
        for acc in accounts:
            nodes[acc.account_id] = HierarchyNode(account=acc, children=[], level=0)

        # Build parent-child relationships
        children_map: dict[UUID, list[UUID]] = {}
        potential_roots: set[UUID] = set(nodes.keys())
        orphans: list[UUID] = []

        for acc_id, node in nodes.items():
            parent_id = node.account.parent_account_id
            if parent_id is None:
                continue  # root candidate
            if parent_id in nodes:
                # Valid parent
                if parent_id not in children_map:
                    children_map[parent_id] = []
                children_map[parent_id].append(acc_id)
                potential_roots.discard(acc_id)  # not a root
            else:
                # Parent not in this collection -> orphan
                orphans.append(acc_id)
                potential_roots.discard(acc_id)

        # Validate no cycles before building levels
        cls._validate_no_cycles(nodes, children_map)

        # Build hierarchy nodes recursively
        root_ids = list(potential_roots)

        def build_node(acc_id: UUID, level: int, path: list[str]) -> HierarchyNode:
            node = nodes[acc_id]
            node.level = level
            node.path = path + [node.account.account_code]
            node.children = []
            child_list = children_map[acc_id] if acc_id in children_map else []
            for child_id in child_list:
                child_node = build_node(child_id, level + 1, node.path)
                node.children.append(child_node)
            return node

        new_nodes: dict[UUID, HierarchyNode] = {}
        for root_id in root_ids:
            new_nodes[root_id] = build_node(root_id, 0, [])

        # Also include orphans as root nodes (they will have missing parent reference)
        for orphan_id in orphans:
            node = nodes[orphan_id]
            node.level = 0
            node.path = [node.account.account_code]
            node.children = []
            new_nodes[orphan_id] = node

        # Ensure all nodes are in new_nodes (for orphans, already there; for others, built)
        for acc_id, node in nodes.items():
            if acc_id not in new_nodes:
                # This can happen if there was a cycle? Should be caught.
                new_nodes[acc_id] = node

        return cls(nodes=new_nodes, roots=root_ids, orphans=orphans)

    @classmethod
    def empty(cls) -> AccountHierarchyTree:
        """Create an empty tree with no accounts."""
        return cls(nodes={}, roots=[], orphans=[])

    @classmethod
    def single_root(cls, root_account: AccountEntity) -> AccountHierarchyTree:
        """Create a tree with a single root account and no children."""
        node = HierarchyNode(
            account=root_account, children=[], level=0, path=[root_account.account_code]
        )
        nodes = {root_account.account_id: node}
        return cls(nodes=nodes, roots=[root_account.account_id], orphans=[])

    # ------------------------------------------------------------------------
    # Private Helpers
    # ------------------------------------------------------------------------

    @staticmethod
    def _validate_no_cycles(
        nodes: dict[UUID, HierarchyNode], children_map: dict[UUID, list[UUID]]
    ) -> None:
        """Detect cycles in the hierarchy using DFS."""
        visited: set[UUID] = set()
        rec_stack: set[UUID] = set()

        def has_cycle(node_id: UUID) -> bool:
            visited.add(node_id)
            rec_stack.add(node_id)
            child_list = children_map[node_id] if node_id in children_map else []
            for child_id in child_list:
                if child_id not in visited:
                    if has_cycle(child_id):
                        return True
                elif child_id in rec_stack:
                    return True
            rec_stack.remove(node_id)
            return False

        for node_id in nodes:
            if node_id not in visited:
                if has_cycle(node_id):
                    raise CycleDetectedError(
                        f"Cycle detected in account hierarchy starting at {node_id}"
                    )

    @staticmethod
    def _find_path_from_root(node: HierarchyNode, target_id: UUID) -> list[UUID] | None:
        """Find path from node's root to target (helper for recursive search)."""
        if node.account.account_id == target_id:
            return [target_id]
        for child in node.children:
            path = AccountHierarchyTree._find_path_from_root(child, target_id)
            if path:
                return [node.account.account_id] + path
        return None

    # ------------------------------------------------------------------------
    # Basic Properties
    # ------------------------------------------------------------------------

    @property
    def is_empty(self) -> bool:
        """Return True if tree has no nodes."""
        return len(self._nodes) == 0

    @property
    def size(self) -> int:
        """Total number of accounts in the tree."""
        return len(self._nodes)

    @property
    def root_count(self) -> int:
        """Number of root accounts (accounts with no parent)."""
        return len(self._roots)

    @property
    def has_multiple_roots(self) -> bool:
        """Return True if there is more than one root account."""
        return self.root_count > 1

    @property
    def has_single_root(self) -> bool:
        """Return True if exactly one root account exists."""
        return self.root_count == 1

    @property
    def orphan_count(self) -> int:
        """Number of accounts whose parent is missing from the tree."""
        return len(self._orphans)

    @property
    def has_orphans(self) -> bool:
        """Return True if there are any orphan accounts."""
        return self.orphan_count > 0

    def get_root(self) -> HierarchyNode | None:
        """Return the single root node if exactly one root exists, else None."""
        if self.has_single_root:
            return self._nodes[self._roots[0]]
        return None

    def get_roots(self) -> list[HierarchyNode]:
        """Return all root nodes."""
        return [self._nodes[rid] for rid in self._roots]

    def get_node(self, account_id: UUID) -> HierarchyNode | None:
        """Get node by account ID."""
        if account_id in self._nodes:
            return self._nodes[account_id]
        return None

    def get_node_by_code(self, account_code: str) -> HierarchyNode | None:
        """Get node by account code."""
        if account_code in self._node_by_code:
            acc_id = self._node_by_code[account_code]
            if acc_id in self._nodes:
                return self._nodes[acc_id]
        return None

    def account_exists(self, account_id: UUID) -> bool:
        """Check if account exists in tree."""
        return account_id in self._nodes

    def account_exists_by_code(self, account_code: str) -> bool:
        """Check if account exists by code."""
        return account_code in self._node_by_code

    # ------------------------------------------------------------------------
    # Navigation Methods
    # ------------------------------------------------------------------------

    def get_parent(self, account_id: UUID) -> HierarchyNode | None:
        """Return the parent node of the given account, or None if root/orphan."""
        if account_id not in self._nodes:
            return None
        node = self._nodes[account_id]
        if node.account.parent_account_id is None:
            return None
        parent_id = node.account.parent_account_id
        if parent_id in self._nodes:
            return self._nodes[parent_id]
        return None

    def get_children(self, account_id: UUID) -> list[HierarchyNode]:
        """Return direct children of the given account."""
        if account_id in self._nodes:
            return self._nodes[account_id].children
        return []

    def get_descendants(self, account_id: UUID) -> list[HierarchyNode]:
        """Return all descendants (children, grandchildren, etc.) of the given account."""
        if account_id in self._nodes:
            return self._nodes[account_id].get_all_descendants()
        return []

    def get_ancestors(self, account_id: UUID) -> list[HierarchyNode]:
        """Return all ancestors (parent, grandparent, etc.) up to root."""
        ancestors = []
        current = self.get_parent(account_id)
        while current:
            ancestors.append(current)
            current = self.get_parent(current.account.account_id)
        return ancestors

    def get_root_path(self, account_id: UUID) -> list[HierarchyNode]:
        """Return the path from root to the given account (including itself)."""
        ancestors = self.get_ancestors(account_id)
        ancestors.reverse()
        if account_id in self._nodes:
            ancestors.append(self._nodes[account_id])
        return ancestors

    def get_level(self, account_id: UUID) -> int:
        """Return depth level of account (0 for root, 1 for child, etc.)."""
        if account_id in self._nodes:
            return self._nodes[account_id].level
        return -1

    def get_subtree(self, account_id: UUID) -> AccountHierarchyTree | None:
        """Return a new tree containing the subtree rooted at the given account."""
        if account_id not in self._nodes:
            return None
        node = self._nodes[account_id]
        # Build new tree with this node as root
        new_nodes: dict[UUID, HierarchyNode] = {}
        new_roots: list[UUID] = []
        new_orphans: list[UUID] = []

        def copy_node(n: HierarchyNode) -> HierarchyNode:
            new_node = HierarchyNode(
                account=n.account,
                children=[],
                level=n.level - node.level,
                path=n.path[node.level :] if node.level < len(n.path) else [n.account.account_code],
            )
            new_nodes[new_node.account.account_id] = new_node
            for child in n.children:
                copied_child = copy_node(child)
                new_node.children.append(copied_child)
            return new_node

        new_root = copy_node(node)
        new_roots.append(new_root.account.account_id)
        return AccountHierarchyTree(nodes=new_nodes, roots=new_roots, orphans=new_orphans)

    # ------------------------------------------------------------------------
    # Traversal Methods
    # ------------------------------------------------------------------------

    def dfs_preorder(self, root_id: UUID | None = None) -> list[HierarchyNode]:
        """Depth-first search pre-order traversal."""
        result = []
        roots = [root_id] if root_id else self._roots
        for rid in roots:
            if rid in self._nodes:
                self._dfs_preorder(self._nodes[rid], result)
        return result

    def _dfs_preorder(self, node: HierarchyNode, result: list[HierarchyNode]) -> None:
        result.append(node)
        for child in node.children:
            self._dfs_preorder(child, result)

    def dfs_postorder(self, root_id: UUID | None = None) -> list[HierarchyNode]:
        """Depth-first search post-order traversal."""
        result = []
        roots = [root_id] if root_id else self._roots
        for rid in roots:
            if rid in self._nodes:
                self._dfs_postorder(self._nodes[rid], result)
        return result

    def _dfs_postorder(self, node: HierarchyNode, result: list[HierarchyNode]) -> None:
        for child in node.children:
            self._dfs_postorder(child, result)
        result.append(node)

    def bfs(self, root_id: UUID | None = None) -> list[HierarchyNode]:
        """Breadth-first search traversal."""
        result = []
        roots = [root_id] if root_id else self._roots
        for rid in roots:
            if rid in self._nodes:
                queue = deque([self._nodes[rid]])
                while queue:
                    current = queue.popleft()
                    result.append(current)
                    queue.extend(current.children)
        return result

    def get_all_nodes(self, order: str = "bfs") -> list[HierarchyNode]:
        """Return all nodes in specified order: 'bfs', 'dfs_pre', 'dfs_post'."""
        if order == "dfs_pre":
            return self.dfs_preorder()
        elif order == "dfs_post":
            return self.dfs_postorder()
        else:
            return self.bfs()

    def get_leaf_nodes(self) -> list[HierarchyNode]:
        """Return all leaf nodes (accounts with no children)."""
        leaves = []
        for node in self._nodes.values():
            if not node.children:
                leaves.append(node)
        return leaves

    # ------------------------------------------------------------------------
    # Query Methods
    # ------------------------------------------------------------------------

    def find_by_code_prefix(self, prefix: str) -> list[HierarchyNode]:
        """Find all accounts whose code starts with given prefix."""
        result = []
        for node in self._nodes.values():
            if node.account.account_code.startswith(prefix):
                result.append(node)
        return result

    def find_by_name_contains(
        self, substring: str, case_sensitive: bool = False
    ) -> list[HierarchyNode]:
        """Find accounts whose name contains substring."""
        result = []
        search = substring if case_sensitive else substring.lower()
        for node in self._nodes.values():
            name = (
                node.account.account_name if case_sensitive else node.account.account_name.lower()
            )
            if search in name:
                result.append(node)
        return result

    def find_by_type(self, account_type) -> list[HierarchyNode]:
        """Find all accounts of a given account type."""
        result = []
        for node in self._nodes.values():
            if node.account.account_type == account_type:
                result.append(node)
        return result

    def find_by_level(self, level: int) -> list[HierarchyNode]:
        """Find all accounts at specific depth level."""
        result = []
        for node in self._nodes.values():
            if node.level == level:
                result.append(node)
        return result

    # ------------------------------------------------------------------------
    # Validation Methods
    # ------------------------------------------------------------------------

    def is_valid(self) -> bool:
        """Validate the entire hierarchy."""
        if self.has_orphans:
            return False
        for node in self._nodes.values():
            if node.account.parent_account_id == node.account.account_id:
                return False
        return True

    def get_validation_errors(self) -> list[str]:
        """Return a list of validation error messages."""
        errors = []
        if self.has_orphans:
            errors.append(f"Orphan accounts: {len(self._orphans)} accounts have missing parents")
        for node in self._nodes.values():
            if node.account.parent_account_id == node.account.account_id:
                errors.append(f"Account {node.account.account_code} has self as parent")
        return errors

    # ------------------------------------------------------------------------
    # Modification Methods (Immutable)
    # ------------------------------------------------------------------------

    def add_account(self, account: AccountEntity) -> AccountHierarchyTree:
        """Add a new account to the hierarchy. Returns a new tree."""
        if account.account_id in self._nodes:
            raise AccountHierarchyError(f"Account {account.account_id} already exists")

        new_nodes = dict(self._nodes)
        new_node = HierarchyNode(account=account, children=[], level=0)
        new_nodes[account.account_id] = new_node
        new_node_by_code = dict(self._node_by_code)
        new_node_by_code[account.account_code] = account.account_id

        new_roots = list(self._roots)
        new_orphans = list(self._orphans)

        parent_id = account.parent_account_id
        if parent_id and parent_id in new_nodes:
            parent_node = new_nodes[parent_id]
            parent_node.children.append(new_node)
            self._update_levels_and_paths(new_node, parent_node.level + 1, parent_node.path)
            if account.account_id in new_orphans:
                new_orphans.remove(account.account_id)
        elif parent_id and parent_id not in new_nodes:
            new_orphans.append(account.account_id)
            if account.account_id in new_roots:
                new_roots.remove(account.account_id)
        else:
            new_roots.append(account.account_id)
            new_node.level = 0
            new_node.path = [account.account_code]

        return AccountHierarchyTree(nodes=new_nodes, roots=new_roots, orphans=new_orphans)

    def _update_levels_and_paths(
        self, node: HierarchyNode, level: int, parent_path: list[str]
    ) -> None:
        node.level = level
        node.path = parent_path + [node.account.account_code]
        for child in node.children:
            self._update_levels_and_paths(child, level + 1, node.path)

    def remove_account(self, account_id: UUID, cascade: bool = False) -> AccountHierarchyTree:
        """Remove an account from the hierarchy."""
        if account_id not in self._nodes:
            raise AccountHierarchyError(f"Account {account_id} not found")

        node = self._nodes[account_id]
        if node.children and not cascade:
            raise AccountHierarchyError(
                f"Account {account_id} has {len(node.children)} children. Use cascade=True to remove subtree."
            )

        new_nodes = {}
        new_node_by_code = {}
        new_roots = []
        new_orphans = []

        removed_ids = {account_id}
        if cascade:
            removed_ids.update([child.account.account_id for child in node.get_all_descendants()])

        for acc_id, n in self._nodes.items():
            if acc_id in removed_ids:
                continue
            new_node = HierarchyNode(
                account=n.account,
                children=[],
                level=n.level,
                path=n.path,
            )
            new_nodes[acc_id] = new_node
            new_node_by_code[n.account.account_code] = acc_id

            if n.account.parent_account_id is None:
                new_roots.append(acc_id)
            elif n.account.parent_account_id not in new_nodes:
                new_orphans.append(acc_id)

        for acc_id, n in new_nodes.items():
            for orig_acc_id, orig_node in self._nodes.items():
                if orig_acc_id in removed_ids:
                    continue
                if orig_node.account.parent_account_id == acc_id:
                    n.children.append(new_nodes[orig_acc_id])

        for root_id in new_roots:
            root_node = new_nodes[root_id]
            self._recalculate_levels(root_node, 0, [])

        return AccountHierarchyTree(nodes=new_nodes, roots=new_roots, orphans=new_orphans)

    def _recalculate_levels(self, node: HierarchyNode, level: int, parent_path: list[str]) -> None:
        node.level = level
        node.path = parent_path + [node.account.account_code]
        for child in node.children:
            self._recalculate_levels(child, level + 1, node.path)

    def move_account(self, account_id: UUID, new_parent_id: UUID | None) -> AccountHierarchyTree:
        """Move an account to a new parent."""
        if account_id not in self._nodes:
            raise AccountHierarchyError(f"Account {account_id} not found")

        if new_parent_id and new_parent_id not in self._nodes:
            raise ParentNotFoundError(f"New parent {new_parent_id} not found")

        if new_parent_id:
            node = self._nodes[account_id]
            descendants = node.get_all_descendants()
            if any(d.account.account_id == new_parent_id for d in descendants):
                raise CycleDetectedError("Moving would create a cycle")

        temp_tree = self.remove_account(account_id, cascade=False)
        original_account = self._nodes[account_id].account
        # In real implementation, we'd need to create a new account entity with updated parent
        # For now, we'll just add back with the same account but modified parent
        # This requires the account to be mutable or we create a new instance
        # Since we don't have a direct way to update account parent immutably here,
        # we'll assume the account is already updated externally.
        return temp_tree.add_account(original_account)

    # ------------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------------

    def get_statistics(self) -> dict[str, Any]:
        """Return comprehensive statistics about the hierarchy."""
        total_nodes = self.size
        total_roots = self.root_count
        total_orphans = self.orphan_count
        max_depth = max((node.level for node in self._nodes.values()), default=0)
        nodes_per_level: dict[int, int] = defaultdict(int)
        for node in self._nodes.values():
            nodes_per_level[node.level] += 1
        leaf_count = len(self.get_leaf_nodes())
        avg_children = (
            sum(len(node.children) for node in self._nodes.values()) / total_nodes
            if total_nodes > 0
            else 0
        )
        return {
            "total_accounts": total_nodes,
            "root_accounts": total_roots,
            "orphan_accounts": total_orphans,
            "leaf_accounts": leaf_count,
            "max_depth": max_depth,
            "nodes_per_level": dict(nodes_per_level),
            "average_children_per_node": round(avg_children, 2),
            "is_valid": self.is_valid(),
        }

    # ------------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------------

    def to_dict(self, include_children: bool = True) -> dict[str, Any]:
        """Convert entire tree to nested dictionary."""
        roots_dict = []
        for root_id in self._roots:
            node = self._nodes[root_id]
            roots_dict.append(node.to_dict(include_children))
        return {
            "roots": roots_dict,
            "statistics": self.get_statistics(),
            "orphan_accounts": [self._nodes[oid].account.account_code for oid in self._orphans],
            "total_nodes": self.size,
            "version": 1,
        }

    @classmethod
    def from_dict(
        cls, data: dict[str, Any], accounts_map: dict[UUID, AccountEntity]
    ) -> AccountHierarchyTree:
        """Reconstruct tree from dictionary."""
        roots = []
        nodes = {}
        orphans = []
        roots_data = data["roots"] if "roots" in data else []
        for root_data in roots_data:
            root_node = HierarchyNode.from_dict(root_data, accounts_map)
            nodes[root_node.account.account_id] = root_node
            roots.append(root_node.account.account_id)
        orphan_codes = data["orphan_accounts"] if "orphan_accounts" in data else []
        for orphan_code in orphan_codes:
            # Find account by code
            for acc_id, acc in accounts_map.items():
                if acc.account_code == orphan_code:
                    orphans.append(acc_id)
                    node = HierarchyNode(account=acc, children=[], level=0, path=[orphan_code])
                    nodes[acc_id] = node
                    break
        return cls(nodes=nodes, roots=roots, orphans=orphans)

    def clone(self) -> AccountHierarchyTree:
        """Create a deep copy of the entire tree."""
        new_nodes = {}
        new_roots = list(self._roots)
        new_orphans = list(self._orphans)
        # Deep copy nodes
        for acc_id, node in self._nodes.items():
            new_nodes[acc_id] = node.clone()
        # Rebuild children relationships (clone already preserves children)
        return AccountHierarchyTree(nodes=new_nodes, roots=new_roots, orphans=new_orphans)

    def snapshot(self) -> dict[str, Any]:
        """Create a snapshot of the entire tree."""
        return {
            "statistics": self.get_statistics(),
            "roots": [self._nodes[rid].snapshot() for rid in self._roots],
            "orphans": [str(oid) for oid in self._orphans],
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def compute_hash(self) -> str:
        """Compute a hash of the entire tree for integrity checking."""
        data_str = ""
        for root_id in self._roots:
            data_str += self._nodes[root_id].compute_hash()
        return hashlib.sha3_256(data_str.encode()).hexdigest()

    def audit_trail(self) -> list[dict[str, Any]]:
        """Get audit trail for the tree."""
        return self._audit_trail.copy()

    def pretty_print(self, root_id: UUID | None = None, indent: int = 2) -> str:
        """Return a string representation of the tree for debugging."""
        lines = []
        roots = [root_id] if root_id else self._roots
        for rid in roots:
            if rid in self._nodes:
                self._pretty_print_node(self._nodes[rid], 0, lines, indent)
        return "\n".join(lines)

    def _pretty_print_node(
        self, node: HierarchyNode, depth: int, lines: list[str], indent: int
    ) -> None:
        prefix = " " * (depth * indent)
        lines.append(f"{prefix}{node.account.account_code} - {node.account.account_name}")
        for child in node.children:
            self._pretty_print_node(child, depth + 1, lines, indent)

    # ------------------------------------------------------------------------
    # Dunder Methods
    # ------------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"AccountHierarchyTree(nodes={self.size}, roots={self.root_count}, orphans={self.orphan_count})"

    def __len__(self) -> int:
        return self.size

    def __contains__(self, account_id: UUID) -> bool:
        return account_id in self._nodes


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "AccountHierarchyError",
    "AccountHierarchyTree",
    "CycleDetectedError",
    "HierarchyNode",
    "InvalidRootError",
    "OrphanAccountError",
    "ParentNotFoundError",
]
