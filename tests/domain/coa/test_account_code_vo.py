"""
Tests for domain/coa/account_code_vo.py

Covers construction/normalization/validation, level access, parent/ancestor/
root derivation, hierarchy predicates (is_child_of/is_descendant_of/
is_ancestor_of/is_root/same_hierarchy_path), code manipulation (with_separator/
without_separator/with_pattern/increment_level/set_level/append_level/
prepend_level), matches_pattern/is_valid_format, serialization, and dunder
methods (str/repr/eq/hash/lt).

NOTE ON DEFAULT PATTERN: `DEFAULT_CODE_PATTERN` (`^[0-9]{1,20}$`) is matched
against the *whole* normalized code string, separator characters included.
This means a hierarchical code like "1.10.01" needs an explicit custom
pattern that allows the separator (e.g. `^[0-9.]{1,20}$`) -- the default
pattern alone rejects any code containing a separator. This is confirmed
by test_hierarchical_code_needs_custom_pattern_to_allow_separator below;
without that, even the pattern shown in the class docstring
(`AccountCodeVO("1.10.01", separator=".")`) would raise.

NOTE ON without_separator(): it is a lossy, one-way transform. Once levels
are concatenated into a single flat level, calling with_separator() again
does not restore the original multi-level hierarchy (there is now only one
level to join).
"""

from __future__ import annotations

import pytest

from domain.coa.account_code_vo import (
    ALLOWED_SEPARATORS,
    DEFAULT_CODE_PATTERN,
    AccountCode,
    AccountCodeFormatError,
    AccountCodeLevelError,
    AccountCodeVO,
)

HIERARCHICAL_PATTERN = r"^[0-9.]{1,20}$"
DASH_PATTERN = r"^[0-9\-]{1,20}$"


# ============================================================================
# Construction & normalization
# ============================================================================


class TestConstruction:
    def test_flat_numeric_code_with_default_pattern(self):
        code = AccountCodeVO("1000")
        assert code.code == "1000"
        assert code.levels == ["1000"]
        assert code.is_flat is True

    def test_hierarchical_code_needs_custom_pattern_to_allow_separator(self):
        # Default pattern is numeric-only; a code containing "." fails it.
        with pytest.raises(AccountCodeFormatError, match="does not match pattern"):
            AccountCodeVO("1.10.01", separator=".")

    def test_hierarchical_code_with_matching_custom_pattern_succeeds(self):
        code = AccountCodeVO("1.10.01", separator=".", pattern=HIERARCHICAL_PATTERN)
        assert code.levels == ["1", "10", "01"]
        assert code.depth == 3
        assert code.is_hierarchical is True

    def test_empty_code_raises(self):
        with pytest.raises(AccountCodeFormatError, match="non-empty string"):
            AccountCodeVO("")

    def test_whitespace_only_code_raises(self):
        with pytest.raises(AccountCodeFormatError):
            AccountCodeVO("   ")

    def test_code_too_long_raises(self):
        with pytest.raises(AccountCodeFormatError, match="too long"):
            AccountCodeVO("1" * 51, pattern=r"^[0-9]{1,60}$")

    def test_invalid_separator_raises(self):
        with pytest.raises(AccountCodeFormatError, match="not allowed"):
            AccountCodeVO("1/10/01", separator="/")

    def test_auto_detect_separator(self):
        code = AccountCodeVO("1-10-01", pattern=DASH_PATTERN)
        assert code.effective_separator == "-"
        assert code.levels == ["1", "10", "01"]

    def test_whitespace_is_stripped(self):
        code = AccountCodeVO("  1000  ")
        assert code.code == "1000"

    def test_code_alias_is_account_code_vo(self):
        assert AccountCode is AccountCodeVO

    def test_allowed_separators_constant(self):
        assert ALLOWED_SEPARATORS == [".", "-", "_"]

    def test_default_code_pattern_constant(self):
        assert DEFAULT_CODE_PATTERN == r"^[0-9]{1,20}$"

    def test_is_immutable(self):
        code = AccountCodeVO("1000")
        with pytest.raises(Exception):
            code.code = "9999"


# ============================================================================
# Properties
# ============================================================================


class TestProperties:
    def test_value_is_alias_for_code(self):
        code = AccountCodeVO("1000")
        assert code.value == code.code

    def test_normalized_code(self):
        code = AccountCodeVO("  1000  ")
        assert code.normalized_code == "1000"

    def test_is_flat_true_for_single_level(self):
        assert AccountCodeVO("1000").is_flat is True

    def test_is_flat_false_for_hierarchical(self):
        code = AccountCodeVO("1.10", separator=".", pattern=HIERARCHICAL_PATTERN)
        assert code.is_flat is False
        assert code.is_hierarchical is True


# ============================================================================
# Level access
# ============================================================================


class TestLevelAccess:
    @pytest.fixture
    def hierarchical(self):
        return AccountCodeVO("1.10.01", separator=".", pattern=HIERARCHICAL_PATTERN)

    def test_get_level_one_indexed(self, hierarchical):
        assert hierarchical.get_level(1) == "1"
        assert hierarchical.get_level(2) == "10"
        assert hierarchical.get_level(3) == "01"

    def test_get_level_out_of_range_returns_none(self, hierarchical):
        assert hierarchical.get_level(4) is None

    def test_get_level_below_one_raises(self, hierarchical):
        with pytest.raises(AccountCodeLevelError, match="must be >= 1"):
            hierarchical.get_level(0)

    def test_get_level_zero_based(self, hierarchical):
        assert hierarchical.get_level_zero_based(0) == "1"
        assert hierarchical.get_level_zero_based(2) == "01"

    def test_get_level_zero_based_out_of_range_returns_none(self, hierarchical):
        assert hierarchical.get_level_zero_based(99) is None
        assert hierarchical.get_level_zero_based(-1) is None

    def test_get_first_level(self, hierarchical):
        assert hierarchical.get_first_level() == "1"

    def test_get_last_level(self, hierarchical):
        assert hierarchical.get_last_level() == "01"


# ============================================================================
# Parent / ancestors / root
# ============================================================================


class TestHierarchyDerivation:
    @pytest.fixture
    def hierarchical(self):
        return AccountCodeVO("1.10.01", separator=".", pattern=HIERARCHICAL_PATTERN)

    def test_get_parent_code(self, hierarchical):
        parent = hierarchical.get_parent_code()
        assert parent.code == "1.10"

    def test_get_parent_code_of_root_is_none(self):
        root = AccountCodeVO("1", pattern=HIERARCHICAL_PATTERN)
        assert root.get_parent_code() is None

    def test_get_parent_code_without_separator_is_none(self):
        flat = AccountCodeVO("1000")
        assert flat.get_parent_code() is None

    def test_get_ancestor_codes_excluding_self(self, hierarchical):
        ancestors = [a.code for a in hierarchical.get_ancestor_codes()]
        assert ancestors == ["1", "1.10"]

    def test_get_ancestor_codes_including_self(self, hierarchical):
        ancestors = [a.code for a in hierarchical.get_ancestor_codes(include_self=True)]
        assert ancestors == ["1", "1.10", "1.10.01"]

    def test_get_root_code(self, hierarchical):
        root = hierarchical.get_root_code()
        assert root.code == "1"
        assert root.effective_separator is None


# ============================================================================
# Hierarchy predicates
# ============================================================================


class TestHierarchyPredicates:
    @pytest.fixture
    def parent(self):
        return AccountCodeVO("1.10", separator=".", pattern=HIERARCHICAL_PATTERN)

    @pytest.fixture
    def child(self):
        return AccountCodeVO("1.10.01", separator=".", pattern=HIERARCHICAL_PATTERN)

    @pytest.fixture
    def grandchild(self):
        return AccountCodeVO("1.10.01.05", separator=".", pattern=r"^[0-9.]{1,30}$")

    def test_is_child_of_true(self, child, parent):
        assert child.is_child_of(parent) is True

    def test_is_child_of_false_for_grandchild(self, grandchild, parent):
        assert grandchild.is_child_of(parent) is False

    def test_is_descendant_of_true_for_direct_and_indirect(self, child, grandchild, parent):
        assert child.is_descendant_of(parent) is True
        assert grandchild.is_descendant_of(parent) is True

    def test_is_descendant_of_false_for_unrelated(self, parent):
        other = AccountCodeVO("2.20", separator=".", pattern=HIERARCHICAL_PATTERN)
        assert other.is_descendant_of(parent) is False

    def test_is_descendant_of_false_when_shallower_or_equal_depth(self, parent):
        assert parent.is_descendant_of(parent) is False

    def test_is_ancestor_of(self, parent, child):
        assert parent.is_ancestor_of(child) is True
        assert child.is_ancestor_of(parent) is False

    def test_is_root(self):
        assert AccountCodeVO("1", pattern=HIERARCHICAL_PATTERN).is_root() is True

    def test_is_root_false_for_hierarchical(self, parent):
        assert parent.is_root() is False

    def test_same_hierarchy_path_true(self, child):
        same = AccountCodeVO("1.10.01", separator=".", pattern=HIERARCHICAL_PATTERN)
        assert child.same_hierarchy_path(same) is True

    def test_same_hierarchy_path_false(self, child, parent):
        assert child.same_hierarchy_path(parent) is False


# ============================================================================
# Code manipulation
# ============================================================================


class TestCodeManipulation:
    def test_with_separator_returns_self_if_same(self):
        code = AccountCodeVO("1.10", separator=".", pattern=HIERARCHICAL_PATTERN)
        assert code.with_separator(".") is code

    def test_with_separator_changes_join_character(self):
        # Pattern must allow BOTH separators, since with_separator() inherits
        # the original pattern for the new instance.
        both_seps_pattern = r"^[0-9.\-]{1,20}$"
        code = AccountCodeVO("1.10", separator=".", pattern=both_seps_pattern)
        dashed = code.with_separator("-")
        assert dashed.code == "1-10"
        assert dashed.effective_separator == "-"

    def test_with_separator_raises_if_new_separator_not_allowed_by_inherited_pattern(self):
        # The inherited pattern only allows dots, so switching to '-' fails
        # because the resulting string "1-10" no longer matches it.
        code = AccountCodeVO("1.10", separator=".", pattern=HIERARCHICAL_PATTERN)
        with pytest.raises(AccountCodeFormatError, match="does not match pattern"):
            code.with_separator("-")

    def test_without_separator_flattens_levels(self):
        code = AccountCodeVO("1.10.01", separator=".", pattern=HIERARCHICAL_PATTERN)
        flat = code.without_separator()
        assert flat.code == "11001"
        assert flat.levels == ["11001"]
        assert flat.effective_separator is None

    def test_without_separator_is_lossy_one_way(self):
        """Re-applying with_separator to an already-flattened code cannot
        restore the original hierarchy, because the flat code now has only
        one level to join."""
        code = AccountCodeVO("1.10.01", separator=".", pattern=HIERARCHICAL_PATTERN)
        flat = code.without_separator()
        restored_attempt = flat.with_separator(".")
        assert restored_attempt.code == "11001"  # NOT "1.10.01"

    def test_without_separator_on_already_flat_returns_self(self):
        flat = AccountCodeVO("1000")
        assert flat.without_separator() is flat

    def test_with_pattern_valid(self):
        code = AccountCodeVO("1000")
        stricter = code.with_pattern(r"^[0-9]{4}$")
        assert stricter.code == "1000"

    def test_with_pattern_invalid_raises(self):
        code = AccountCodeVO("1000")
        with pytest.raises(AccountCodeFormatError, match="does not match new pattern"):
            code.with_pattern(r"^[0-9]{10}$")

    def test_increment_level(self):
        code = AccountCodeVO("1.10.01", separator=".", pattern=HIERARCHICAL_PATTERN)
        incremented = code.increment_level(3, 1)
        assert incremented.code == "1.10.02"

    def test_increment_level_preserves_zero_padding(self):
        code = AccountCodeVO("1.10.01", separator=".", pattern=HIERARCHICAL_PATTERN)
        incremented = code.increment_level(3, 8)
        assert incremented.get_level(3) == "09"

    def test_increment_level_nonexistent_raises(self):
        code = AccountCodeVO("1.10", separator=".", pattern=HIERARCHICAL_PATTERN)
        with pytest.raises(AccountCodeLevelError, match="does not exist"):
            code.increment_level(5)

    def test_increment_level_negative_result_raises(self):
        code = AccountCodeVO("1.10.00", separator=".", pattern=HIERARCHICAL_PATTERN)
        with pytest.raises(AccountCodeFormatError, match="negative"):
            code.increment_level(3, -1)

    def test_set_level(self):
        code = AccountCodeVO("1.10.01", separator=".", pattern=HIERARCHICAL_PATTERN)
        updated = code.set_level(2, "20")
        assert updated.code == "1.20.01"

    def test_set_level_out_of_range_raises(self):
        code = AccountCodeVO("1.10", separator=".", pattern=HIERARCHICAL_PATTERN)
        with pytest.raises(AccountCodeLevelError, match="out of range"):
            code.set_level(5, "99")

    def test_append_level(self):
        code = AccountCodeVO("1.10", separator=".", pattern=HIERARCHICAL_PATTERN)
        appended = code.append_level("05")
        assert appended.code == "1.10.05"
        assert appended.depth == 3

    def test_prepend_level(self):
        code = AccountCodeVO("1.10", separator=".", pattern=HIERARCHICAL_PATTERN)
        prepended = code.prepend_level("9")
        assert prepended.code == "9.1.10"
        assert prepended.depth == 3


# ============================================================================
# Pattern validation helpers
# ============================================================================


class TestPatternValidation:
    def test_matches_pattern_default(self):
        code = AccountCodeVO("1000")
        assert code.matches_pattern() is True

    def test_matches_pattern_with_override(self):
        code = AccountCodeVO("1.10", separator=".", pattern=HIERARCHICAL_PATTERN)
        assert code.matches_pattern(r"^[0-9]{1,20}$") is False  # dots not allowed

    def test_is_valid_format_true(self):
        assert AccountCodeVO.is_valid_format("1000") is True

    def test_is_valid_format_false(self):
        assert AccountCodeVO.is_valid_format("abc") is False

    def test_is_valid_format_with_separator_and_pattern(self):
        assert AccountCodeVO.is_valid_format(
            "1.10.01", pattern=HIERARCHICAL_PATTERN, separator="."
        ) is True


# ============================================================================
# Serialization
# ============================================================================


class TestSerialization:
    def test_to_dict_contains_expected_fields(self):
        code = AccountCodeVO("1.10.01", separator=".", pattern=HIERARCHICAL_PATTERN)
        d = code.to_dict()
        assert d["code"] == "1.10.01"
        assert d["levels"] == ["1", "10", "01"]
        assert d["depth"] == 3
        assert d["root_level"] == "1"
        assert d["last_level"] == "01"

    def test_from_dict_round_trip(self):
        code = AccountCodeVO("1.10.01", separator=".", pattern=HIERARCHICAL_PATTERN)
        restored = AccountCodeVO.from_dict(code.to_dict())
        assert restored == code
        assert restored.levels == code.levels

    def test_to_db_format_returns_normalized_code(self):
        code = AccountCodeVO("  1000  ")
        assert code.to_db_format() == "1000"


# ============================================================================
# Dunder methods
# ============================================================================


class TestDunderMethods:
    def test_str(self):
        assert str(AccountCodeVO("1000")) == "1000"

    def test_repr_contains_code_and_depth(self):
        code = AccountCodeVO("1000")
        assert "1000" in repr(code)
        assert "depth=1" in repr(code)

    def test_equality_ignores_separator_and_pattern(self):
        a = AccountCodeVO("1000")
        b = AccountCodeVO("1000", pattern=r"^[0-9]{1,10}$")
        assert a == b

    def test_equality_with_non_account_code_is_false(self):
        assert (AccountCodeVO("1000") == "1000") is False

    def test_hash_matches_for_equal_codes(self):
        a = AccountCodeVO("1000")
        b = AccountCodeVO("1000")
        assert hash(a) == hash(b)

    def test_lt_orders_by_normalized_code(self):
        a = AccountCodeVO("1000")
        b = AccountCodeVO("2000")
        assert a < b
        assert not (b < a)

    def test_sorted_list_of_codes(self):
        codes = [AccountCodeVO("3000"), AccountCodeVO("1000"), AccountCodeVO("2000")]
        ordered = sorted(codes)
        assert [c.code for c in ordered] == ["1000", "2000", "3000"]
