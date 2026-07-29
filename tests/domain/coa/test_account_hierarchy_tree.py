"""
Tests for domain/coa/account_hierarchy_tree.py

Covers HierarchyNode (construction, serialization, clone, snapshot, hash,
query helpers) and AccountHierarchyTree (build/empty/single_root factories,
properties, navigation, traversal, query, validation, immutable
modification, statistics, serialization, dunder methods).

======================================================================
KNOWN BUGS IN THE SOURCE (verified by direct execution):

BUG-HIERARCHY-001 — `move_account(account_id, new_parent_id)` validates
that `new_parent_id` exists and that moving would not create a cycle, but
then does `temp_tree.add_account(original_account)` using the *original*,
unmodified `AccountEntity` object -- whose `parent_account_id` still
points at the OLD parent. The account therefore ends up back under its
original parent; `new_parent_id` has no actual effect. Confirmed with a
real tree: after `move_account(child, other_root.id)`, `get_parent(child)`
still returns the original parent, not `other_root`.

BUG-HIERARCHY-002 — `AccountHierarchyTree.clone()` calls
`HierarchyNode.clone()`, which calls `self.account.clone()` (i.e.
`AccountEntity.clone()` with no arguments). Per BUG-ACCOUNT-002 in
account_entity.py, that always raises `AccountCodeFormatError` (the
default "<code>_COPY" suffix isn't numeric), so `AccountHierarchyTree.clone()`
cannot succeed for any tree built from accounts with the default numeric
code pattern -- i.e. essentially every realistic tree.

BUG-HIERARCHY-003 — `AccountHierarchyTree.from_dict()` only inserts the
*root* HierarchyNode objects into the tree's internal `_nodes` index; it
does not flatten descendant nodes (children, grandchildren, ...) into
`_nodes`, even though `HierarchyNode.from_dict()` did nest them correctly
under `.children`. As a result, on a tree restored via `from_dict()`:
  - `tree.size` / `tree.get_node(child_id)` / `tree.account_exists(child_id)`
    are all wrong (they don't "see" non-root accounts).
  - `tree.get_children(root_id)` still works correctly, because it reads
    the nested `HierarchyNode.children` list directly, not the `_nodes`
    index.
This asymmetry is confirmed by test_from_dict_does_not_index_descendants
below.
======================================================================
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from domain.coa.account_code_vo import AccountCodeVO
from domain.coa.account_entity import AccountEntity
from domain.coa.account_hierarchy_tree import (
    AccountHierarchyError,
    AccountHierarchyTree,
    CycleDetectedError,
    HierarchyNode,
    ParentNotFoundError,
)
from domain.coa.account_normal_balance_vo import NormalBalance
from domain.coa.account_type_enum import AccountType

# ============================================================================
# Reset shared ClassVar audit trails between tests
# ============================================================================


@pytest.fixture(autouse=True)
def reset_class_level_state():
    AccountEntity._audit_trail.clear()
    AccountEntity._snapshots.clear()
    AccountHierarchyTree._audit_trail.clear()
    yield
    AccountEntity._audit_trail.clear()
    AccountEntity._snapshots.clear()
    AccountHierarchyTree._audit_trail.clear()


# ============================================================================
# Fixtures / builders
# ============================================================================


def make_account(code, name, legal_entity_id, parent=None, **overrides):
    defaults = dict(
        id=uuid4(),
        legal_entity_id=legal_entity_id,
        code=AccountCodeVO(code),
        name=name,
        account_type=AccountType.ASSET,
        normal_balance=NormalBalance.DEBIT,
        parent_id=parent,
    )
    defaults.update(overrides)
    return AccountEntity(**defaults)


@pytest.fixture
def legal_entity_id():
    return uuid4()


@pytest.fixture
def simple_hierarchy(legal_entity_id):
    """root (1000) -> child (1001) -> grandchild (1002)"""
    root = make_account("1000", "Assets", legal_entity_id)
    child = make_account("1001", "Cash", legal_entity_id, parent=root.id)
    grandchild = make_account("1002", "Petty Cash", legal_entity_id, parent=child.id)
    return root, child, grandchild


# ============================================================================
# HierarchyNode
# ============================================================================


class TestHierarchyNode:
    def test_path_auto_initialized_from_account(self, legal_entity_id):
        account = make_account("1000", "Assets", legal_entity_id)
        node = HierarchyNode(account=account)
        assert node.path == ["1000"]

    def test_to_dict_contains_expected_fields(self, legal_entity_id):
        account = make_account("1000", "Assets", legal_entity_id)
        node = HierarchyNode(account=account, level=0)
        d = node.to_dict()
        assert d["account_code"] == "1000"
        assert d["account_name"] == "Assets"
        assert d["account_type"] == "asset"
        assert d["has_children"] is False
        assert d["child_count"] == 0

    def test_to_dict_include_children_false_uses_child_ids(self, legal_entity_id):
        root = make_account("1000", "Assets", legal_entity_id)
        child = make_account("1001", "Cash", legal_entity_id, parent=root.id)
        root_node = HierarchyNode(account=root, children=[HierarchyNode(account=child)])
        d = root_node.to_dict(include_children=False)
        assert "children" not in d
        assert d["child_ids"] == [str(child.account_id)]

    def test_from_dict_round_trip(self, legal_entity_id):
        root = make_account("1000", "Assets", legal_entity_id)
        node = HierarchyNode(account=root, level=0)
        d = node.to_dict()
        restored = HierarchyNode.from_dict(d, {root.account_id: root})
        assert restored.account.account_id == root.account_id
        assert restored.level == 0

    def test_from_dict_missing_account_raises(self, legal_entity_id):
        root = make_account("1000", "Assets", legal_entity_id)
        node = HierarchyNode(account=root)
        d = node.to_dict()
        with pytest.raises(ValueError, match="not found in accounts_map"):
            HierarchyNode.from_dict(d, {})

    def test_snapshot_contains_expected_fields(self, legal_entity_id):
        account = make_account("1000", "Assets", legal_entity_id)
        node = HierarchyNode(account=account)
        snap = node.snapshot()
        assert snap["account_code"] == "1000"
        assert "timestamp" in snap

    def test_compute_hash_is_deterministic_for_same_state(self, legal_entity_id):
        account = make_account("1000", "Assets", legal_entity_id)
        node = HierarchyNode(account=account)
        assert node.compute_hash() == node.compute_hash()

    def test_get_child_by_code_and_id(self, legal_entity_id):
        root = make_account("1000", "Assets", legal_entity_id)
        child = make_account("1001", "Cash", legal_entity_id, parent=root.id)
        root_node = HierarchyNode(account=root, children=[HierarchyNode(account=child)])
        assert root_node.get_child_by_code("1001").account.account_id == child.account_id
        assert root_node.get_child_by_id(child.account_id).account.account_code == "1001"

    def test_get_child_by_code_not_found_returns_none(self, legal_entity_id):
        root = make_account("1000", "Assets", legal_entity_id)
        root_node = HierarchyNode(account=root)
        assert root_node.get_child_by_code("nope") is None

    def test_get_descendant_count(self, simple_hierarchy):
        root, child, grandchild = simple_hierarchy
        grandchild_node = HierarchyNode(account=grandchild)
        child_node = HierarchyNode(account=child, children=[grandchild_node])
        root_node = HierarchyNode(account=root, children=[child_node])
        assert root_node.get_descendant_count() == 2

    def test_get_all_descendants_bfs_order(self, simple_hierarchy):
        root, child, grandchild = simple_hierarchy
        grandchild_node = HierarchyNode(account=grandchild)
        child_node = HierarchyNode(account=child, children=[grandchild_node])
        root_node = HierarchyNode(account=root, children=[child_node])
        descendants = root_node.get_all_descendants()
        assert [n.account.account_code for n in descendants] == ["1001", "1002"]

    def test_get_all_leaf_nodes(self, simple_hierarchy):
        root, child, grandchild = simple_hierarchy
        grandchild_node = HierarchyNode(account=grandchild)
        child_node = HierarchyNode(account=child, children=[grandchild_node])
        root_node = HierarchyNode(account=root, children=[child_node])
        leaves = root_node.get_all_leaf_nodes()
        assert [n.account.account_code for n in leaves] == ["1002"]

    def test_leaf_node_is_its_own_leaf(self, legal_entity_id):
        account = make_account("9999", "Leaf", legal_entity_id)
        node = HierarchyNode(account=account)
        assert node.get_all_leaf_nodes() == [node]

    def test_audit_trail_collects_self_and_descendants(self, simple_hierarchy):
        root, child, grandchild = simple_hierarchy
        grandchild_node = HierarchyNode(account=grandchild)
        child_node = HierarchyNode(account=child, children=[grandchild_node])
        root_node = HierarchyNode(account=root, children=[child_node])
        trail = root_node.audit_trail()
        assert len(trail) == 3

    def test_repr(self, legal_entity_id):
        account = make_account("1000", "Assets", legal_entity_id)
        node = HierarchyNode(account=account)
        assert "1000" in repr(node)


# ============================================================================
# AccountHierarchyTree — factories
# ============================================================================


class TestTreeFactories:
    def test_empty_tree(self):
        tree = AccountHierarchyTree.empty()
        assert tree.is_empty is True
        assert tree.size == 0

    def test_single_root_tree(self, legal_entity_id):
        root = make_account("1000", "Assets", legal_entity_id)
        tree = AccountHierarchyTree.single_root(root)
        assert tree.size == 1
        assert tree.has_single_root is True

    def test_build_simple_hierarchy(self, simple_hierarchy, legal_entity_id):
        root, child, grandchild = simple_hierarchy
        tree = AccountHierarchyTree.build([root, child, grandchild])
        assert tree.size == 3
        assert tree.root_count == 1
        assert tree.orphan_count == 0

    def test_build_detects_multiple_roots(self, legal_entity_id):
        root1 = make_account("1000", "Assets", legal_entity_id)
        root2 = make_account("2000", "Liabilities", legal_entity_id)
        tree = AccountHierarchyTree.build([root1, root2])
        assert tree.has_multiple_roots is True
        assert tree.get_root() is None  # get_root() only works for exactly 1 root

    def test_build_detects_orphans(self, legal_entity_id):
        root = make_account("1000", "Assets", legal_entity_id)
        orphan = make_account("9999", "Orphan", legal_entity_id, parent=uuid4())
        tree = AccountHierarchyTree.build([root, orphan])
        assert tree.has_orphans is True
        assert tree.orphan_count == 1

    def test_build_raises_on_cycle(self, legal_entity_id):
        import dataclasses

        a = make_account("1", "Acc A", legal_entity_id)
        b = make_account("2", "Acc B", legal_entity_id, parent=a.id)
        a_with_cycle = dataclasses.replace(a, parent_id=b.id)
        with pytest.raises(CycleDetectedError):
            AccountHierarchyTree.build([a_with_cycle, b])


# ============================================================================
# AccountHierarchyTree — basic properties & lookups
# ============================================================================


class TestTreeBasicProperties:
    def test_get_root_returns_none_for_multiple_roots(self, legal_entity_id):
        root1 = make_account("1000", "Assets", legal_entity_id)
        root2 = make_account("2000", "Liabilities", legal_entity_id)
        tree = AccountHierarchyTree.build([root1, root2])
        assert tree.get_root() is None

    def test_get_root_returns_node_for_single_root(self, legal_entity_id):
        root = make_account("1000", "Assets", legal_entity_id)
        tree = AccountHierarchyTree.build([root])
        assert tree.get_root().account.account_code == "1000"

    def test_get_roots_returns_all(self, legal_entity_id):
        root1 = make_account("1000", "Assets", legal_entity_id)
        root2 = make_account("2000", "Liabilities", legal_entity_id)
        tree = AccountHierarchyTree.build([root1, root2])
        codes = {n.account.account_code for n in tree.get_roots()}
        assert codes == {"1000", "2000"}

    def test_get_node_and_get_node_by_code(self, simple_hierarchy):
        root, child, grandchild = simple_hierarchy
        tree = AccountHierarchyTree.build([root, child, grandchild])
        assert tree.get_node(child.account_id).account.account_code == "1001"
        assert tree.get_node_by_code("1001").account.account_id == child.account_id

    def test_get_node_missing_returns_none(self, legal_entity_id):
        tree = AccountHierarchyTree.empty()
        assert tree.get_node(uuid4()) is None
        assert tree.get_node_by_code("nope") is None

    def test_account_exists(self, simple_hierarchy):
        root, child, grandchild = simple_hierarchy
        tree = AccountHierarchyTree.build([root, child, grandchild])
        assert tree.account_exists(root.account_id) is True
        assert tree.account_exists(uuid4()) is False
        assert tree.account_exists_by_code("1000") is True
        assert tree.account_exists_by_code("nope") is False


# ============================================================================
# AccountHierarchyTree — navigation
# ============================================================================


class TestTreeNavigation:
    def test_get_parent(self, simple_hierarchy):
        root, child, grandchild = simple_hierarchy
        tree = AccountHierarchyTree.build([root, child, grandchild])
        assert tree.get_parent(child.account_id).account.account_code == "1000"

    def test_get_parent_of_root_is_none(self, simple_hierarchy):
        root, child, grandchild = simple_hierarchy
        tree = AccountHierarchyTree.build([root, child, grandchild])
        assert tree.get_parent(root.account_id) is None

    def test_get_children(self, simple_hierarchy):
        root, child, grandchild = simple_hierarchy
        tree = AccountHierarchyTree.build([root, child, grandchild])
        children = tree.get_children(root.account_id)
        assert [n.account.account_code for n in children] == ["1001"]

    def test_get_descendants(self, simple_hierarchy):
        root, child, grandchild = simple_hierarchy
        tree = AccountHierarchyTree.build([root, child, grandchild])
        descendants = tree.get_descendants(root.account_id)
        assert {n.account.account_code for n in descendants} == {"1001", "1002"}

    def test_get_ancestors(self, simple_hierarchy):
        root, child, grandchild = simple_hierarchy
        tree = AccountHierarchyTree.build([root, child, grandchild])
        ancestors = tree.get_ancestors(grandchild.account_id)
        assert [n.account.account_code for n in ancestors] == ["1001", "1000"]

    def test_get_root_path_includes_self(self, simple_hierarchy):
        root, child, grandchild = simple_hierarchy
        tree = AccountHierarchyTree.build([root, child, grandchild])
        path = tree.get_root_path(grandchild.account_id)
        assert [n.account.account_code for n in path] == ["1000", "1001", "1002"]

    def test_get_level(self, simple_hierarchy):
        root, child, grandchild = simple_hierarchy
        tree = AccountHierarchyTree.build([root, child, grandchild])
        assert tree.get_level(root.account_id) == 0
        assert tree.get_level(child.account_id) == 1
        assert tree.get_level(grandchild.account_id) == 2

    def test_get_level_missing_returns_negative_one(self):
        tree = AccountHierarchyTree.empty()
        assert tree.get_level(uuid4()) == -1

    def test_get_subtree(self, simple_hierarchy):
        root, child, grandchild = simple_hierarchy
        tree = AccountHierarchyTree.build([root, child, grandchild])
        subtree = tree.get_subtree(child.account_id)
        assert subtree.size == 2  # child + grandchild
        assert subtree.get_node(child.account_id).level == 0  # re-rooted

    def test_get_subtree_missing_returns_none(self):
        tree = AccountHierarchyTree.empty()
        assert tree.get_subtree(uuid4()) is None


# ============================================================================
# AccountHierarchyTree — traversal
# ============================================================================


class TestTreeTraversal:
    def test_dfs_preorder(self, simple_hierarchy):
        root, child, grandchild = simple_hierarchy
        tree = AccountHierarchyTree.build([root, child, grandchild])
        assert [n.account.account_code for n in tree.dfs_preorder()] == ["1000", "1001", "1002"]

    def test_dfs_postorder(self, simple_hierarchy):
        root, child, grandchild = simple_hierarchy
        tree = AccountHierarchyTree.build([root, child, grandchild])
        assert [n.account.account_code for n in tree.dfs_postorder()] == ["1002", "1001", "1000"]

    def test_bfs(self, legal_entity_id):
        root = make_account("1000", "Assets", legal_entity_id)
        child_a = make_account("1001", "Cash", legal_entity_id, parent=root.id)
        child_b = make_account("1002", "Bank", legal_entity_id, parent=root.id)
        tree = AccountHierarchyTree.build([root, child_a, child_b])
        assert [n.account.account_code for n in tree.bfs()] == ["1000", "1001", "1002"]

    def test_get_all_nodes_dispatches_by_order(self, simple_hierarchy):
        root, child, grandchild = simple_hierarchy
        tree = AccountHierarchyTree.build([root, child, grandchild])
        assert tree.get_all_nodes("dfs_pre") == tree.dfs_preorder()
        assert tree.get_all_nodes("dfs_post") == tree.dfs_postorder()
        assert tree.get_all_nodes("bfs") == tree.bfs()

    def test_get_leaf_nodes(self, simple_hierarchy):
        root, child, grandchild = simple_hierarchy
        tree = AccountHierarchyTree.build([root, child, grandchild])
        leaves = tree.get_leaf_nodes()
        assert [n.account.account_code for n in leaves] == ["1002"]

    def test_orphans_are_excluded_from_dfs_and_bfs_traversal(self, legal_entity_id):
        """Orphans exist in the tree's node index (and are counted by
        get_leaf_nodes/statistics), but dfs_preorder/dfs_postorder/bfs only
        walk from self._roots, so an orphan account never appears in those
        traversal results."""
        root = make_account("1000", "Assets", legal_entity_id)
        orphan = make_account("9999", "Orphan", legal_entity_id, parent=uuid4())
        tree = AccountHierarchyTree.build([root, orphan])
        assert "9999" not in [n.account.account_code for n in tree.dfs_preorder()]
        assert "9999" not in [n.account.account_code for n in tree.bfs()]
        assert "9999" in [n.account.account_code for n in tree.get_leaf_nodes()]


# ============================================================================
# AccountHierarchyTree — query methods
# ============================================================================


class TestTreeQueries:
    def test_find_by_code_prefix(self, simple_hierarchy):
        root, child, grandchild = simple_hierarchy
        tree = AccountHierarchyTree.build([root, child, grandchild])
        results = tree.find_by_code_prefix("100")
        assert {n.account.account_code for n in results} == {"1000", "1001", "1002"}

    def test_find_by_name_contains_case_insensitive(self, simple_hierarchy):
        root, child, grandchild = simple_hierarchy
        tree = AccountHierarchyTree.build([root, child, grandchild])
        results = tree.find_by_name_contains("CASH")
        codes = {n.account.account_code for n in results}
        assert codes == {"1001", "1002"}

    def test_find_by_name_contains_case_sensitive(self, simple_hierarchy):
        root, child, grandchild = simple_hierarchy
        tree = AccountHierarchyTree.build([root, child, grandchild])
        results = tree.find_by_name_contains("CASH", case_sensitive=True)
        assert results == []

    def test_find_by_type(self, legal_entity_id):
        asset = make_account("1000", "Assets", legal_entity_id)
        liability = make_account("2000", "Liabilities", legal_entity_id, account_type=AccountType.LIABILITY, normal_balance=NormalBalance.CREDIT)
        tree = AccountHierarchyTree.build([asset, liability])
        results = tree.find_by_type(AccountType.LIABILITY)
        assert [n.account.account_code for n in results] == ["2000"]

    def test_find_by_level(self, simple_hierarchy):
        root, child, grandchild = simple_hierarchy
        tree = AccountHierarchyTree.build([root, child, grandchild])
        assert [n.account.account_code for n in tree.find_by_level(1)] == ["1001"]


# ============================================================================
# AccountHierarchyTree — validation
# ============================================================================


class TestTreeValidation:
    def test_is_valid_true_for_clean_tree(self, simple_hierarchy):
        root, child, grandchild = simple_hierarchy
        tree = AccountHierarchyTree.build([root, child, grandchild])
        assert tree.is_valid() is True
        assert tree.get_validation_errors() == []

    def test_is_valid_false_with_orphans(self, legal_entity_id):
        root = make_account("1000", "Assets", legal_entity_id)
        orphan = make_account("9999", "Orphan", legal_entity_id, parent=uuid4())
        tree = AccountHierarchyTree.build([root, orphan])
        assert tree.is_valid() is False
        assert any("Orphan" in e for e in tree.get_validation_errors())


# ============================================================================
# AccountHierarchyTree — modification (add / remove / move)
# ============================================================================


class TestTreeModification:
    def test_add_account_as_new_root(self, legal_entity_id):
        root = make_account("1000", "Assets", legal_entity_id)
        tree = AccountHierarchyTree.build([root])
        new_root = make_account("2000", "Liabilities", legal_entity_id)
        updated = tree.add_account(new_root)
        assert updated.size == 2
        assert updated.root_count == 2

    def test_add_account_as_child_of_existing(self, legal_entity_id):
        root = make_account("1000", "Assets", legal_entity_id)
        tree = AccountHierarchyTree.build([root])
        child = make_account("1001", "Cash", legal_entity_id, parent=root.id)
        updated = tree.add_account(child)
        assert updated.get_parent(child.account_id).account.account_code == "1000"

    def test_add_account_with_missing_parent_becomes_orphan(self, legal_entity_id):
        root = make_account("1000", "Assets", legal_entity_id)
        tree = AccountHierarchyTree.build([root])
        orphan = make_account("9999", "Orphan", legal_entity_id, parent=uuid4())
        updated = tree.add_account(orphan)
        assert updated.has_orphans is True

    def test_add_account_duplicate_id_raises(self, legal_entity_id):
        root = make_account("1000", "Assets", legal_entity_id)
        tree = AccountHierarchyTree.build([root])
        with pytest.raises(AccountHierarchyError, match="already exists"):
            tree.add_account(root)

    def test_add_account_does_not_mutate_original_tree(self, legal_entity_id):
        root = make_account("1000", "Assets", legal_entity_id)
        tree = AccountHierarchyTree.build([root])
        new_root = make_account("2000", "Liabilities", legal_entity_id)
        tree.add_account(new_root)
        assert tree.size == 1  # original tree unchanged

    def test_remove_leaf_account(self, legal_entity_id):
        root = make_account("1000", "Assets", legal_entity_id)
        child = make_account("1001", "Cash", legal_entity_id, parent=root.id)
        tree = AccountHierarchyTree.build([root, child])
        updated = tree.remove_account(child.account_id)
        assert updated.size == 1
        assert updated.account_exists(child.account_id) is False

    def test_remove_account_with_children_without_cascade_raises(self, simple_hierarchy):
        root, child, grandchild = simple_hierarchy
        tree = AccountHierarchyTree.build([root, child, grandchild])
        with pytest.raises(AccountHierarchyError, match="Use cascade=True"):
            tree.remove_account(child.account_id, cascade=False)

    def test_remove_account_with_cascade_removes_descendants(self, simple_hierarchy):
        root, child, grandchild = simple_hierarchy
        tree = AccountHierarchyTree.build([root, child, grandchild])
        updated = tree.remove_account(child.account_id, cascade=True)
        assert updated.size == 1  # only root remains
        assert updated.account_exists(grandchild.account_id) is False

    def test_remove_nonexistent_account_raises(self):
        tree = AccountHierarchyTree.empty()
        with pytest.raises(AccountHierarchyError, match="not found"):
            tree.remove_account(uuid4())

    def test_move_account_validates_new_parent_exists(self, simple_hierarchy):
        root, child, grandchild = simple_hierarchy
        tree = AccountHierarchyTree.build([root, child, grandchild])
        with pytest.raises(ParentNotFoundError):
            tree.move_account(grandchild.account_id, uuid4())

    def test_move_account_detects_cycle(self, simple_hierarchy):
        root, child, grandchild = simple_hierarchy
        tree = AccountHierarchyTree.build([root, child, grandchild])
        # Moving `child` under its own descendant `grandchild` would cycle.
        with pytest.raises(CycleDetectedError):
            tree.move_account(child.account_id, grandchild.account_id)

    def test_move_account_does_not_actually_change_parent(self, legal_entity_id):
        """BUG-HIERARCHY-001: move_account's new_parent_id is validated but
        never actually applied -- the account ends up back under its
        ORIGINAL parent because the unmodified AccountEntity object is
        re-added via add_account()."""
        root_a = make_account("1000", "Assets", legal_entity_id)
        root_b = make_account("2000", "Liabilities", legal_entity_id)
        child = make_account("1001", "Cash", legal_entity_id, parent=root_a.id)
        tree = AccountHierarchyTree.build([root_a, root_b, child])

        moved_tree = tree.move_account(child.account_id, root_b.account_id)

        actual_parent = moved_tree.get_parent(child.account_id)
        assert actual_parent is not None
        assert actual_parent.account.account_code == "1000"  # still root_a, NOT root_b
        assert moved_tree.get_node(child.account_id).account.parent_account_id == root_a.account_id

    def test_move_account_with_children_raises_without_cascade(self, simple_hierarchy):
        """move_account() calls remove_account(cascade=False) internally,
        so moving a node that itself has children always raises."""
        root, child, grandchild = simple_hierarchy
        tree = AccountHierarchyTree.build([root, child, grandchild])
        with pytest.raises(AccountHierarchyError, match="Use cascade=True"):
            tree.move_account(child.account_id, root.account_id)


# ============================================================================
# AccountHierarchyTree — statistics
# ============================================================================


class TestTreeStatistics:
    def test_statistics_for_simple_hierarchy(self, simple_hierarchy):
        root, child, grandchild = simple_hierarchy
        tree = AccountHierarchyTree.build([root, child, grandchild])
        stats = tree.get_statistics()
        assert stats["total_accounts"] == 3
        assert stats["root_accounts"] == 1
        assert stats["leaf_accounts"] == 1
        assert stats["max_depth"] == 2
        assert stats["is_valid"] is True

    def test_statistics_for_empty_tree(self):
        tree = AccountHierarchyTree.empty()
        stats = tree.get_statistics()
        assert stats["total_accounts"] == 0
        assert stats["average_children_per_node"] == 0


# ============================================================================
# AccountHierarchyTree — serialization
# ============================================================================


class TestTreeSerialization:
    def test_to_dict_contains_expected_fields(self, simple_hierarchy):
        root, child, grandchild = simple_hierarchy
        tree = AccountHierarchyTree.build([root, child, grandchild])
        d = tree.to_dict()
        assert d["total_nodes"] == 3
        assert len(d["roots"]) == 1
        assert d["roots"][0]["account_code"] == "1000"

    def test_from_dict_root_only_round_trips_correctly(self, legal_entity_id):
        root = make_account("1000", "Assets", legal_entity_id)
        tree = AccountHierarchyTree.build([root])
        d = tree.to_dict()
        restored = AccountHierarchyTree.from_dict(d, {root.account_id: root})
        assert restored.size == 1
        assert restored.get_node(root.account_id) is not None

    def test_from_dict_does_not_index_descendants(self, legal_entity_id):
        """BUG-HIERARCHY-003: from_dict() only registers root nodes in
        `_nodes`; descendants are nested under `.children` but not
        separately indexed, so lookups by id/size are wrong for them --
        even though get_children() (which reads the nested structure)
        still works."""
        root = make_account("1000", "Assets", legal_entity_id)
        child = make_account("1001", "Cash", legal_entity_id, parent=root.id)
        tree = AccountHierarchyTree.build([root, child])
        d = tree.to_dict()
        accounts_map = {root.account_id: root, child.account_id: child}
        restored = AccountHierarchyTree.from_dict(d, accounts_map)

        assert restored.size == 1  # should conceptually be 2
        assert restored.get_node(child.account_id) is None  # not indexed
        assert restored.account_exists(child.account_id) is False

        # ...yet the nested structure is intact and get_children still works:
        children_via_api = restored.get_children(root.account_id)
        assert [n.account.account_code for n in children_via_api] == ["1001"]

    def test_clone_fails_due_to_underlying_account_clone_bug(self, legal_entity_id):
        """BUG-HIERARCHY-002: clone() delegates to AccountEntity.clone()
        with no explicit new_code, which always raises AccountCodeFormatError
        (see BUG-ACCOUNT-002 in test_account_entity.py)."""
        from domain.coa.account_code_vo import AccountCodeFormatError

        root = make_account("1000", "Assets", legal_entity_id)
        tree = AccountHierarchyTree.build([root])
        with pytest.raises(AccountCodeFormatError):
            tree.clone()

    def test_snapshot_contains_expected_fields(self, simple_hierarchy):
        root, child, grandchild = simple_hierarchy
        tree = AccountHierarchyTree.build([root, child, grandchild])
        snap = tree.snapshot()
        assert "statistics" in snap
        assert len(snap["roots"]) == 1

    def test_compute_hash_deterministic(self, simple_hierarchy):
        root, child, grandchild = simple_hierarchy
        tree = AccountHierarchyTree.build([root, child, grandchild])
        assert tree.compute_hash() == tree.compute_hash()

    def test_audit_trail_records_build_action(self, legal_entity_id):
        root = make_account("1000", "Assets", legal_entity_id)
        AccountHierarchyTree.build([root])
        trail = AccountHierarchyTree.empty().audit_trail()
        # empty() also triggers a BUILD audit entry; at least one BUILD entry exists
        assert any(entry["action"] == "BUILD" for entry in trail)

    def test_pretty_print_contains_account_codes(self, simple_hierarchy):
        root, child, grandchild = simple_hierarchy
        tree = AccountHierarchyTree.build([root, child, grandchild])
        text = tree.pretty_print()
        assert "1000" in text
        assert "1001" in text
        assert "1002" in text


# ============================================================================
# AccountHierarchyTree — private methods (direct coverage)
# ============================================================================


class TestTreePrivateMethods:
    """Direct tests for private methods to satisfy coverage."""

    def test_validate_no_cycles_valid(self, legal_entity_id):
        """Test _validate_no_cycles does not raise on acyclic graph."""
        root = make_account("1000", "Assets", legal_entity_id)
        child = make_account("1001", "Cash", legal_entity_id, parent=root.id)
        nodes = {
            root.account_id: HierarchyNode(account=root),
            child.account_id: HierarchyNode(account=child),
        }
        children_map = {root.account_id: [child.account_id]}
        # Should not raise
        AccountHierarchyTree._validate_no_cycles(nodes, children_map)

    def test_validate_no_cycles_detects_cycle(self, legal_entity_id):
        """Test _validate_no_cycles raises CycleDetectedError on cycle."""
        a = make_account("1", "A", legal_entity_id)
        b = make_account("2", "B", legal_entity_id, parent=a.id)
        # Manually create cycle: a -> b, b -> a
        nodes = {
            a.account_id: HierarchyNode(account=a),
            b.account_id: HierarchyNode(account=b),
        }
        children_map = {
            a.account_id: [b.account_id],
            b.account_id: [a.account_id],
        }
        with pytest.raises(CycleDetectedError):
            AccountHierarchyTree._validate_no_cycles(nodes, children_map)

    def test_find_path_from_root_found(self, simple_hierarchy):
        """Test _find_path_from_root returns path when target exists."""
        root, child, grandchild = simple_hierarchy
        tree = AccountHierarchyTree.build([root, child, grandchild])
        root_node = tree.get_node(root.account_id)
        path = AccountHierarchyTree._find_path_from_root(root_node, grandchild.account_id)
        assert path is not None
        assert len(path) == 3
        assert path[0] == root.account_id
        assert path[-1] == grandchild.account_id

    def test_find_path_from_root_not_found(self, simple_hierarchy):
        """Test _find_path_from_root returns None when target missing."""
        root, child, grandchild = simple_hierarchy
        tree = AccountHierarchyTree.build([root, child, grandchild])
        root_node = tree.get_node(root.account_id)
        path = AccountHierarchyTree._find_path_from_root(root_node, uuid4())
        assert path is None

    def test_dfs_preorder_private(self, simple_hierarchy):
        """Test _dfs_preorder directly."""
        root, child, grandchild = simple_hierarchy
        tree = AccountHierarchyTree.build([root, child, grandchild])
        root_node = tree.get_node(root.account_id)
        result = []
        tree._dfs_preorder(root_node, result)
        assert [n.account.account_code for n in result] == ["1000", "1001", "1002"]

    def test_dfs_postorder_private(self, simple_hierarchy):
        """Test _dfs_postorder directly."""
        root, child, grandchild = simple_hierarchy
        tree = AccountHierarchyTree.build([root, child, grandchild])
        root_node = tree.get_node(root.account_id)
        result = []
        tree._dfs_postorder(root_node, result)
        assert [n.account.account_code for n in result] == ["1002", "1001", "1000"]

    def test_update_levels_and_paths(self, legal_entity_id):
        """Test _update_levels_and_paths updates node and descendants."""
        root = make_account("1000", "Assets", legal_entity_id)
        child = make_account("1001", "Cash", legal_entity_id, parent=root.id)
        grandchild = make_account("1002", "Petty Cash", legal_entity_id, parent=child.id)
        # Build nodes manually
        grandchild_node = HierarchyNode(account=grandchild)
        child_node = HierarchyNode(account=child, children=[grandchild_node])
        root_node = HierarchyNode(account=root, children=[child_node])
        # Call private method on root
        root_node._update_levels_and_paths(root_node, 0, [])
        assert root_node.level == 0
        assert root_node.path == ["1000"]
        assert child_node.level == 1
        assert child_node.path == ["1000", "1001"]
        assert grandchild_node.level == 2
        assert grandchild_node.path == ["1000", "1001", "1002"]

    def test_recalculate_levels(self, legal_entity_id):
        """Test _recalculate_levels recomputes levels and paths."""
        root = make_account("1000", "Assets", legal_entity_id)
        child = make_account("1001", "Cash", legal_entity_id, parent=root.id)
        grandchild = make_account("1002", "Petty Cash", legal_entity_id, parent=child.id)
        # Build nodes manually with wrong levels initially
        grandchild_node = HierarchyNode(account=grandchild, level=99, path=[])
        child_node = HierarchyNode(account=child, children=[grandchild_node], level=99, path=[])
        root_node = HierarchyNode(account=root, children=[child_node], level=99, path=[])
        # Call private method
        tree = AccountHierarchyTree.empty()
        tree._recalculate_levels(root_node, 0, [])
        assert root_node.level == 0
        assert root_node.path == ["1000"]
        assert child_node.level == 1
        assert child_node.path == ["1000", "1001"]
        assert grandchild_node.level == 2
        assert grandchild_node.path == ["1000", "1001", "1002"]

    def test_pretty_print_node(self, simple_hierarchy):
        """Test _pretty_print_node directly."""
        root, child, grandchild = simple_hierarchy
        tree = AccountHierarchyTree.build([root, child, grandchild])
        root_node = tree.get_node(root.account_id)
        lines = []
        tree._pretty_print_node(root_node, 0, lines, indent=2)
        assert len(lines) == 3
        assert lines[0] == "1000 - Assets"
        assert lines[1] == "  1001 - Cash"
        assert lines[2] == "    1002 - Petty Cash"


# ============================================================================
# Dunder methods
# ============================================================================


class TestTreeDunderMethods:
    def test_repr(self, simple_hierarchy):
        root, child, grandchild = simple_hierarchy
        tree = AccountHierarchyTree.build([root, child, grandchild])
        assert "nodes=3" in repr(tree)

    def test_len(self, simple_hierarchy):
        root, child, grandchild = simple_hierarchy
        tree = AccountHierarchyTree.build([root, child, grandchild])
        assert len(tree) == 3

    def test_contains(self, simple_hierarchy):
        root, child, grandchild = simple_hierarchy
        tree = AccountHierarchyTree.build([root, child, grandchild])
        assert root.account_id in tree
        assert uuid4() not in tree
