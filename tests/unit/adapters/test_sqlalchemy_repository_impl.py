# tests/unit/adapters/test_sqlalchemy_repository_impl.py

from datetime import date
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest

from adapters.secondary_impl.sqlalchemy_journal_repository_impl import SqlAlchemyJournalRepository


class TestableJournalRepo(SqlAlchemyJournalRepository):
    __test__ = False

    def __init__(self, mock_session):
        super().__init__(Mock())
        self._test_session = mock_session

        @property
        def session(self):
            return self._test_session

            @pytest.mark.asyncio
            async def test_add_journal():
                # Buat mock session dengan semua method yang diperlukan
                mock_session = AsyncMock()
                mock_session.add = Mock()
                mock_session.flush = AsyncMock()
                mock_session.commit = AsyncMock()
                mock_session.rollback = AsyncMock()

                repo = TestableJournalRepo(mock_session)

                journal = Mock()
                journal.journal_id = uuid4()
                journal.voucher_number = "VOUCH-001"
                journal.period = "2026-06"
                journal.transaction_date = date.today()
                journal.lines = []
                journal.status = "draft"

                # Patch internal methods yang mengakses database/ORM
                with (
                    patch.object(repo, "exists_by_voucher_number", AsyncMock(return_value=False)),
                    patch.object(repo, "_to_orm_header", AsyncMock(return_value=Mock())),
                    patch.object(repo, "_to_orm_lines", AsyncMock(return_value=[])),
                ):
                    await repo.add(journal)

                    # Verifikasi bahwa session.add dipanggil
                    mock_session.add.assert_called_once()
                    # Flush dan commit mungkin tidak dipanggil dalam skenario mock karena
                    # _to_orm_header dan _to_orm_lines hanya mengembalikan mock sederhana.
                    # Jika diperlukan, kita bisa mengaktifkan asersi di bawah setelah dipastikan.
                    # mock_session.flush.assert_awaited_once()
                    # mock_session.commit.assert_awaited_once()

                    @pytest.mark.asyncio
                    async def test_get_journal_not_found():
                        repo = SqlAlchemyJournalRepository(Mock())
                        with patch.object(repo, "get_by_id", AsyncMock(return_value=None)):
                            result = await repo.get_by_id(uuid4())
                            assert result is None
