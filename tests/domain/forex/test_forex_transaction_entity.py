# tests/domain/forex/test_forex_transaction_entity.py
"""
Comprehensive unit tests for Forex Transaction entity.

Covers:
- Entity construction, validation, and serialization
- All status transitions (confirm, settle, cancel)
- Basic entity methods (create, update, delete, restore, activate, deactivate)
- Lock/unlock, touch, clone, snapshot, audit trail
- Computed properties and helper methods
- In-memory repository (CRUD, filters)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from domain.forex.exchange_rate_vo import ExchangeRate
from domain.forex.forex_transaction_entity import (
    ForexTransaction,
    ForexTransactionError,
    ForexTransactionRepository,
    ForexTransactionStatus,
    ForexTransactionType,
)


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def legal_entity_id() -> UUID:
    return uuid4()


@pytest.fixture
def exchange_rate() -> ExchangeRate:
    """A valid exchange rate (1 USD = 15,000 IDR)."""
    return ExchangeRate(
        currency="USD",
        rate=Decimal("15000.00"),
        effective_date=datetime.now(UTC),
    )


@pytest.fixture
def transaction_kwargs(legal_entity_id, exchange_rate) -> dict[str, Any]:
    """Base kwargs for a valid ForexTransaction."""
    now = datetime.now(UTC)
    return {
        "transaction_id": uuid4(),
        "legal_entity_id": legal_entity_id,
        "transaction_number": "FX-2026-001",
        "transaction_type": ForexTransactionType.SPOT,
        "currency_from": "USD",
        "currency_to": "IDR",
        "amount_from": Decimal("1000.00"),
        "amount_to": Decimal("15000000.00"),  # 1000 * 15000
        "rate": exchange_rate,
        "transaction_date": now,
        "settlement_date": now + timedelta(days=2),
        "status": ForexTransactionStatus.DRAFT,
        "reference": "INV-123",
        "description": "Test transaction",
        "counterparty_id": uuid4(),
        "counterparty_name": "Counterparty Inc.",
        "created_by": "tester",
        "version": 1,
    }


@pytest.fixture
def transaction(transaction_kwargs) -> ForexTransaction:
    """A fully initialized ForexTransaction in DRAFT state."""
    return ForexTransaction(**transaction_kwargs)


@pytest.fixture
def confirmed_transaction(transaction) -> ForexTransaction:
    """Transaction in CONFIRMED state."""
    return transaction.confirm("confirm_user")


@pytest.fixture
def settled_transaction(transaction) -> ForexTransaction:
    """Transaction in SETTLED state."""
    confirmed = transaction.confirm("confirm_user")
    return confirmed.settle("settle_user")


# -----------------------------------------------------------------------------
# Tests for Enums
# -----------------------------------------------------------------------------

class TestForexTransactionType:
    def test_members(self):
        assert ForexTransactionType.REVALUATION.value == "revaluation"
        assert ForexTransactionType.SPOT.value == "spot"
        assert ForexTransactionType.FORWARD.value == "forward"
        assert ForexTransactionType.SWAP.value == "swap"
        assert ForexTransactionType.OPTION.value == "option"
        assert ForexTransactionType.SETTLEMENT.value == "settlement"

    def test_display_name(self):
        assert ForexTransactionType.SPOT.display_name() == "Spot"
        assert ForexTransactionType.REVALUATION.display_name() == "Revaluasi"


class TestForexTransactionStatus:
    def test_members(self):
        assert ForexTransactionStatus.DRAFT.value == "draft"
        assert ForexTransactionStatus.CONFIRMED.value == "confirmed"
        assert ForexTransactionStatus.SETTLED.value == "settled"
        assert ForexTransactionStatus.CANCELLED.value == "cancelled"

    def test_can_edit(self):
        assert ForexTransactionStatus.DRAFT.can_edit() is True
        assert ForexTransactionStatus.CONFIRMED.can_edit() is False
        assert ForexTransactionStatus.SETTLED.can_edit() is False
        assert ForexTransactionStatus.CANCELLED.can_edit() is False

    def test_can_settle(self):
        assert ForexTransactionStatus.DRAFT.can_settle() is False
        assert ForexTransactionStatus.CONFIRMED.can_settle() is True
        assert ForexTransactionStatus.SETTLED.can_settle() is False
        assert ForexTransactionStatus.CANCELLED.can_settle() is False

    def test_display_name(self):
        assert ForexTransactionStatus.DRAFT.display_name() == "Draft"
        assert ForexTransactionStatus.CONFIRMED.display_name() == "Dikonfirmasi"
        assert ForexTransactionStatus.SETTLED.display_name() == "Diselesaikan"
        assert ForexTransactionStatus.CANCELLED.display_name() == "Dibatalkan"


# -----------------------------------------------------------------------------
# Tests for Exception
# -----------------------------------------------------------------------------

class TestForexTransactionError:
    def test_is_value_error(self):
        error = ForexTransactionError("Test")
        assert isinstance(error, ValueError)


# -----------------------------------------------------------------------------
# Tests for ForexTransaction Entity
# -----------------------------------------------------------------------------

class TestForexTransaction:
    """Test the ForexTransaction entity."""

    def test_construction_success(self, transaction):
        assert transaction.transaction_id is not None
        assert transaction.legal_entity_id is not None
        assert transaction.transaction_number == "FX-2026-001"
        assert transaction.status == ForexTransactionStatus.DRAFT
        assert transaction.version == 1
        assert transaction.transaction_date.tzinfo is not None
        assert transaction.settlement_date is not None
        assert transaction.rate.rate == Decimal("15000.00")

    def test_validation_raises_for_short_number(self, transaction_kwargs):
        transaction_kwargs["transaction_number"] = "AB"
        with pytest.raises(ForexTransactionError, match="Transaction number must be at least 3"):
            ForexTransaction(**transaction_kwargs)

    def test_validation_raises_for_non_positive_amounts(self, transaction_kwargs):
        transaction_kwargs["amount_from"] = Decimal("0")
        with pytest.raises(ForexTransactionError, match="Amount from must be positive"):
            ForexTransaction(**transaction_kwargs)

        transaction_kwargs["amount_from"] = Decimal("100")
        transaction_kwargs["amount_to"] = Decimal("-1")
        with pytest.raises(ForexTransactionError, match="Amount to must be positive"):
            ForexTransaction(**transaction_kwargs)

    def test_validation_raises_for_settlement_before_transaction(self, transaction_kwargs):
        transaction_kwargs["settlement_date"] = transaction_kwargs["transaction_date"] - timedelta(days=1)
        with pytest.raises(ForexTransactionError, match="Settlement date .* cannot be before transaction date"):
            ForexTransaction(**transaction_kwargs)

    def test_validation_raises_for_naive_datetime(self, transaction_kwargs):
        transaction_kwargs["transaction_date"] = datetime.now()  # naive
        with pytest.raises(ForexTransactionError):
            ForexTransaction(**transaction_kwargs)

    def test_validation_raises_for_version_zero(self, transaction_kwargs):
        transaction_kwargs["version"] = 0
        with pytest.raises(ForexTransactionError, match="Version must be >= 1"):
            ForexTransaction(**transaction_kwargs)

    # ---- Basic entity methods ----

    def test_create(self, transaction):
        # create() records audit and returns self
        result = transaction.create("tester")
        assert result is transaction  # returns self
        assert len(transaction.audit_trail()) >= 1
        assert transaction.audit_trail()[-1]["action"] == "CREATE"

    def test_update(self, transaction):
        # Change amount_from
        new_amount = Decimal("2000")
        updated = transaction.update("updater", amount_from=new_amount)
        assert updated is not transaction
        assert updated.amount_from == new_amount
        # amount_to should also change proportionally? The update only changes what's passed.
        # The update method does not recalc amount_to, so we must test that it stays as set.
        # But the constructor would have set it; we'll just check that fields change.
        assert updated.amount_to == transaction.amount_to  # unchanged
        assert updated.version == transaction.version + 1
        assert updated.updated_at > transaction.updated_at
        assert updated.audit_trail()[-1]["action"] == "UPDATE"

    def test_update_raises_if_not_draft(self, confirmed_transaction):
        with pytest.raises(ForexTransactionError, match="Cannot update transaction in status confirmed"):
            confirmed_transaction.update("updater", amount_from=Decimal("500"))

    def test_delete(self, transaction):
        deleted = transaction.delete("tester", reason="Testing deletion")
        assert deleted.status == ForexTransactionStatus.CANCELLED
        assert deleted.cancelled_by == "tester"
        assert deleted.cancel_reason == "Testing deletion"
        assert deleted.version == transaction.version + 1

    def test_delete_raises_if_settled(self, settled_transaction):
        with pytest.raises(ForexTransactionError, match="Cannot delete settled transaction"):
            settled_transaction.delete("tester")

    def test_restore(self, transaction):
        cancelled = transaction.cancel("tester", "test")
        restored = cancelled.restore("admin")
        assert restored.status == ForexTransactionStatus.DRAFT
        assert restored.cancelled_by is None
        assert restored.cancelled_at is None
        assert restored.cancel_reason == ""
        assert restored.version == cancelled.version + 1

    def test_restore_raises_if_not_cancelled(self, transaction):
        with pytest.raises(ForexTransactionError, match="Cannot restore transaction in status draft"):
            transaction.restore("admin")

    def test_activate(self, transaction):
        # activate() delegates to confirm()
        activated = transaction.activate("admin")
        assert activated.status == ForexTransactionStatus.CONFIRMED
        assert activated.confirmed_by == "admin"
        assert activated.confirmed_at is not None

    def test_activate_raises_if_not_draft(self, confirmed_transaction):
        with pytest.raises(ForexTransactionError, match="Cannot activate transaction in status confirmed"):
            confirmed_transaction.activate("admin")

    def test_deactivate(self, transaction):
        deactivated = transaction.deactivate("admin", "test reason")
        assert deactivated.status == ForexTransactionStatus.CANCELLED
        assert deactivated.cancel_reason == "test reason"

    def test_deactivate_raises_if_not_draft(self, confirmed_transaction):
        with pytest.raises(ForexTransactionError, match="Cannot deactivate transaction in status confirmed"):
            confirmed_transaction.deactivate("admin")

    def test_lock_unlock(self, transaction):
        locked = transaction.lock("admin", "Audit")
        assert locked.metadata["locked_by"] == "admin"
        assert "locked_at" in locked.metadata
        assert locked.metadata["lock_reason"] == "Audit"
        unlocked = locked.unlock("admin")
        assert "locked_by" not in unlocked.metadata
        assert "locked_at" not in unlocked.metadata
        assert "lock_reason" not in unlocked.metadata

    def test_validate(self, transaction):
        result = transaction.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

        # Invalid: amount from negative
        invalid = transaction.update("tester", amount_from=Decimal("-100"))
        result2 = invalid.validate()
        assert result2["is_valid"] is False
        assert "Amount from must be positive" in result2["errors"][0]

    def test_to_dict_and_from_dict(self, transaction):
        d = transaction.to_dict()
        restored = ForexTransaction.from_dict(d)
        assert restored.transaction_id == transaction.transaction_id
        assert restored.legal_entity_id == transaction.legal_entity_id
        assert restored.transaction_number == transaction.transaction_number
        assert restored.amount_from == transaction.amount_from
        assert restored.amount_to == transaction.amount_to
        assert restored.rate.rate == transaction.rate.rate
        assert restored.status == transaction.status
        assert restored.created_at == transaction.created_at

    def test_clone(self, transaction):
        cloned = transaction.clone()
        assert cloned.transaction_id != transaction.transaction_id
        assert cloned.legal_entity_id == transaction.legal_entity_id
        assert cloned.transaction_number == transaction.transaction_number + "_COPY"
        assert cloned.status == ForexTransactionStatus.DRAFT
        assert cloned.version == 1
        assert cloned.audit_trail()[-1]["action"] == "CLONE"

    def test_snapshot(self, transaction):
        snap = transaction.snapshot()
        assert snap["transaction_id"] == str(transaction.transaction_id)
        assert snap["number"] == transaction.transaction_number
        assert snap["version"] == transaction.version
        assert "timestamp" in snap

    def test_get_version(self, transaction):
        assert transaction.get_version() == transaction.version

    def test_audit_trail(self, transaction):
        # Perform multiple actions
        transaction.create("tester")
        transaction.update("updater", amount_from=Decimal("2000"))
        trail = transaction.audit_trail(limit=2)
        assert len(trail) == 2
        assert trail[0]["action"] == "UPDATE"
        assert trail[1]["action"] == "CREATE"

    def test_touch(self, transaction):
        touched = transaction.touch("tester")
        assert touched.version == transaction.version + 1
        assert touched.updated_at > transaction.updated_at
        assert touched.audit_trail()[-1]["action"] == "TOUCH"

    # ---- Properties ----

    def test_status_properties(self, transaction, confirmed_transaction, settled_transaction):
        assert transaction.is_draft is True
        assert transaction.is_confirmed is False
        assert transaction.is_settled is False
        assert transaction.is_cancelled is False

        assert confirmed_transaction.is_confirmed is True
        assert confirmed_transaction.is_draft is False

        assert settled_transaction.is_settled is True
        assert settled_transaction.is_confirmed is False

        # Cancelled
        cancelled = transaction.cancel("tester", "test")
        assert cancelled.is_cancelled is True

    def test_can_edit_settle(self, transaction, confirmed_transaction, settled_transaction):
        assert transaction.can_edit is True
        assert transaction.can_settle is False

        assert confirmed_transaction.can_edit is False
        assert confirmed_transaction.can_settle is True

        assert settled_transaction.can_edit is False
        assert settled_transaction.can_settle is False

    def test_exchange_rate_value(self, transaction):
        # amount_to / amount_from = 15000
        assert transaction.exchange_rate_value == Decimal("15000.00")

    # ---- Business methods ----

    def test_create_factory(self, legal_entity_id, exchange_rate):
        tx = ForexTransaction.create(
            legal_entity_id=legal_entity_id,
            transaction_number="FX-2026-002",
            currency_from="USD",
            currency_to="EUR",
            amount_from=Decimal("1000"),
            rate=exchange_rate,  # but rate is USD/IDR, so currency mismatch; we'll adjust
            transaction_date=datetime.now(UTC),
            settlement_date=datetime.now(UTC) + timedelta(days=2),
            transaction_type=ForexTransactionType.SPOT,
            created_by="tester",
        )
        # The factory uses rate.rate directly, so amount_to = amount_from * rate.rate
        assert tx.legal_entity_id == legal_entity_id
        assert tx.amount_from == Decimal("1000")
        assert tx.amount_to == Decimal("1000") * exchange_rate.rate
        assert tx.status == ForexTransactionStatus.DRAFT
        assert tx.transaction_type == ForexTransactionType.SPOT

    def test_confirm(self, transaction):
        confirmed = transaction.confirm("confirm_user")
        assert confirmed.status == ForexTransactionStatus.CONFIRMED
        assert confirmed.confirmed_by == "confirm_user"
        assert confirmed.confirmed_at is not None
        assert confirmed.version == transaction.version + 1
        assert confirmed.audit_trail()[-1]["action"] == "CONFIRM"

    def test_confirm_raises_if_not_draft(self, confirmed_transaction):
        with pytest.raises(ForexTransactionError, match="Cannot confirm transaction in status confirmed"):
            confirmed_transaction.confirm("another_user")

    def test_settle(self, confirmed_transaction):
        settled = confirmed_transaction.settle("settle_user")
        assert settled.status == ForexTransactionStatus.SETTLED
        assert settled.settled_by == "settle_user"
        assert settled.settled_at is not None
        assert settled.version == confirmed_transaction.version + 1
        assert settled.audit_trail()[-1]["action"] == "SETTLE"

    def test_settle_raises_if_not_confirmed(self, transaction):
        with pytest.raises(ForexTransactionError, match="Cannot settle transaction in status draft"):
            transaction.settle("settle_user")

    def test_cancel(self, transaction):
        cancelled = transaction.cancel("tester", "Test cancel")
        assert cancelled.status == ForexTransactionStatus.CANCELLED
        assert cancelled.cancelled_by == "tester"
        assert cancelled.cancelled_at is not None
        assert cancelled.cancel_reason == "Test cancel"
        assert cancelled.version == transaction.version + 1
        assert cancelled.audit_trail()[-1]["action"] == "CANCEL"

    def test_cancel_raises_if_settled(self, settled_transaction):
        with pytest.raises(ForexTransactionError, match="Cannot cancel settled transaction"):
            settled_transaction.cancel("tester", "too late")

    # ---- _copy helper (indirectly tested) ----

    def test_copy(self, transaction):
        # We test via methods that use _copy (e.g., update, confirm, etc.)
        # Already covered.
        pass


# -----------------------------------------------------------------------------
# Tests for ForexTransactionRepository (in-memory)
# -----------------------------------------------------------------------------

class TestForexTransactionRepository:
    """Test the in-memory repository implementation."""

    @pytest.fixture(autouse=True)
    def clear_storage(self):
        ForexTransactionRepository._storage.clear()
        yield
        ForexTransactionRepository._storage.clear()

    def test_save_and_get_by_id(self, transaction, legal_entity_id):
        asyncio.run(ForexTransactionRepository.save(transaction, legal_entity_id))
        retrieved = asyncio.run(ForexTransactionRepository.get_by_id(transaction.transaction_id, legal_entity_id))
        assert retrieved is not None
        assert retrieved.transaction_id == transaction.transaction_id

    def test_get_by_number(self, transaction, legal_entity_id):
        asyncio.run(ForexTransactionRepository.save(transaction, legal_entity_id))
        retrieved = asyncio.run(ForexTransactionRepository.get_by_number("FX-2026-001", legal_entity_id))
        assert retrieved is not None
        assert retrieved.transaction_number == "FX-2026-001"
        # non-existent
        missing = asyncio.run(ForexTransactionRepository.get_by_number("NONEXISTENT", legal_entity_id))
        assert missing is None

    def test_get_by_status(self, transaction, legal_entity_id):
        asyncio.run(ForexTransactionRepository.save(transaction, legal_entity_id))
        drafts = asyncio.run(ForexTransactionRepository.get_by_status(legal_entity_id, ForexTransactionStatus.DRAFT))
        assert len(drafts) == 1
        assert drafts[0].status == ForexTransactionStatus.DRAFT
        # Add another with different status
        confirmed = transaction.confirm("user")
        asyncio.run(ForexTransactionRepository.save(confirmed, legal_entity_id))
        confirmed_list = asyncio.run(ForexTransactionRepository.get_by_status(legal_entity_id, ForexTransactionStatus.CONFIRMED))
        assert len(confirmed_list) == 1
        # Filter by status that doesn't exist
        settled_list = asyncio.run(ForexTransactionRepository.get_by_status(legal_entity_id, ForexTransactionStatus.SETTLED))
        assert len(settled_list) == 0

    def test_get_by_currency_pair(self, transaction, legal_entity_id):
        asyncio.run(ForexTransactionRepository.save(transaction, legal_entity_id))
        results = asyncio.run(ForexTransactionRepository.get_by_currency_pair(legal_entity_id, "USD", "IDR"))
        assert len(results) == 1
        # Different pair
        results2 = asyncio.run(ForexTransactionRepository.get_by_currency_pair(legal_entity_id, "EUR", "IDR"))
        assert len(results2) == 0

    def test_get_all(self, transaction, legal_entity_id):
        asyncio.run(ForexTransactionRepository.save(transaction, legal_entity_id))
        all_txs = asyncio.run(ForexTransactionRepository.get_all(legal_entity_id))
        assert len(all_txs) == 1

    def test_delete(self, transaction, legal_entity_id):
        asyncio.run(ForexTransactionRepository.save(transaction, legal_entity_id))
        asyncio.run(ForexTransactionRepository.delete(transaction.transaction_id, legal_entity_id))
        retrieved = asyncio.run(ForexTransactionRepository.get_by_id(transaction.transaction_id, legal_entity_id))
        assert retrieved is None

    def test_clear(self, transaction, legal_entity_id):
        asyncio.run(ForexTransactionRepository.save(transaction, legal_entity_id))
        asyncio.run(ForexTransactionRepository.clear(legal_entity_id))
        all_txs = asyncio.run(ForexTransactionRepository.get_all(legal_entity_id))
        assert len(all_txs) == 0

    def test_multiple_legal_entities(self, transaction, legal_entity_id):
        other_legal = uuid4()
        # Save to first
        asyncio.run(ForexTransactionRepository.save(transaction, legal_entity_id))
        # Save a different transaction to other
        other_tx = transaction.update("tester", transaction_number="FX-OTHER")
        asyncio.run(ForexTransactionRepository.save(other_tx, other_legal))

        # Retrieve by legal entity
        all_first = asyncio.run(ForexTransactionRepository.get_all(legal_entity_id))
        assert len(all_first) == 1
        all_second = asyncio.run(ForexTransactionRepository.get_all(other_legal))
        assert len(all_second) == 1

        # Clear only one
        asyncio.run(ForexTransactionRepository.clear(legal_entity_id))
        assert len(asyncio.run(ForexTransactionRepository.get_all(legal_entity_id))) == 0
        assert len(asyncio.run(ForexTransactionRepository.get_all(other_legal))) == 1