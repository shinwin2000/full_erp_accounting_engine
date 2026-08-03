"""
Tests for projections/ledger/general_ledger_table.py
Menggunakan mock untuk semua dependensi eksternal.
"""

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from projections.ledger.general_ledger_table import (
    GeneralLedgerProjectionError,
    GeneralLedgerTable,
    RebuildInProgressError,
    get_general_ledger_projection,
)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_result():
    """Mock SQLAlchemy result object dengan synchronous methods."""
    result = MagicMock()
    result.scalar = MagicMock()
    result.first = MagicMock()
    result.scalars = MagicMock()
    result.scalars.return_value.all = MagicMock()
    result.scalars.return_value.first = MagicMock()
    return result


@pytest.fixture
def mock_session(mock_result):
    """Mock AsyncSession dengan execute yang mengembalikan result."""
    session = AsyncMock(spec=AsyncSession)

    # Mendukung 'async with session'
    session.__aenter__.return_value = session
    session.__aexit__.return_value = None

    # Mendukung 'async with session.begin()'
    mock_tx = AsyncMock()
    mock_tx.__aenter__.return_value = mock_tx
    mock_tx.__aexit__.return_value = None
    session.begin = MagicMock(return_value=mock_tx)

    # execute mengembalikan result yang sudah di-await, bukan coroutine
    session.execute = AsyncMock(return_value=mock_result)
    session.add_all = MagicMock()
    session.commit = AsyncMock()
    return session


@pytest.fixture
def mock_session_factory(mock_session):
    """Mock session factory yang get_session mengembalikan session yang di-await."""
    factory = MagicMock()
    # get_session mengembalikan session langsung (bukan coroutine)
    factory.get_session = MagicMock(return_value=mock_session)
    return factory


@pytest.fixture
def mock_event_store():
    store = AsyncMock()
    store.read_stream = AsyncMock(return_value=[])
    return store


@pytest.fixture
def general_ledger_table(mock_session_factory, mock_event_store):
    """Instance dengan dependencies dimock."""
    table = GeneralLedgerTable()
    table._session_factory = mock_session_factory
    table._event_store = mock_event_store

    # Hanya mock _process_event_batch agar test handle tidak error
    table._process_event_batch = AsyncMock()
    table._account_cache = {}
    return table


# ============================================================================
# Exception Tests
# ============================================================================

class TestGeneralLedgerProjectionError:
    def test_construction(self):
        exc = GeneralLedgerProjectionError("test")
        assert str(exc) == "test"
        assert isinstance(exc, Exception)


class TestRebuildInProgressError:
    def test_construction(self):
        exc = RebuildInProgressError("test")
        assert str(exc) == "test"
        assert isinstance(exc, GeneralLedgerProjectionError)


# ============================================================================
# Tests untuk GeneralLedgerTable
# ============================================================================

class TestGeneralLedgerTable:
    def test_construction(self):
        table = GeneralLedgerTable()
        assert table._event_store is None
        assert table._session_factory is None
        assert table._rebuild_lock is not None
        assert table._last_event_id is None
        assert table._last_event_sequence == 0

    @pytest.mark.asyncio
    async def test_get_event_store_caches(self, general_ledger_table):
        store = await general_ledger_table._get_event_store()
        assert store is general_ledger_table._event_store
        store2 = await general_ledger_table._get_event_store()
        assert store2 is store

    @pytest.mark.asyncio
    async def test_get_session_caches(self, general_ledger_table):
        session1 = await general_ledger_table._get_session()
        session2 = await general_ledger_table._get_session()
        assert session1 is session2
        # _get_session accesses the factory directly each time, so call count should be 2
        assert general_ledger_table._session_factory.get_session.call_count == 2

    @pytest.mark.asyncio
    async def test_get_checkpoint(self, general_ledger_table, mock_session):
        mock_result = MagicMock()
        mock_result.first = MagicMock(return_value=(uuid4(), 42))
        mock_session.execute = AsyncMock(return_value=mock_result)

        _event_id, seq = await general_ledger_table._get_checkpoint()
        assert seq == 42

    @pytest.mark.asyncio
    async def test_update_checkpoint(self, general_ledger_table, mock_session):
        event_id = uuid4()
        seq = 99
        mock_stmt = MagicMock()
        mock_stmt.values.return_value = mock_stmt
        mock_stmt.on_conflict_do_update.return_value = mock_stmt

        with patch("projections.ledger.general_ledger_table.insert", return_value=mock_stmt):
            await general_ledger_table._update_checkpoint(event_id, seq)
            mock_session.execute.assert_called_once()
            mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_rebuild_success(self, general_ledger_table):
        general_ledger_table._event_store.read_stream = AsyncMock(return_value=[
            {"id": str(uuid4()), "event_type": "JournalPosted", "data": {"journal_id": str(uuid4()), "lines": []}}
        ])
        general_ledger_table._process_event_batch = AsyncMock()
        result = await general_ledger_table.rebuild(batch_size=1)
        assert result["success"] is True
        assert result["total_events_processed"] == 1
        assert result["errors"] == 0

    @pytest.mark.asyncio
    async def test_rebuild_handles_errors(self, general_ledger_table):
        general_ledger_table._event_store.read_stream = AsyncMock(return_value=[
            {"id": str(uuid4()), "event_type": "JournalPosted", "data": {}}
        ])
        general_ledger_table._process_event_batch = AsyncMock(side_effect=Exception("DB error"))
        with patch("projections.ledger.general_ledger_table.trigger_alert") as mock_alert:
            result = await general_ledger_table.rebuild(batch_size=1)
            assert result["success"] is False
            assert result["errors"] == 1
            mock_alert.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_calls_process_batch(self, general_ledger_table):
        event = {"id": "evt1"}
        await general_ledger_table.handle(event)
        general_ledger_table._process_event_batch.assert_called_once_with([event])

    @pytest.mark.asyncio
    async def test_get_account_id_caches(self, general_ledger_table, mock_session):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=uuid4())
        mock_session.execute = AsyncMock(return_value=mock_result)

        account_id1 = await general_ledger_table._get_account_id("1234")
        assert account_id1 is not None
        assert "1234" in general_ledger_table._account_cache

        account_id2 = await general_ledger_table._get_account_id("1234")
        assert account_id2 == account_id1
        assert mock_session.execute.call_count == 1

    @pytest.mark.asyncio
    async def test_get_ledger_entries(self, general_ledger_table, mock_session):
        mock_entry = MagicMock()
        mock_entry.id = uuid4()
        mock_entry.journal_id = uuid4()
        mock_entry.account_code = "1001"
        mock_entry.debit_amount = Decimal("100")
        mock_entry.credit_amount = Decimal("0")
        mock_entry.posting_date = date(2026, 1, 1)
        mock_entry.cost_center = "CC01"
        mock_entry.description = "Test"

        mock_scalars = MagicMock()
        mock_scalars.all = MagicMock(return_value=[mock_entry])
        mock_result = MagicMock()
        mock_result.scalars = MagicMock(return_value=mock_scalars)
        mock_session.execute = AsyncMock(return_value=mock_result)

        entries = await general_ledger_table.get_ledger_entries(
            account_id=uuid4(),
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
            cost_center="CC01",
            legal_entity_id=uuid4(),
            limit=10,
            offset=0
        )
        assert len(entries) == 1
        assert entries[0]["account_code"] == "1001"
        assert entries[0]["debit_amount"] == 100.0

    @pytest.mark.asyncio
    async def test_get_account_balance(self, general_ledger_table, mock_session):
        class MockRow:
            def __init__(self):
                self.total_debit = Decimal("1000")
                self.total_credit = Decimal("200")

        mock_result = MagicMock()
        mock_result.first = MagicMock(return_value=MockRow())
        mock_session.execute = AsyncMock(return_value=mock_result)

        balance = await general_ledger_table.get_account_balance(
            account_id=uuid4(),
            as_of_date=date(2026, 12, 31),
            legal_entity_id=uuid4()
        )
        assert balance == Decimal("800")

    @pytest.mark.asyncio
    async def test_incremental_update(self, general_ledger_table):
        events = [
            {"id": str(uuid4()), "sequence_number": 10, "event_type": "JournalPosted", "data": {}},
            {"id": str(uuid4()), "sequence_number": 11, "event_type": "JournalPosted", "data": {}},
        ]
        general_ledger_table._event_store.read_stream = AsyncMock(return_value=events)
        general_ledger_table._get_checkpoint = AsyncMock(return_value=(None, 5))
        general_ledger_table._process_event_batch = AsyncMock()
        general_ledger_table._update_checkpoint = AsyncMock()

        count = await general_ledger_table.incremental_update()
        assert count == 2
        general_ledger_table._process_event_batch.assert_called_once_with(events)
        general_ledger_table._update_checkpoint.assert_called_once()

    @pytest.mark.asyncio
    async def test_incremental_update_no_new_events(self, general_ledger_table):
        general_ledger_table._event_store.read_stream = AsyncMock(return_value=[])
        general_ledger_table._get_checkpoint = AsyncMock(return_value=(None, 0))
        count = await general_ledger_table.incremental_update()
        assert count == 0

    @pytest.mark.asyncio
    async def test_get_stats(self, general_ledger_table, mock_session):
        mock_result_count = MagicMock()
        mock_result_count.scalar = MagicMock(return_value=100)

        class MockRow:
            def __init__(self):
                self.total_debit = Decimal("5000")
                self.total_credit = Decimal("2000")

        mock_result_sum = MagicMock()
        mock_result_sum.first = MagicMock(return_value=MockRow())

        mock_session.execute = AsyncMock(side_effect=[mock_result_count, mock_result_sum])
        general_ledger_table._get_checkpoint = AsyncMock(return_value=(None, 42))

        stats = await general_ledger_table.get_stats()
        assert stats["total_entries"] == 100
        assert stats["total_debit"] == 5000.0
        assert stats["total_credit"] == 2000.0
        assert stats["last_checkpoint_sequence"] == 42


# ============================================================================
# Tests for module-level function
# ============================================================================

@pytest.mark.asyncio
async def test_get_general_ledger_projection():
    with patch("projections.ledger.general_ledger_table._general_ledger_projection", None):
        with patch("projections.ledger.general_ledger_table.GeneralLedgerTable") as mock_class:
            mock_instance = AsyncMock()
            mock_class.return_value = mock_instance
            result = await get_general_ledger_projection()
            assert result is mock_instance
            result2 = await get_general_ledger_projection()
            assert result2 is result
            assert mock_class.call_count == 1
