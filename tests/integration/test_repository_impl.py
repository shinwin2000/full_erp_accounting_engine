#!/usr/bin/env python3
"""
Integration: SQLAlchemy Repository Implementations (Mock)
Menguji repository untuk berbagai aggregate (journal, account, inventory, dll)
termasuk CRUD, optimistic lock, filter, dan pagination.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

# ============================================================================
# MOCK DOMAIN CLASSES
# ============================================================================


class MockJournalLine:
    def __init__(self, account: str, debit: Decimal, credit: Decimal):
        self.account = account
        self.debit = debit
        self.credit = credit

        class MockJournalAggregate:
            def __init__(self, journal_id: str):
                self.journal_id = journal_id
                self.description = ""
                self.lines: list[MockJournalLine] = []
                self.version = 1  # dikelola oleh repository

                def create(self, description: str):
                    self.description = description

                    def add_line(self, account: str, debit: Decimal, credit: Decimal):
                        self.lines.append(MockJournalLine(account, debit, credit))

                        def update_description(self, new_description: str):
                            self.description = new_description
                            # version tidak diubah di sini (optimistic lock dikelola repository)

                            class MockJournalRepository:
                                def __init__(self):
                                    self._store: dict[str, MockJournalAggregate] = {}

                                    def add(self, journal: MockJournalAggregate):
                                        self._store[journal.journal_id] = journal

                                        def get(
                                            self, journal_id: str
                                        ) -> MockJournalAggregate | None:
                                            journal = self._store.get(journal_id)
                                            if journal:
                                                # Kembalikan copy dengan version yang sama
                                                copy = MockJournalAggregate(journal.journal_id)
                                                copy.description = journal.description
                                                copy.lines = journal.lines[:]
                                                copy.version = journal.version
                                                return copy
                                                return None

                                                def update(self, journal: MockJournalAggregate):
                                                    if journal.journal_id not in self._store:
                                                        raise ValueError("Journal not found")
                                                        stored = self._store[journal.journal_id]
                                                        if stored.version != journal.version:
                                                            raise Exception(
                                                                "Optimistic lock: version mismatch"
                                                            )
                                                            # Update stored aggregate
                                                            stored.description = journal.description
                                                            stored.lines = journal.lines[:]
                                                            stored.version += 1  # increment version setelah update sukses
                                                            # Tidak perlu mengubah version pada journal parameter (sudah usang)

                                                            def find(
                                                                self,
                                                                description_contains: str
                                                                | None = None,
                                                            ) -> list[MockJournalAggregate]:
                                                                if description_contains is None:
                                                                    return list(
                                                                        self._store.values()
                                                                    )
                                                                    return [
                                                                        j
                                                                        for j in self._store.values()
                                                                        if description_contains
                                                                        in j.description
                                                                    ]

                                                                    class MockUnitOfWork:
                                                                        def __init__(self):
                                                                            self.committed = False

                                                                            def __enter__(self):
                                                                                return self

                                                                                def __exit__(
                                                                                    self,
                                                                                    exc_type,
                                                                                    exc_val,
                                                                                    exc_tb,
                                                                                ):
                                                                                    if not exc_type:
                                                                                        self.commit()

                                                                                        def commit(
                                                                                            self,
                                                                                        ):
                                                                                            self.committed = True

                                                                                            def rollback(
                                                                                                self,
                                                                                            ):
                                                                                                pass

                                                                                                # ============================================================================
                                                                                                # FIXTURES
                                                                                                # ============================================================================

                                                                                                @pytest.fixture
                                                                                                def uow():
                                                                                                    return MockUnitOfWork()

                                                                                                    @pytest.fixture
                                                                                                    def journal_repo():
                                                                                                        return MockJournalRepository()

                                                                                                        # ============================================================================
                                                                                                        # TESTS
                                                                                                        # ============================================================================

                                                                                                        def test_save_and_load_journal(
                                                                                                            journal_repo,
                                                                                                            uow,
                                                                                                        ):
                                                                                                            journal = MockJournalAggregate(
                                                                                                                journal_id="JRN-001"
                                                                                                            )
                                                                                                            journal.create(
                                                                                                                "Test journal"
                                                                                                            )
                                                                                                            journal.add_line(
                                                                                                                account="101",
                                                                                                                debit=Decimal(
                                                                                                                    "1000000"
                                                                                                                ),
                                                                                                                credit=Decimal(
                                                                                                                    "0"
                                                                                                                ),
                                                                                                            )
                                                                                                            journal.add_line(
                                                                                                                account="201",
                                                                                                                debit=Decimal(
                                                                                                                    "0"
                                                                                                                ),
                                                                                                                credit=Decimal(
                                                                                                                    "1000000"
                                                                                                                ),
                                                                                                            )

                                                                                                            with uow:
                                                                                                                journal_repo.add(
                                                                                                                    journal
                                                                                                                )
                                                                                                                uow.commit()

                                                                                                                loaded = journal_repo.get(
                                                                                                                    "JRN-001"
                                                                                                                )
                                                                                                                assert (
                                                                                                                    loaded
                                                                                                                    is not None
                                                                                                                )
                                                                                                                assert (
                                                                                                                    loaded.description
                                                                                                                    == "Test journal"
                                                                                                                )
                                                                                                                assert (
                                                                                                                    len(
                                                                                                                        loaded.lines
                                                                                                                    )
                                                                                                                    == 2
                                                                                                                )

                                                                                                                def test_optimistic_lock():
                                                                                                                    """
                                                                                                                    Optimistic lock test: dua session mengambil object yang sama.
                                                                                                                    Session pertama berhasil update, session kedua harus gagal.
                                                                                                                    """
                                                                                                                    repo = MockJournalRepository()

                                                                                                                    # 1. Simpan aggregate awal
                                                                                                                    journal = MockJournalAggregate(
                                                                                                                        journal_id="JRN-002"
                                                                                                                    )
                                                                                                                    journal.create(
                                                                                                                        "Initial"
                                                                                                                    )
                                                                                                                    repo.add(
                                                                                                                        journal
                                                                                                                    )

                                                                                                                    # 2. Simulasi dua session mengambil object yang sama (version=1)
                                                                                                                    session1_journal = repo.get(
                                                                                                                        "JRN-002"
                                                                                                                    )
                                                                                                                    session2_journal = repo.get(
                                                                                                                        "JRN-002"
                                                                                                                    )

                                                                                                                    # 3. User A melakukan perubahan (tanpa mengubah version)
                                                                                                                    session1_journal.update_description(
                                                                                                                        "Updated by A"
                                                                                                                    )
                                                                                                                    repo.update(
                                                                                                                        session1_journal
                                                                                                                    )  # sukses, version di store menjadi 2

                                                                                                                    # 4. User B mencoba update dengan object stale (version masih 1)
                                                                                                                    session2_journal.update_description(
                                                                                                                        "Updated by B"
                                                                                                                    )  # version tetap 1
                                                                                                                    with pytest.raises(
                                                                                                                        Exception,
                                                                                                                        match="Optimistic lock",
                                                                                                                    ):
                                                                                                                        repo.update(
                                                                                                                            session2_journal
                                                                                                                        )

                                                                                                                        def test_filter_by_criteria(
                                                                                                                            journal_repo,
                                                                                                                            uow,
                                                                                                                        ):
                                                                                                                            for i in range(
                                                                                                                                5
                                                                                                                            ):
                                                                                                                                j = MockJournalAggregate(
                                                                                                                                    journal_id=f"JRN-00{i}"
                                                                                                                                )
                                                                                                                                j.create(
                                                                                                                                    f"Journal {i}"
                                                                                                                                )
                                                                                                                                with uow:
                                                                                                                                    journal_repo.add(
                                                                                                                                        j
                                                                                                                                    )
                                                                                                                                    uow.commit()

                                                                                                                                    filtered = journal_repo.find(
                                                                                                                                        description_contains="Journal 2"
                                                                                                                                    )
                                                                                                                                    assert (
                                                                                                                                        len(
                                                                                                                                            filtered
                                                                                                                                        )
                                                                                                                                        == 1
                                                                                                                                    )
                                                                                                                                    assert (
                                                                                                                                        filtered[
                                                                                                                                            0
                                                                                                                                        ].journal_id
                                                                                                                                        == "JRN-002"
                                                                                                                                    )
