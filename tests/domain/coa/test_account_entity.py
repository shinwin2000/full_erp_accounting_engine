"""
Tests for domain/coa/account_entity.py

Covers AccountStatus enum, AccountEntity construction/validation/lifecycle
(create/update/delete/restore/activate/deactivate/lock/unlock/touch/clone),
serialization, property aliases, and the real in-memory AccountRepository.

======================================================================
KNOWN ISSUES IN THE SOURCE (verified by direct execution):

BUG-ACCOUNT-001 — `AccountEntity.from_dict()` always reconstructs the
account code as `AccountCodeVO(data["code"])`, i.e. with NO separator and
the module's DEFAULT numeric-only pattern (`^[0-9]{1,20}$`). Any account
whose code contains a separator (e.g. a realistic hierarchical code like
"1.10.01") will raise `AccountCodeFormatError` when passed through
`from_dict()`. Since `update()` internally round-trips through
`to_dict()` -> `from_dict()`, **`update()` itself is broken for any
account with a hierarchical code** -- it only works for flat, purely
numeric codes. This is pinned down by
test_update_raises_for_hierarchical_code below.

BUG-ACCOUNT-002 — `clone()` without an explicit `new_code` builds the
default as `f"{self.code.code}_COPY"` (e.g. "1000_COPY"), then constructs
`AccountCodeVO(new_code_str)` with the default numeric-only pattern. Since
"1000_COPY" contains letters and an underscore, this always raises
`AccountCodeFormatError` -- `clone()` can only be used with an explicit,
pattern-valid `new_code` argument, never with its own default.

BUG-ACCOUNT-003 (design issue, not a crash) — `_audit_trail` and
`_snapshots` are declared as `ClassVar`, so they are a single list SHARED
by every `AccountEntity` instance in the process (confirmed: two unrelated
accounts' `._audit_trail` attribute is the literal same list object).
Audit trail entries from every account accumulate into one global list.
Tests below reset these class-level lists in an autouse fixture to stay
independent from each other, and one test pins down the sharing itself.
======================================================================
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from domain.coa.account_code_vo import AccountCodeFormatError, AccountCodeVO
from domain.coa.account_entity import (
    Account,
    AccountEntity,
    AccountRepository,
    AccountStatus,
)
from domain.coa.account_normal_balance_vo import NormalBalance
from domain.coa.account_type_enum import AccountType

# ============================================================================
# Reset shared ClassVar state between tests (see BUG-ACCOUNT-003)
# ============================================================================


@pytest.fixture(autouse=True)
def reset_class_level_state():
    AccountEntity._audit_trail.clear()
    AccountEntity._snapshots.clear()
    AccountRepository._storage.clear()
    yield
    AccountEntity._audit_trail.clear()
    AccountEntity._snapshots.clear()
    AccountRepository._storage.clear()


# ============================================================================
# AccountStatus
# ============================================================================


class TestAccountStatus:
    def test_is_active_only_for_active(self):
        assert AccountStatus.ACTIVE.is_active() is True
        assert AccountStatus.DRAFT.is_active() is False

    def test_can_post_only_for_active(self):
        assert AccountStatus.ACTIVE.can_post() is True
        assert AccountStatus.LOCKED.can_post() is False

    def test_can_modify_draft_active_suspended(self):
        assert AccountStatus.DRAFT.can_modify() is True
        assert AccountStatus.ACTIVE.can_modify() is True
        assert AccountStatus.SUSPENDED.can_modify() is True
        assert AccountStatus.LOCKED.can_modify() is False
        assert AccountStatus.CLOSED.can_modify() is False


# ============================================================================
# AccountEntity — fixtures
# ============================================================================


def make_account(**overrides):
    legal_entity_id = overrides.pop("legal_entity_id", uuid4())
    code = overrides.pop("code", AccountCodeVO("1000"))
    defaults = {
        "id": uuid4(),
        "legal_entity_id": legal_entity_id,
        "code": code,
        "name": "Cash",
        "account_type": AccountType.ASSET,
        "normal_balance": NormalBalance.DEBIT,
    }
    defaults.update(overrides)
    return AccountEntity(**defaults)


# ============================================================================
# Construction & validation
# ============================================================================


class TestAccountEntityConstruction:
    def test_valid_construction(self):
        account = make_account()
        assert account.name == "Cash"
        assert account.status == AccountStatus.DRAFT
        assert account.version == 1

    def test_short_name_raises(self):
        with pytest.raises(ValueError, match="at least 2 characters"):
            make_account(name="X")

    def test_empty_name_raises(self):
        with pytest.raises(ValueError, match="at least 2 characters"):
            make_account(name="")

    def test_negative_opening_balance_raises(self):
        with pytest.raises(ValueError, match="cannot be negative"):
            make_account(opening_balance=Decimal("-1"))

    def test_opening_balance_is_quantized_to_two_decimals(self):
        account = make_account(opening_balance=Decimal("100.005"))
        assert account.opening_balance == account.opening_balance.quantize(Decimal("0.01"))

    def test_construction_takes_a_snapshot(self):
        make_account()
        assert len(AccountEntity._snapshots) == 1


# ============================================================================
# Lifecycle: create / update / delete / restore
# ============================================================================


class TestLifecycleCreateUpdateDeleteRestore:
    def test_create_records_audit_and_returns_self(self):
        account = make_account()
        result = account.create("user_a")
        assert result is account
        assert account.audit_trail()[-1]["action"] == "CREATE"

    def test_update_flat_code_succeeds(self):
        account = make_account()
        updated = account.update("user_b", name="Cash Renamed")
        assert updated.name == "Cash Renamed"
        assert updated.version == account.version + 1
        assert updated.updated_by == "user_b"

    def test_update_raises_for_hierarchical_code(self):
        """BUG-ACCOUNT-001: update() round-trips through to_dict()/from_dict(),
        and from_dict() always uses the default numeric-only pattern with no
        separator -- so any hierarchical code breaks update()."""
        hierarchical_code = AccountCodeVO("1.10.01", separator=".", pattern=r"^[0-9.]{1,20}$")
        account = make_account(code=hierarchical_code)
        with pytest.raises(AccountCodeFormatError, match="does not match pattern"):
            account.update("user_b", name="Renamed")

    def test_update_on_non_modifiable_status_raises(self):
        account = make_account(status=AccountStatus.LOCKED)
        with pytest.raises(ValueError, match="Cannot update account in status locked"):
            account.update("user_b", name="Renamed")

    def test_update_does_not_allow_overriding_protected_fields(self):
        account = make_account()
        original_id = account.id
        updated = account.update("user_b", id=str(uuid4()), created_by="hacker", version=999)
        assert updated.id == original_id  # protected fields ignored
        assert updated.created_by == account.created_by
        assert updated.version == account.version + 1  # computed normally, not from kwargs

    def test_delete_from_draft_succeeds(self):
        account = make_account(status=AccountStatus.DRAFT)
        deleted = account.delete("user_c", reason="duplicate")
        assert deleted.status == AccountStatus.CLOSED

    def test_delete_from_active_raises(self):
        account = make_account(status=AccountStatus.ACTIVE)
        with pytest.raises(ValueError, match="Cannot delete account in status active"):
            account.delete("user_c")

    def test_restore_from_closed_succeeds(self):
        account = make_account(status=AccountStatus.CLOSED)
        restored = account.restore("user_d")
        assert restored.status == AccountStatus.DRAFT

    def test_restore_from_non_closed_raises(self):
        account = make_account(status=AccountStatus.DRAFT)
        with pytest.raises(ValueError, match="Cannot restore account in status draft"):
            account.restore("user_d")


# ============================================================================
# Lifecycle: activate / deactivate / lock / unlock
# ============================================================================


class TestLifecycleActivateDeactivateLockUnlock:
    def test_activate_from_draft_succeeds(self):
        account = make_account(status=AccountStatus.DRAFT)
        activated = account.activate("user_e")
        assert activated.status == AccountStatus.ACTIVE

    def test_activate_from_non_draft_raises(self):
        account = make_account(status=AccountStatus.ACTIVE)
        with pytest.raises(ValueError, match="Cannot activate account in status active"):
            account.activate("user_e")

    def test_deactivate_from_active_succeeds(self):
        account = make_account(status=AccountStatus.ACTIVE)
        deactivated = account.deactivate("user_f", reason="temporary freeze")
        assert deactivated.status == AccountStatus.SUSPENDED

    def test_deactivate_from_non_active_raises(self):
        account = make_account(status=AccountStatus.DRAFT)
        with pytest.raises(ValueError, match="Cannot deactivate account in status draft"):
            account.deactivate("user_f")

    def test_lock_from_active_succeeds(self):
        account = make_account(status=AccountStatus.ACTIVE)
        locked = account.lock("user_g", reason="fraud investigation")
        assert locked.status == AccountStatus.LOCKED

    def test_lock_from_suspended_succeeds(self):
        account = make_account(status=AccountStatus.SUSPENDED)
        locked = account.lock("user_g", reason="fraud investigation")
        assert locked.status == AccountStatus.LOCKED

    def test_lock_from_draft_raises(self):
        account = make_account(status=AccountStatus.DRAFT)
        with pytest.raises(ValueError, match="Cannot lock account in status draft"):
            account.lock("user_g", reason="x")

    def test_unlock_from_locked_succeeds(self):
        account = make_account(status=AccountStatus.LOCKED)
        unlocked = account.unlock("user_h")
        assert unlocked.status == AccountStatus.ACTIVE

    def test_unlock_from_non_locked_raises(self):
        account = make_account(status=AccountStatus.ACTIVE)
        with pytest.raises(ValueError, match="Cannot unlock account in status active"):
            account.unlock("user_h")


# ============================================================================
# validate() / touch()
# ============================================================================


class TestValidateAndTouch:
    def test_validate_valid_account(self):
        account = make_account()
        result = account.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_touch_creates_new_version(self):
        account = make_account()
        touched = account.touch("user_i")
        assert touched.version == account.version + 1
        assert touched.updated_by == "user_i"
        assert touched is not account


# ============================================================================
# clone()
# ============================================================================


class TestClone:
    def test_clone_with_explicit_code_succeeds(self):
        account = make_account()
        cloned = account.clone(new_code="1001")
        assert cloned.code.code == "1001"
        assert cloned.status == AccountStatus.DRAFT
        assert cloned.id != account.id
        assert "(COPY)" in cloned.name

    def test_clone_without_explicit_code_raises(self):
        """BUG-ACCOUNT-002: the default new_code ("<code>_COPY") contains
        letters/underscore and fails the default numeric-only pattern."""
        account = make_account()
        with pytest.raises(AccountCodeFormatError, match="does not match pattern"):
            account.clone()

    def test_clone_resets_balance_and_version(self):
        account = make_account(opening_balance=Decimal("500"))
        cloned = account.clone(new_code="1002")
        assert cloned.opening_balance == Decimal("0")
        assert cloned.version == 1


# ============================================================================
# Serialization
# ============================================================================


class TestSerialization:
    def test_to_dict_contains_expected_fields(self):
        account = make_account()
        d = account.to_dict()
        assert d["code"] == "1000"
        assert d["name"] == "Cash"
        assert d["account_type"] == "asset"
        assert d["normal_balance"] == "debit"
        assert d["status"] == "draft"

    def test_to_dict_excludes_metadata_when_absent(self):
        account = make_account()
        d = account.to_dict()
        assert "metadata" not in d

    def test_to_dict_includes_metadata_when_present_and_requested(self):
        account = make_account(metadata={"tag": "important"})
        d = account.to_dict()
        assert d["metadata"] == {"tag": "important"}

    def test_to_dict_can_exclude_metadata_explicitly(self):
        account = make_account(metadata={"tag": "important"})
        d = account.to_dict(include_metadata=False)
        assert "metadata" not in d

    def test_from_dict_round_trip_for_flat_numeric_code(self):
        account = make_account()
        d = account.to_dict()
        restored = AccountEntity.from_dict(d)
        assert restored.id == account.id
        assert restored.code.code == account.code.code
        assert restored.name == account.name

    def test_snapshot_contains_expected_fields(self):
        account = make_account()
        snap = account.snapshot()
        assert snap["code"] == "1000"
        assert snap["status"] == "draft"
        assert "timestamp" in snap

    def test_get_version(self):
        account = make_account()
        assert account.get_version() == 1


# ============================================================================
# Property aliases
# ============================================================================


class TestPropertyAliases:
    def test_account_id_alias(self):
        account = make_account()
        assert account.account_id == account.id

    def test_account_code_alias(self):
        account = make_account()
        assert account.account_code == "1000"

    def test_account_name_alias(self):
        account = make_account()
        assert account.account_name == "Cash"

    def test_parent_account_id_alias(self):
        parent_id = uuid4()
        account = make_account(parent_id=parent_id)
        assert account.parent_account_id == parent_id

    def test_is_active_property(self):
        assert make_account(status=AccountStatus.ACTIVE).is_active is True
        assert make_account(status=AccountStatus.DRAFT).is_active is False

    def test_account_alias_is_account_entity(self):
        assert Account is AccountEntity


# ============================================================================
# Shared ClassVar audit trail (BUG-ACCOUNT-003)
# ============================================================================


class TestSharedAuditTrailAcrossInstances:
    def test_audit_trail_is_shared_between_unrelated_accounts(self):
        """Confirms _audit_trail is a single ClassVar list shared by every
        AccountEntity instance: recording an action on one account is
        visible through any other account's `.audit_trail()` call too."""
        account_a = make_account(name="Account A")
        account_b = make_account(name="Account B")
        account_a.create("user_a")
        account_b.create("user_b")
        assert account_a._audit_trail is account_b._audit_trail
        assert len(account_a.audit_trail()) == 2
        assert len(account_b.audit_trail()) == 2


# ============================================================================
# AccountRepository (real in-memory implementation)
# ============================================================================


class TestAccountRepository:
    @pytest.fixture
    def repo(self):
        return AccountRepository()

    @pytest.fixture
    def legal_entity_id(self):
        return uuid4()

    async def test_save_and_get_by_id(self, repo, legal_entity_id):
        account = make_account(legal_entity_id=legal_entity_id)
        await repo.save(account, legal_entity_id)
        fetched = await repo.get_by_id(account.id, legal_entity_id)
        assert fetched is account

    async def test_get_by_id_missing_returns_none(self, repo, legal_entity_id):
        assert await repo.get_by_id(uuid4(), legal_entity_id) is None

    async def test_get_by_code(self, repo, legal_entity_id):
        account = make_account(legal_entity_id=legal_entity_id, code=AccountCodeVO("2000"))
        await repo.save(account, legal_entity_id)
        fetched = await repo.get_by_code("2000", legal_entity_id)
        assert fetched is account

    async def test_get_by_code_with_vo_argument(self, repo, legal_entity_id):
        account = make_account(legal_entity_id=legal_entity_id, code=AccountCodeVO("2001"))
        await repo.save(account, legal_entity_id)
        fetched = await repo.get_by_code(AccountCodeVO("2001"), legal_entity_id)
        assert fetched is account

    async def test_get_all_excludes_inactive_by_default(self, repo, legal_entity_id):
        draft_account = make_account(legal_entity_id=legal_entity_id, code=AccountCodeVO("3000"))
        active_account = make_account(
            legal_entity_id=legal_entity_id, code=AccountCodeVO("3001"), status=AccountStatus.ACTIVE,
        )
        await repo.save(draft_account, legal_entity_id)
        await repo.save(active_account, legal_entity_id)
        active_only = await repo.get_all(legal_entity_id)
        assert active_only == [active_account]

    async def test_get_all_include_inactive(self, repo, legal_entity_id):
        draft_account = make_account(legal_entity_id=legal_entity_id, code=AccountCodeVO("3000"))
        await repo.save(draft_account, legal_entity_id)
        everything = await repo.get_all(legal_entity_id, include_inactive=True)
        assert draft_account in everything

    async def test_get_children_and_descendants(self, repo, legal_entity_id):
        root = make_account(legal_entity_id=legal_entity_id, code=AccountCodeVO("1000"))
        await repo.save(root, legal_entity_id)
        child = make_account(
            legal_entity_id=legal_entity_id, code=AccountCodeVO("1001"), parent_id=root.id,
        )
        await repo.save(child, legal_entity_id)
        grandchild = make_account(
            legal_entity_id=legal_entity_id, code=AccountCodeVO("1002"), parent_id=child.id,
        )
        await repo.save(grandchild, legal_entity_id)

        children = await repo.get_children(root.id, legal_entity_id)
        assert children == [child]

        descendants = await repo.get_descendants(root.id, legal_entity_id)
        assert {a.id for a in descendants} == {child.id, grandchild.id}

    async def test_get_root_accounts(self, repo, legal_entity_id):
        root = make_account(legal_entity_id=legal_entity_id, code=AccountCodeVO("1000"))
        child = make_account(
            legal_entity_id=legal_entity_id, code=AccountCodeVO("1001"), parent_id=root.id,
        )
        await repo.save(root, legal_entity_id)
        await repo.save(child, legal_entity_id)
        roots = await repo.get_root_accounts(legal_entity_id)
        assert roots == [root]

    async def test_update_saves_new_version(self, repo, legal_entity_id):
        account = make_account(legal_entity_id=legal_entity_id)
        await repo.save(account, legal_entity_id)
        updated = account.update("user_x", name="New Name")
        await repo.update(updated, legal_entity_id)
        fetched = await repo.get_by_id(account.id, legal_entity_id)
        assert fetched.name == "New Name"

    async def test_delete_removes_account(self, repo, legal_entity_id):
        account = make_account(legal_entity_id=legal_entity_id)
        await repo.save(account, legal_entity_id)
        await repo.delete(account.id, legal_entity_id)
        assert await repo.get_by_id(account.id, legal_entity_id) is None

    async def test_delete_nonexistent_does_not_raise(self, repo, legal_entity_id):
        await repo.delete(uuid4(), legal_entity_id)  # should not raise

    async def test_exists_and_exists_by_code(self, repo, legal_entity_id):
        account = make_account(legal_entity_id=legal_entity_id, code=AccountCodeVO("4000"))
        await repo.save(account, legal_entity_id)
        assert await repo.exists(account.id, legal_entity_id) is True
        assert await repo.exists(uuid4(), legal_entity_id) is False
        assert await repo.exists_by_code("4000", legal_entity_id) is True
        assert await repo.exists_by_code("9999", legal_entity_id) is False

    async def test_count(self, repo, legal_entity_id):
        await repo.save(make_account(legal_entity_id=legal_entity_id, code=AccountCodeVO("5000")), legal_entity_id)
        await repo.save(make_account(legal_entity_id=legal_entity_id, code=AccountCodeVO("5001")), legal_entity_id)
        assert await repo.count(legal_entity_id) == 2

    async def test_list_with_limit_and_offset(self, repo, legal_entity_id):
        for i in range(5):
            await repo.save(
                make_account(legal_entity_id=legal_entity_id, code=AccountCodeVO(f"600{i}")),
                legal_entity_id,
            )
        page = await repo.list(legal_entity_id, limit=2, offset=1)
        assert len(page) == 2

    async def test_paginate(self, repo, legal_entity_id):
        for i in range(5):
            await repo.save(
                make_account(legal_entity_id=legal_entity_id, code=AccountCodeVO(f"700{i}")),
                legal_entity_id,
            )
        page, total = await repo.paginate(legal_entity_id, page=1, per_page=2)
        assert total == 5
        assert len(page) == 2

    async def test_search_matches_name(self, repo, legal_entity_id):
        account = make_account(legal_entity_id=legal_entity_id, code=AccountCodeVO("8000"), name="Petty Cash")
        await repo.save(account, legal_entity_id)
        results = await repo.search(legal_entity_id, "petty")
        assert account in results

    async def test_search_no_match_returns_empty(self, repo, legal_entity_id):
        account = make_account(legal_entity_id=legal_entity_id, code=AccountCodeVO("8001"), name="Cash")
        await repo.save(account, legal_entity_id)
        results = await repo.search(legal_entity_id, "nonexistent_term")
        assert results == []

    async def test_lock_via_repository(self, repo, legal_entity_id):
        account = make_account(legal_entity_id=legal_entity_id, status=AccountStatus.ACTIVE)
        await repo.save(account, legal_entity_id)
        locked = await repo.lock(account.id, legal_entity_id, "user_a", "investigation")
        assert locked.status == AccountStatus.LOCKED
        fetched = await repo.get_by_id(account.id, legal_entity_id)
        assert fetched.status == AccountStatus.LOCKED

    async def test_lock_via_repository_nonexistent_raises(self, repo, legal_entity_id):
        with pytest.raises(ValueError, match="not found"):
            await repo.lock(uuid4(), legal_entity_id, "user_a", "reason")

    async def test_unlock_via_repository(self, repo, legal_entity_id):
        account = make_account(legal_entity_id=legal_entity_id, status=AccountStatus.LOCKED)
        await repo.save(account, legal_entity_id)
        unlocked = await repo.unlock(account.id, legal_entity_id, "user_b")
        assert unlocked.status == AccountStatus.ACTIVE

    async def test_unlock_via_repository_nonexistent_raises(self, repo, legal_entity_id):
        with pytest.raises(ValueError, match="not found"):
            await repo.unlock(uuid4(), legal_entity_id, "user_b")

    async def test_storage_is_isolated_per_legal_entity(self, repo):
        legal_entity_a = uuid4()
        legal_entity_b = uuid4()
        account = make_account(legal_entity_id=legal_entity_a)
        await repo.save(account, legal_entity_a)
        assert await repo.get_by_id(account.id, legal_entity_a) is not None
        assert await repo.get_by_id(account.id, legal_entity_b) is None
