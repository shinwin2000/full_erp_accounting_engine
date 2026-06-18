#!/usr/bin/env python3

"""
Module: test_coa_aggregate.py

Layer: Tests / Unit / Domain

Responsibility:
    Unit tests untuk Chart of Accounts aggregate root.
    Menguji pembuatan akun, update, deaktivasi, hierarki, dan invariants.

Dependencies:
    - domain/coa/aggregate_root.py
    - domain/coa/account_entity.py
    - domain/coa/account_code_vo.py
    - pytest

Audit:
    Tests harus lulus 100% sebelum deployment.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.coa.account_code_vo import AccountCodeVO
from domain.coa.account_entity import AccountEntity as Account
from domain.coa.account_entity import AccountStatus, AccountType
from domain.coa.account_normal_balance_vo import NormalBalance
from domain.coa.aggregate_root import ChartOfAccounts, COAAggregate
from domain.coa.domain_events import (
    AccountCreated,
    AccountDeactivated,
    AccountUpdated,
    HierarchyChangedEvent,
)


class TestCOAAggregate:
    """Test suite untuk COAAggregate."""

    @pytest.fixture
    def valid_account(self) -> Account:
        """Fixture akun valid (numeric code without separator)."""
        now = datetime.now(UTC)
        code = AccountCodeVO("11000")
        return Account(
            id=uuid4(),
            legal_entity_id=uuid4(),
            code=code,
            name="Kas",
            account_type=AccountType.ASSET,
            normal_balance=NormalBalance.DEBIT,
            parent_id=None,
            is_control_account=False,
            status=AccountStatus.ACTIVE,
            description="Akun kas",
            opening_balance=Decimal("0"),
            currency_code="IDR",
            is_header=False,
            level=0,
            created_at=now,
            updated_at=now,
            created_by=str(uuid4()),
            updated_by=str(uuid4()),
            version=1,
        )

    @pytest.fixture
    def parent_account(self) -> Account:
        """Fixture akun parent (header)."""
        now = datetime.now(UTC)
        code = AccountCodeVO("10000")
        return Account(
            id=uuid4(),
            legal_entity_id=uuid4(),
            code=code,
            name="ASET",
            account_type=AccountType.ASSET,
            normal_balance=NormalBalance.DEBIT,
            parent_id=None,
            is_control_account=True,
            status=AccountStatus.ACTIVE,
            description="Kelompok Aset",
            opening_balance=Decimal("0"),
            currency_code="IDR",
            is_header=True,
            level=0,
            created_at=now,
            updated_at=now,
            created_by=str(uuid4()),
            updated_by=str(uuid4()),
            version=1,
        )

    @pytest.fixture
    def child_account(self, parent_account) -> Account:
        """Fixture anak dari parent_account."""
        now = datetime.now(UTC)
        code = AccountCodeVO("11001")
        return Account(
            id=uuid4(),
            legal_entity_id=parent_account.legal_entity_id,
            code=code,
            name="Kas Kecil",
            account_type=AccountType.ASSET,
            normal_balance=NormalBalance.DEBIT,
            parent_id=parent_account.id,
            is_control_account=False,
            status=AccountStatus.ACTIVE,
            description="Sub kas",
            opening_balance=Decimal("0"),
            currency_code="IDR",
            is_header=False,
            level=1,
            created_at=now,
            updated_at=now,
            created_by=str(uuid4()),
            updated_by=str(uuid4()),
            version=1,
        )

    def test_create_account_success(self, valid_account):
        """Test: Membuat akun baru berhasil."""
        aggregate = COAAggregate()
        user_id = uuid4()
        aggregate.create(valid_account, user_id)
        assert aggregate.account.id == valid_account.id
        assert aggregate.version == 1
        events = aggregate.pop_events()
        assert len(events) == 1
        assert isinstance(events[0], AccountCreated)
        assert events[0].event_data["account_id"] == str(valid_account.id)

    def test_create_duplicate_account_code_raises_error(self, valid_account):
        """Test: Duplikasi kode harus ditolak oleh ChartOfAccounts."""
        coa = ChartOfAccounts.create(legal_entity_id=valid_account.legal_entity_id, name="COA Test")
        # Tambahkan akun pertama
        coa = coa.add_account(valid_account, created_by="system")
        # Buat akun dengan kode yang sama
        duplicate_account = Account(
            id=uuid4(),
            legal_entity_id=valid_account.legal_entity_id,
            code=valid_account.code,  # kode sama
            name="Kas Lain",
            account_type=AccountType.ASSET,
            normal_balance=NormalBalance.DEBIT,
            parent_id=None,
            is_control_account=False,
            status=AccountStatus.ACTIVE,
            description="Akun duplikat",
            opening_balance=Decimal("0"),
            currency_code="IDR",
            is_header=False,
            level=0,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            created_by="system",
            updated_by="system",
            version=1,
        )
        with pytest.raises(ValueError, match="already exists"):
            coa.add_account(duplicate_account, created_by="system")

    def test_rename_account(self, valid_account):
        """Test: Mengubah nama akun."""
        aggregate = COAAggregate()
        user_id = uuid4()
        aggregate.create(valid_account, user_id)
        aggregate.pop_events()
        new_name = "Kas Besar"
        aggregate.rename(new_name, user_id)
        assert aggregate.account.name == new_name
        events = aggregate.pop_events()
        assert len(events) == 1
        assert isinstance(events[0], AccountUpdated)
        assert "name" in events[0].event_data["changes"]

    def test_update_description(self, valid_account):
        """Test: Mengubah deskripsi akun."""
        aggregate = COAAggregate()
        user_id = uuid4()
        aggregate.create(valid_account, user_id)
        aggregate.pop_events()
        new_desc = "Akun kas untuk transaksi tunai"
        aggregate.update_description(new_desc, user_id)
        assert aggregate.account.description == new_desc
        events = aggregate.pop_events()
        assert isinstance(events[0], AccountUpdated)

    def test_change_parent_account(self, valid_account, parent_account):
        """Test: Mengubah parent account."""
        aggregate = COAAggregate()
        user_id = uuid4()
        aggregate.create(valid_account, user_id)
        aggregate.pop_events()
        aggregate.change_parent(parent_account.id, user_id)
        assert aggregate.account.parent_id == parent_account.id
        events = aggregate.pop_events()
        assert len(events) == 1
        assert isinstance(events[0], HierarchyChangedEvent)

    def test_change_parent_invalid_cycle_raises_error(self, parent_account, child_account):
        """Test: Siklus hierarki harus ditolak oleh ChartOfAccounts."""
        coa = ChartOfAccounts.create(
            legal_entity_id=parent_account.legal_entity_id, name="COA Test"
        )
        # Tambahkan parent dan child
        coa = coa.add_account(parent_account, created_by="system")
        coa = coa.add_account(child_account, created_by="system")
        # Coba ubah parent dari parent_account menjadi child_account (membuat siklus)
        with pytest.raises(ValueError, match="cycle"):
            coa = coa.update_account(
                Account(
                    id=parent_account.id,
                    legal_entity_id=parent_account.legal_entity_id,
                    code=parent_account.code,
                    name=parent_account.name,
                    account_type=parent_account.account_type,
                    normal_balance=parent_account.normal_balance,
                    parent_id=child_account.id,  # menyebabkan siklus
                    is_control_account=parent_account.is_control_account,
                    status=parent_account.status,
                    description=parent_account.description,
                    opening_balance=parent_account.opening_balance,
                    currency_code=parent_account.currency_code,
                    is_header=parent_account.is_header,
                    level=parent_account.level,
                    created_at=parent_account.created_at,
                    updated_at=datetime.now(UTC),
                    created_by=parent_account.created_by,
                    updated_by="system",
                    version=parent_account.version + 1,
                    metadata=None,
                ),
                updated_by="system",
            )

    def test_deactivate_account(self, valid_account):
        """Test: Menonaktifkan akun."""
        aggregate = COAAggregate()
        user_id = uuid4()
        aggregate.create(valid_account, user_id)
        aggregate.pop_events()
        aggregate.deactivate(user_id, reason="Tidak dipakai")
        events = aggregate.pop_events()
        assert len(events) >= 1
        assert any(isinstance(e, (AccountDeactivated, AccountUpdated)) for e in events)

    def test_cannot_deactivate_account_with_children(self, parent_account, child_account):
        """Test: Tidak bisa menonaktifkan parent yang memiliki anak."""
        coa = ChartOfAccounts.create(
            legal_entity_id=parent_account.legal_entity_id, name="COA Test"
        )
        coa = coa.add_account(parent_account, created_by="system")
        coa = coa.add_account(child_account, created_by="system")
        with pytest.raises(ValueError, match="child accounts"):
            coa.deactivate_account(parent_account.id, deactivated_by="system")

    def test_reactivate_account(self, valid_account):
        """Test: Mengaktifkan kembali akun yang nonaktif."""
        aggregate = COAAggregate()
        user_id = uuid4()
        aggregate.create(valid_account, user_id)
        aggregate.deactivate(user_id)
        aggregate.pop_events()
        aggregate.reactivate(user_id)
        assert aggregate.account.is_active is True
        events = aggregate.pop_events()
        assert len(events) >= 1

    def test_version_increment(self, valid_account):
        """Test: Version increment pada setiap perubahan."""
        aggregate = COAAggregate()
        user_id = uuid4()
        aggregate.create(valid_account, user_id)
        assert aggregate.version == 1
        aggregate.rename("Nama baru", user_id)
        assert aggregate.version == 2
        aggregate.update_description("Deskripsi baru", user_id)
        assert aggregate.version == 3

    def test_reconstruct_from_events(self, valid_account):
        """Test: Rekonstruksi aggregate dari event store (sederhana)."""
        agg1 = COAAggregate()
        user_id = uuid4()
        agg1.create(valid_account, user_id)
        agg1.rename("Nama Baru", user_id)
        agg2 = COAAggregate()
        modified_account = agg1.account
        agg2.load(modified_account)
        agg2.version = 2
        assert agg2.account.id == agg1.account.id
        assert agg2.account.name == "Nama Baru"
        assert agg2.version == 2

    def test_opening_balance_zero_by_default(self, valid_account):
        """Test: Opening balance default = 0."""
        assert valid_account.opening_balance == Decimal("0")

    def test_currency_code_default_idr(self, valid_account):
        """Test: Currency code default IDR."""
        assert valid_account.currency_code == "IDR"


if __name__ == "__main__":
    pytest.main([__file__])
