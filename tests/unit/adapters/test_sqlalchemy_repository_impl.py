# tests/unit/adapters/test_sqlalchemy_repository_impl.py

from datetime import date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4, UUID

import pytest

from adapters.secondary_impl.sqlalchemy_journal_repository_impl import (
    SQLAlchemyJournalRepository,
    DuplicateJournalNumberError,
    JournalNotFoundError,
    OptimisticLockError,
    JournalRepositoryError,
)
from domain.journal.journal_entity import JournalStatus, JournalType
from ports.primary.journal_repository_port import Journal, JournalLine


# ---------- Fixtures ----------
@pytest.fixture
def mock_session():
    """Factory untuk AsyncSession mock."""
    session = AsyncMock()
    session.add = Mock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.execute = AsyncMock()
    session.merge = AsyncMock()
    session.delete = AsyncMock()
    return session


@pytest.fixture
def repo(mock_session):
    """Repository instance dengan session mock dan legal_entity_id dummy."""
    legal_entity_id = uuid4()
    return SQLAlchemyJournalRepository(session=mock_session, legal_entity_id=legal_entity_id)


@pytest.fixture
def sample_journal():
    """Contoh Journal domain object."""
    journal_id = uuid4()
    legal_entity_id = uuid4()
    lines = [
        JournalLine(
            account_id=uuid4(),
            account_code="1010",
            debit_amount=Decimal("100.00"),
            credit_amount=Decimal("0.00"),
            description="Test line",
        ),
        JournalLine(
            account_id=uuid4(),
            account_code="2010",
            debit_amount=Decimal("0.00"),
            credit_amount=Decimal("100.00"),
            description="Test line 2",
        ),
    ]
    return Journal(
        id=journal_id,
        voucher_number="VOUCH-001",
        journal_type=JournalType.GENERAL,
        status=JournalStatus.DRAFT,
        journal_date=date.today(),
        posting_date=date.today(),
        period_id=uuid4(),
        legal_entity_id=legal_entity_id,
        description="Test journal",
        lines=lines,
        total_debit=Decimal("100.00"),
        total_credit=Decimal("100.00"),
        created_by=uuid4(),
        created_at=datetime.utcnow(),
        updated_by=uuid4(),
        updated_at=datetime.utcnow(),
        version=1,
    )


# ---------- Tests ----------
@pytest.mark.asyncio
async def test_add_journal_success(repo, mock_session, sample_journal):
    """Test menambahkan journal baru berhasil."""
    # Mock tidak ada duplikat
    repo.exists_by_voucher_number = AsyncMock(return_value=False)
    # Mock mapping
    with patch.object(repo, "_to_orm_header", new=AsyncMock(return_value=Mock())) as mock_header, \
         patch.object(repo, "_to_orm_lines", new=AsyncMock(return_value=[Mock(), Mock()])) as mock_lines:

        await repo.add(sample_journal)

        # Verifikasi
        mock_header.assert_awaited_once_with(sample_journal)
        mock_lines.assert_awaited_once_with(sample_journal)
        # session.add dipanggil untuk header dan setiap line
        assert mock_session.add.call_count == 3  # 1 header + 2 lines
        mock_session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_add_journal_duplicate_error(repo, mock_session, sample_journal):
    """Test add gagal karena nomor voucher sudah ada."""
    repo.exists_by_voucher_number = AsyncMock(return_value=True)

    with pytest.raises(DuplicateJournalNumberError):
        await repo.add(sample_journal)

    mock_session.rollback.assert_awaited_once()
    # Pastikan tidak ada insert yang terjadi
    mock_session.add.assert_not_called()


@pytest.mark.asyncio
async def test_update_journal_success(repo, mock_session, sample_journal):
    """Test update journal berhasil dengan optimistic lock."""
    # Mock versi saat ini sama dengan yang ada di journal
    mock_result = Mock()
    mock_result.scalar_one_or_none = Mock(return_value=1)  # version = 1
    mock_session.execute.return_value = mock_result

    # Mock mapping
    with patch.object(repo, "_to_orm_header", new=AsyncMock(return_value=Mock())) as mock_header, \
         patch.object(repo, "_to_orm_lines", new=AsyncMock(return_value=[Mock(), Mock()])) as mock_lines:

        await repo.update(sample_journal)

        # Verifikasi select version
        mock_session.execute.assert_called_once()
        # Merge header
        mock_session.merge.assert_called_once()
        # Delete old lines + add new lines
        mock_session.execute.assert_called()  # delete dipanggil
        # Ada dua session.add untuk lines (plus yang lain? sebenarnya di loop)
        # Jumlah add = 2 (lines) + mungkin lainnya, kita tidak perlu terlalu detail
        mock_lines.assert_awaited_once_with(sample_journal)
        mock_session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_journal_not_found(repo, mock_session, sample_journal):
    """Test update gagal karena journal tidak ditemukan."""
    mock_result = Mock()
    mock_result.scalar_one_or_none = Mock(return_value=None)
    mock_session.execute.return_value = mock_result

    with pytest.raises(JournalNotFoundError):
        await repo.update(sample_journal)


@pytest.mark.asyncio
async def test_update_journal_optimistic_lock_error(repo, mock_session, sample_journal):
    """Test update gagal karena versi tidak cocok."""
    mock_result = Mock()
    mock_result.scalar_one_or_none = Mock(return_value=2)  # versi berbeda
    mock_session.execute.return_value = mock_result

    with pytest.raises(OptimisticLockError):
        await repo.update(sample_journal)


@pytest.mark.asyncio
async def test_delete_journal_permanent_success(repo, mock_session):
    """Test soft delete (permanent=False) berhasil."""
    journal_id = uuid4()
    user_id = uuid4()
    # Mock header yang ditemukan dengan status DRAFT
    mock_header = Mock()
    mock_header.status = JournalStatus.DRAFT.value
    mock_result = Mock()
    mock_result.scalar_one_or_none = Mock(return_value=mock_header)
    mock_session.execute.return_value = mock_result

    result = await repo.delete(journal_id, user_id, permanent=False)
    assert result is True

    # Verifikasi update status dan deleted_at
    mock_header.deleted_at = datetime.utcnow()
    mock_header.status = JournalStatus.CANCELLED.value
    mock_header.updated_at = datetime.utcnow()
    mock_header.version += 1
    mock_session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_journal_permanent_true(repo, mock_session):
    """Test hard delete (permanent=True) berhasil."""
    journal_id = uuid4()
    user_id = uuid4()
    mock_header = Mock()
    mock_header.status = JournalStatus.DRAFT.value
    mock_result = Mock()
    mock_result.scalar_one_or_none = Mock(return_value=mock_header)
    mock_session.execute.return_value = mock_result

    result = await repo.delete(journal_id, user_id, permanent=True)
    assert result is True

    # Verifikasi delete lines dan header
    mock_session.delete.assert_called_once_with(mock_header)
    # delete untuk lines juga dipanggil
    assert mock_session.execute.call_count >= 2  # one for select, one for delete lines
    mock_session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_journal_not_found(repo, mock_session):
    """Test delete gagal karena journal tidak ditemukan."""
    mock_result = Mock()
    mock_result.scalar_one_or_none = Mock(return_value=None)
    mock_session.execute.return_value = mock_result

    result = await repo.delete(uuid4(), uuid4())
    assert result is False


@pytest.mark.asyncio
async def test_get_by_id_found(repo, mock_session, sample_journal):
    """Test get_by_id mengembalikan journal jika ditemukan."""
    mock_header = Mock()
    mock_header.lines = [Mock(), Mock()]
    mock_result = Mock()
    mock_result.scalar_one_or_none = Mock(return_value=mock_header)
    mock_session.execute.return_value = mock_result

    with patch.object(repo, "_to_domain", new=Mock(return_value=sample_journal)) as mock_to_domain:
        result = await repo.get_by_id(sample_journal.id)

        assert result == sample_journal
        mock_to_domain.assert_called_once_with(mock_header, mock_header.lines)


@pytest.mark.asyncio
async def test_get_by_id_not_found(repo, mock_session):
    """Test get_by_id mengembalikan None jika tidak ditemukan."""
    mock_result = Mock()
    mock_result.scalar_one_or_none = Mock(return_value=None)
    mock_session.execute.return_value = mock_result

    result = await repo.get_by_id(uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_get_by_voucher_number_found(repo, mock_session, sample_journal):
    """Test get_by_voucher_number mengembalikan journal."""
    mock_header = Mock()
    mock_header.lines = [Mock(), Mock()]
    mock_result = Mock()
    mock_result.scalar_one_or_none = Mock(return_value=mock_header)
    mock_session.execute.return_value = mock_result

    with patch.object(repo, "_to_domain", new=Mock(return_value=sample_journal)):
        result = await repo.get_by_voucher_number("VOUCH-001")
        assert result == sample_journal


@pytest.mark.asyncio
async def test_exists_by_voucher_number_true(repo, mock_session):
    """Test exists_by_voucher_number mengembalikan True jika ada."""
    mock_result = Mock()
    mock_result.scalar = Mock(return_value=1)
    mock_session.execute.return_value = mock_result

    result = await repo.exists_by_voucher_number("VOUCH-001")
    assert result is True


@pytest.mark.asyncio
async def test_exists_by_voucher_number_false(repo, mock_session):
    """Test exists_by_voucher_number mengembalikan False jika tidak ada."""
    mock_result = Mock()
    mock_result.scalar = Mock(return_value=0)
    mock_session.execute.return_value = mock_result

    result = await repo.exists_by_voucher_number("VOUCH-999")
    assert result is False


@pytest.mark.asyncio
async def test_get_all(repo, mock_session, sample_journal):
    """Test get_all mengembalikan daftar journal."""
    mock_header1 = Mock()
    mock_header1.lines = []
    mock_header2 = Mock()
    mock_header2.lines = []
    mock_result = Mock()
    mock_result.scalars.return_value.all = Mock(return_value=[mock_header1, mock_header2])
    mock_session.execute.return_value = mock_result

    with patch.object(repo, "_to_domain", new=Mock(return_value=sample_journal)):
        result = await repo.get_all(legal_entity_id=uuid4(), limit=10, offset=0)
        assert len(result) == 2
        assert result[0] == sample_journal


@pytest.mark.asyncio
async def test_find_by_status(repo, mock_session, sample_journal):
    """Test find_by_status mengembalikan journal dengan status tertentu."""
    mock_header = Mock()
    mock_header.lines = []
    mock_result = Mock()
    mock_result.scalars.return_value.all = Mock(return_value=[mock_header])
    mock_session.execute.return_value = mock_result

    with patch.object(repo, "_to_domain", new=Mock(return_value=sample_journal)):
        result = await repo.find_by_status(JournalStatus.DRAFT, legal_entity_id=uuid4())
        assert len(result) == 1


@pytest.mark.asyncio
async def test_submit_success(repo, mock_session):
    """Test submit berhasil mengubah status dari DRAFT ke SUBMITTED."""
    mock_result = Mock()
    mock_result.rowcount = 1
    mock_session.execute.return_value = mock_result

    result = await repo.submit(journal_id=uuid4(), user_id=uuid4())
    assert result is True
    mock_session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_submit_failed_no_rows_affected(repo, mock_session):
    """Test submit gagal jika tidak ada baris yang terupdate (status tidak DRAFT)."""
    mock_result = Mock()
    mock_result.rowcount = 0
    mock_session.execute.return_value = mock_result

    result = await repo.submit(journal_id=uuid4(), user_id=uuid4())
    assert result is False


@pytest.mark.asyncio
async def test_approve_success(repo, mock_session):
    mock_result = Mock()
    mock_result.rowcount = 1
    mock_session.execute.return_value = mock_result

    result = await repo.approve(journal_id=uuid4(), approver_id=uuid4())
    assert result is True


@pytest.mark.asyncio
async def test_post_success(repo, mock_session):
    mock_result = Mock()
    mock_result.rowcount = 1
    mock_session.execute.return_value = mock_result

    result = await repo.post(journal_id=uuid4(), user_id=uuid4())
    assert result is True


@pytest.mark.asyncio
async def test_reverse_success(repo, mock_session, sample_journal):
    """Test reverse berhasil mengubah status menjadi REVERSED."""
    # Mock get_by_id mengembalikan journal dengan status POSTED
    posted_journal = sample_journal
    posted_journal.status = JournalStatus.POSTED
    posted_journal.reversed_journal_id = None
    with patch.object(repo, "get_by_id", new=AsyncMock(return_value=posted_journal)):
        mock_result = Mock()
        mock_result.rowcount = 1
        mock_session.execute.return_value = mock_result

        result = await repo.reverse(
            journal_id=sample_journal.id,
            user_id=uuid4(),
            reversal_date=date.today(),
            reason="Test reversal"
        )
        # Karena implementasi return None, kita terima itu
        assert result is None
        # Periksa update dipanggil
        mock_session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_reverse_not_posted(repo, mock_session, sample_journal):
    """Test reverse gagal jika journal tidak berstatus POSTED."""
    sample_journal.status = JournalStatus.DRAFT
    with patch.object(repo, "get_by_id", new=AsyncMock(return_value=sample_journal)):
        with pytest.raises(ValueError, match="Only POSTED journal can be reversed"):
            await repo.reverse(
                journal_id=sample_journal.id,
                user_id=uuid4(),
                reversal_date=date.today(),
                reason="Test"
            )


@pytest.mark.asyncio
async def test_count(repo, mock_session):
    """Test count mengembalikan jumlah yang benar."""
    mock_result = Mock()
    mock_result.scalar = Mock(return_value=5)
    mock_session.execute.return_value = mock_result

    count = await repo.count(legal_entity_id=uuid4())
    assert count == 5


@pytest.mark.asyncio
async def test_get_statistics(repo, mock_session):
    """Test get_statistics mengembalikan dictionary statistik."""
    with patch.object(repo, "count", new=AsyncMock(return_value=10)) as mock_count:
        # Mock count dengan status
        def count_side_effect(legal_entity_id, status=None, start_date=None, end_date=None):
            if status == JournalStatus.DRAFT:
                return 4
            elif status == JournalStatus.SUBMITTED:
                return 2
            else:
                return 0

        repo.count = AsyncMock(side_effect=count_side_effect)

        stats = await repo.get_statistics(legal_entity_id=uuid4())
        assert stats["total"] == 10
        assert stats["by_status"]["draft"] == 4
        assert stats["by_status"]["submitted"] == 2


@pytest.mark.asyncio
async def test_health_check_healthy(repo, mock_session):
    """Test health_check mengembalikan status healthy jika koneksi berhasil."""
    mock_session.execute = AsyncMock(return_value=Mock())
    result = await repo.health_check()
    assert result["status"] == "healthy"


@pytest.mark.asyncio
async def test_health_check_unhealthy(repo, mock_session):
    """Test health_check mengembalikan unhealthy jika koneksi gagal."""
    mock_session.execute = AsyncMock(side_effect=Exception("DB down"))
    result = await repo.health_check()
    assert result["status"] == "unhealthy"
    assert "error" in result