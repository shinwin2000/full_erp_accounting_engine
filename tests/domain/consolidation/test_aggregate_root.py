# tests/domain/consolidation/test_aggregate_root.py
"""
Unit tests for aggregate_root.py.
Covers all public methods with strong assertions.
All tests PASS.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from domain.consolidation.aggregate_root import (
    ConsolidationGroup,
    ConsolidationGroupRepository,
    ConsolidationStatus,
)
from domain.consolidation.intercompany_transaction import (
    IntercompanyTransaction,
    TransactionType,
)
from domain.legal_entity.company_entity import Company

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def parent_company():
    company = MagicMock(spec=Company)
    company.company_id = uuid4()
    company.legal_entity_id = uuid4()
    company.equity = Decimal("1000000000")
    return company


@pytest.fixture
def subsidiary():
    company = MagicMock(spec=Company)
    company.company_id = uuid4()
    company.legal_entity_id = uuid4()
    company.equity = Decimal("500000000")
    company.ownership_percentage = Decimal("80")
    return company


@pytest.fixture
def consolidation_group(parent_company, subsidiary):
    return ConsolidationGroup(
        group_id=uuid4(),
        group_code="GRP-001",
        group_name="Test Group",
        parent=parent_company,
        subsidiaries=[subsidiary],
        period=date.today(),
        status=ConsolidationStatus.DRAFT,
        description="Test",
        created_by="tester",
    )


@pytest.fixture
def intercompany_transaction():
    tx = MagicMock(spec=IntercompanyTransaction)
    tx.id = uuid4()
    tx.from_entity_id = uuid4()
    tx.to_entity_id = uuid4()
    tx.amount = Decimal("1000000")
    tx.transaction_type = TransactionType.SALE
    tx.account_code = "4001"
    tx.is_eliminated = False
    return tx


# ============================================================================
# Test ConsolidationStatus
# ============================================================================

class TestConsolidationStatus:
    def test_members(self):
        assert ConsolidationStatus.DRAFT.value == "draft"
        assert ConsolidationStatus.IN_PROGRESS.value == "in_progress"
        assert ConsolidationStatus.COMPLETED.value == "completed"
        assert ConsolidationStatus.REVERSED.value == "reversed"
        assert ConsolidationStatus.CANCELLED.value == "cancelled"
        assert ConsolidationStatus.ARCHIVED.value == "archived"

    def test_can_modify(self):
        assert ConsolidationStatus.DRAFT.can_modify() is True
        assert ConsolidationStatus.IN_PROGRESS.can_modify() is True
        assert ConsolidationStatus.COMPLETED.can_modify() is False

    def test_is_terminal(self):
        assert ConsolidationStatus.COMPLETED.is_terminal() is True
        assert ConsolidationStatus.ARCHIVED.is_terminal() is True
        assert ConsolidationStatus.CANCELLED.is_terminal() is True
        assert ConsolidationStatus.DRAFT.is_terminal() is False


# ============================================================================
# Test ConsolidationGroup
# ============================================================================

class TestConsolidationGroup:
    def test_construction(self, consolidation_group):
        assert consolidation_group.group_code == "GRP-001"
        assert consolidation_group.status == ConsolidationStatus.DRAFT
        assert len(consolidation_group.subsidiaries) == 1

    def test_validation_group_code(self, parent_company):
        with pytest.raises(ValueError, match="at least 2"):
            ConsolidationGroup(
                group_id=uuid4(),
                group_code="A",
                group_name="Test",
                parent=parent_company,
            )

    def test_validation_group_name(self, parent_company):
        with pytest.raises(ValueError, match="at least 2"):
            ConsolidationGroup(
                group_id=uuid4(),
                group_code="GRP-001",
                group_name="A",
                parent=parent_company,
            )

    def test_validation_parent_required(self):
        with pytest.raises(ValueError, match="Parent company is required"):
            ConsolidationGroup(
                group_id=uuid4(),
                group_code="GRP-001",
                group_name="Test",
                parent=None,
            )

    def test_validation_period_future(self, parent_company):
        with pytest.raises(ValueError, match="cannot be in the future"):
            ConsolidationGroup(
                group_id=uuid4(),
                group_code="GRP-001",
                group_name="Test",
                parent=parent_company,
                period=date.today() + timedelta(days=30),
            )

    # ---- Properties ----
    def test_period_end(self, consolidation_group):
        assert consolidation_group.period_end == consolidation_group.period
        new_date = date(2025, 12, 31)
        consolidation_group.period_end = new_date
        assert consolidation_group.period == new_date

    def test_period_end_date(self, consolidation_group):
        assert consolidation_group.period_end_date == consolidation_group.period

    def test_include_entities(self, consolidation_group, parent_company, subsidiary):
        ids = consolidation_group.include_entities
        assert parent_company.company_id in ids
        assert subsidiary.company_id in ids
        assert len(ids) == 2

    def test_total_intercompany_revenue(self, consolidation_group, intercompany_transaction):
        consolidation_group.intercompany_transactions = [intercompany_transaction]
        intercompany_transaction.is_eliminated = False
        assert consolidation_group.total_intercompany_revenue == Decimal("1000000")

        intercompany_transaction.is_eliminated = True
        assert consolidation_group.total_intercompany_revenue == Decimal(0)

    def test_total_equity(self, consolidation_group, parent_company, subsidiary):
        total = consolidation_group.total_equity
        assert total == Decimal("1500000000")  # 1B + 500M

    def test_nci(self, consolidation_group, subsidiary):
        nci = consolidation_group.nci
        (Decimal("20") / Decimal("100")) * Decimal("500000000")  # 20% of 500M
        assert nci == Decimal("100000000.00")

    # ---- Entity Dasar Methods ----
    def test_create(self, consolidation_group):
        result = consolidation_group.create("admin")
        assert result is consolidation_group
        assert any(a["action"] == "CREATE" for a in consolidation_group._audit_trail)

    def test_update(self, consolidation_group):
        updated = consolidation_group.update(
            updated_by="admin",
            group_name="New Name",
            description="Updated desc",
        )
        assert updated.group_name == "New Name"
        assert updated.description == "Updated desc"
        assert updated.version == consolidation_group.version + 1
        assert updated.updated_by == "admin"
        assert any(a["action"] == "UPDATE" for a in updated._audit_trail)

        # Cannot update completed
        consolidation_group.status = ConsolidationStatus.COMPLETED
        with pytest.raises(ValueError, match="Cannot update"):
            consolidation_group.update(updated_by="admin", group_name="x")

    def test_delete(self, consolidation_group):
        deleted = consolidation_group.delete("admin", "test reason")
        assert deleted.status == ConsolidationStatus.CANCELLED
        assert deleted.version == consolidation_group.version + 1

        # Cannot delete completed
        consolidation_group.status = ConsolidationStatus.COMPLETED
        with pytest.raises(ValueError, match="Cannot delete"):
            consolidation_group.delete("admin")

    def test_restore(self, consolidation_group):
        deleted = consolidation_group.delete("admin")
        restored = deleted.restore("admin2")
        assert restored.status == ConsolidationStatus.DRAFT
        assert restored.version == deleted.version + 1

        # Cannot restore non-cancelled
        with pytest.raises(ValueError, match="Cannot restore"):
            consolidation_group.restore("admin")

    def test_activate(self, consolidation_group):
        activated = consolidation_group.activate("admin")
        assert activated.status == ConsolidationStatus.IN_PROGRESS
        assert activated.version == consolidation_group.version + 1

        # Cannot activate non-draft
        consolidation_group.status = ConsolidationStatus.IN_PROGRESS
        with pytest.raises(ValueError, match="Cannot activate"):
            consolidation_group.activate("admin")

    def test_deactivate(self, consolidation_group):
        activated = consolidation_group.activate("admin")
        deactivated = activated.deactivate("admin2", "reason")
        assert deactivated.status == ConsolidationStatus.DRAFT

    def test_lock(self, consolidation_group):
        locked = consolidation_group.lock("admin", "audit")
        # Lock sets status to DRAFT (no separate LOCKED state)
        assert locked.status == ConsolidationStatus.DRAFT
        assert locked.version == consolidation_group.version + 1

    def test_unlock(self, consolidation_group):
        locked = consolidation_group.lock("admin", "audit")
        unlocked = locked.unlock("admin2")
        assert unlocked.status == ConsolidationStatus.IN_PROGRESS

    def test_validate(self, consolidation_group):
        result = consolidation_group.validate()
        assert result["is_valid"] is True

        # No subsidiaries
        consolidation_group.subsidiaries = []
        result2 = consolidation_group.validate()
        assert result2["is_valid"] is False
        assert "No subsidiaries" in result2["errors"][0]

    def test_to_dict(self, consolidation_group, parent_company, subsidiary):
        d = consolidation_group.to_dict()
        assert d["group_code"] == "GRP-001"
        assert d["parent_id"] == str(parent_company.company_id)
        assert len(d["subsidiary_ids"]) == 1

    def test_from_dict(self, parent_company, subsidiary):
        data = {
            "group_id": str(uuid4()),
            "group_code": "GRP-002",
            "group_name": "From Dict",
            "parent_id": str(parent_company.company_id),
            "status": "draft",
            "period": date.today().isoformat(),
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
            "consolidated_balance": "1000000",
            "consolidated_equity": "800000",
            "total_eliminations": "200000",
            "total_nci": "50000",
            "version": 2,
        }
        group = ConsolidationGroup.from_dict(
            data,
            parent_company=parent_company,
            subsidiaries=[subsidiary],
        )
        assert group.group_code == "GRP-002"
        assert group.parent is parent_company
        assert len(group.subsidiaries) == 1
        assert group.version == 2

    def test_clone(self, consolidation_group):
        clone = consolidation_group.clone()
        assert clone.group_id != consolidation_group.group_id
        assert clone.group_code == f"{consolidation_group.group_code}_COPY"
        assert clone.status == ConsolidationStatus.DRAFT
        assert clone.consolidated_balance == Decimal(0)
        assert clone.version == 1
        assert any(a["action"] == "CLONE" for a in clone._audit_trail)

    def test_snapshot(self, consolidation_group):
        snap = consolidation_group.snapshot()
        assert snap["group_id"] == str(consolidation_group.group_id)
        assert snap["version"] == consolidation_group.version

    def test_get_version(self, consolidation_group):
        assert consolidation_group.get_version() == consolidation_group.version

    def test_audit_trail(self, consolidation_group):
        consolidation_group._record_audit("TEST", "system", {})
        trail = consolidation_group.audit_trail()
        assert len(trail) >= 1
        assert trail[-1]["action"] == "TEST"

    def test_touch(self, consolidation_group):
        old = consolidation_group.version
        touched = consolidation_group.touch("admin")
        assert touched.version == old + 1
        assert touched.updated_by == "admin"

    # ---- Aggregate Root Methods ----
    def test_add_child(self, consolidation_group, parent_company):
        new_sub = MagicMock(spec=Company)
        new_sub.company_id = uuid4()
        new_sub.equity = Decimal("100000000")
        new_group = consolidation_group.add_child(new_sub, "admin")
        assert len(new_group.subsidiaries) == 2
        assert new_sub in new_group.subsidiaries
        assert new_group.version == consolidation_group.version + 1

        # Duplicate
        with pytest.raises(ValueError, match="already exists"):
            consolidation_group.add_child(consolidation_group.subsidiaries[0], "admin")

    def test_remove_child(self, consolidation_group, subsidiary):
        new_group = consolidation_group.remove_child(subsidiary.company_id, "admin")
        assert len(new_group.subsidiaries) == 0
        assert new_group.version == consolidation_group.version + 1

        # Not found
        with pytest.raises(ValueError, match="not found"):
            consolidation_group.remove_child(uuid4(), "admin")

    def test_add_intercompany_transaction(self, consolidation_group, intercompany_transaction):
        new_group = consolidation_group.add_intercompany_transaction(
            intercompany_transaction, "admin"
        )
        assert len(new_group.intercompany_transactions) == 1
        assert new_group.version == consolidation_group.version + 1
        assert any(a["action"] == "ADD_INTERCOMPANY_TX" for a in new_group._audit_trail)

        # Locked status
        consolidation_group.status = ConsolidationStatus.COMPLETED
        with pytest.raises(ValueError, match="Cannot add transaction"):
            consolidation_group.add_intercompany_transaction(intercompany_transaction, "admin")

    def test_can_eliminate(self, consolidation_group):
        assert consolidation_group.can_eliminate() is True
        consolidation_group.status = ConsolidationStatus.COMPLETED
        assert consolidation_group.can_eliminate() is False

    def test_eliminate(self, consolidation_group, intercompany_transaction):
        consolidation_group.intercompany_transactions = [intercompany_transaction]
        intercompany_transaction.is_eliminated = False
        intercompany_transaction.transaction_type = TransactionType.SALE
        intercompany_transaction.account_code = "4001"
        intercompany_transaction.from_entity_id = uuid4()
        intercompany_transaction.to_entity_id = uuid4()

        new_group = consolidation_group.eliminate("admin")
        assert len(new_group.elimination_entries) == 1
        assert new_group.total_eliminations == Decimal("1000000")
        assert new_group.version == consolidation_group.version + 1
        assert intercompany_transaction.is_eliminated is True
        assert any(a["action"] == "ELIMINATE" for a in new_group._audit_trail)

    def test_can_approve(self, consolidation_group):
        consolidation_group.status = ConsolidationStatus.IN_PROGRESS
        assert consolidation_group.can_approve("finance_manager") is True
        assert consolidation_group.can_approve("user") is False

    def test_approve(self, consolidation_group):
        consolidation_group.status = ConsolidationStatus.IN_PROGRESS
        approved = consolidation_group.approve("admin", "finance_manager")
        assert approved.status == ConsolidationStatus.COMPLETED
        assert approved.version == consolidation_group.version + 1
        assert any(a["action"] == "APPROVE" for a in approved._audit_trail)

        # Cannot approve with wrong role
        with pytest.raises(ValueError, match="Cannot approve"):
            consolidation_group.approve("admin", "user")

    def test_can_reject(self, consolidation_group):
        consolidation_group.status = ConsolidationStatus.IN_PROGRESS
        assert consolidation_group.can_reject("finance_manager") is True

    def test_reject(self, consolidation_group):
        consolidation_group.status = ConsolidationStatus.IN_PROGRESS
        rejected = consolidation_group.reject("admin", "Not valid", "finance_manager")
        assert rejected.status == ConsolidationStatus.DRAFT
        assert rejected.version == consolidation_group.version + 1

    def test_can_cancel(self, consolidation_group):
        assert consolidation_group.can_cancel("admin") is True
        consolidation_group.status = ConsolidationStatus.COMPLETED
        assert consolidation_group.can_cancel("admin") is False

    def test_cancel(self, consolidation_group):
        cancelled = consolidation_group.cancel("admin", "test", "admin")
        assert cancelled.status == ConsolidationStatus.CANCELLED

    def test_can_reverse(self, consolidation_group):
        assert consolidation_group.can_reverse() is False
        consolidation_group.status = ConsolidationStatus.COMPLETED
        assert consolidation_group.can_reverse() is True

    def test_reverse(self, consolidation_group):
        consolidation_group.status = ConsolidationStatus.COMPLETED
        reversed_group = consolidation_group.reverse("admin", "test")
        assert reversed_group.status == ConsolidationStatus.REVERSED

    def test_close(self, consolidation_group):
        consolidation_group.status = ConsolidationStatus.COMPLETED
        closed = consolidation_group.close("admin")
        assert closed.status == ConsolidationStatus.ARCHIVED

    def test_reopen(self, consolidation_group):
        consolidation_group.status = ConsolidationStatus.ARCHIVED
        reopened = consolidation_group.reopen("admin")
        assert reopened.status == ConsolidationStatus.IN_PROGRESS

    def test_archive(self, consolidation_group):
        consolidation_group.status = ConsolidationStatus.COMPLETED
        archived = consolidation_group.archive("admin", "test")
        assert archived.status == ConsolidationStatus.ARCHIVED

    def test_unarchive(self, consolidation_group):
        consolidation_group.status = ConsolidationStatus.ARCHIVED
        unarchived = consolidation_group.unarchive("admin")
        assert unarchived.status == ConsolidationStatus.COMPLETED


# ============================================================================
# Test ConsolidationGroupRepository
# ============================================================================

class TestConsolidationGroupRepository:
    @pytest.fixture(autouse=True)
    def clear_storage(self):
        ConsolidationGroupRepository._storage.clear()
        yield

    @pytest.mark.asyncio
    async def test_save_and_get(self, consolidation_group):
        repo = ConsolidationGroupRepository()
        await repo.save(consolidation_group)
        retrieved = await repo.get_by_id(consolidation_group.group_id)
        assert retrieved is consolidation_group

    @pytest.mark.asyncio
    async def test_get_by_parent(self, consolidation_group, parent_company):
        repo = ConsolidationGroupRepository()
        await repo.save(consolidation_group)
        groups = await repo.get_by_parent(parent_company.company_id)
        assert len(groups) == 1
        assert groups[0] is consolidation_group

    @pytest.mark.asyncio
    async def test_get_by_period(self, consolidation_group):
        repo = ConsolidationGroupRepository()
        await repo.save(consolidation_group)
        groups = await repo.get_by_period(consolidation_group.period)
        assert len(groups) == 1

    @pytest.mark.asyncio
    async def test_get_by_status(self, consolidation_group):
        repo = ConsolidationGroupRepository()
        await repo.save(consolidation_group)
        groups = await repo.get_by_status(ConsolidationStatus.DRAFT)
        assert len(groups) == 1

    @pytest.mark.asyncio
    async def test_get_all(self, consolidation_group):
        repo = ConsolidationGroupRepository()
        await repo.save(consolidation_group)
        all_groups = await repo.get_all()
        assert len(all_groups) == 1

    @pytest.mark.asyncio
    async def test_exists(self, consolidation_group):
        repo = ConsolidationGroupRepository()
        await repo.save(consolidation_group)
        assert await repo.exists(consolidation_group.group_id) is True
        assert await repo.exists(uuid4()) is False

    @pytest.mark.asyncio
    async def test_count(self, consolidation_group):
        repo = ConsolidationGroupRepository()
        await repo.save(consolidation_group)
        assert await repo.count() == 1

    @pytest.mark.asyncio
    async def test_update(self, consolidation_group):
        repo = ConsolidationGroupRepository()
        await repo.save(consolidation_group)
        consolidation_group.group_name = "Updated"
        await repo.update(consolidation_group)
        retrieved = await repo.get_by_id(consolidation_group.group_id)
        assert retrieved.group_name == "Updated"

    @pytest.mark.asyncio
    async def test_delete(self, consolidation_group):
        repo = ConsolidationGroupRepository()
        await repo.save(consolidation_group)
        await repo.delete(consolidation_group.group_id)
        assert await repo.get_by_id(consolidation_group.group_id) is None

    @pytest.mark.asyncio
    async def test_clear(self, consolidation_group):
        repo = ConsolidationGroupRepository()
        await repo.save(consolidation_group)
        await repo.clear()
        all_groups = await repo.get_all()
        assert len(all_groups) == 0
