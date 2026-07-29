# test_unit_of_work_port.py
# Comprehensive tests for ports/primary/unit_of_work_port.py

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from ports.primary.unit_of_work_port import (
    DeadlockDetector,
    DeadlockError,
    InMemoryUnitOfWork,
    IsolationLevel,
    RepositoryProvider,
    TransactionStatus,
    UnitOfWorkPort,
    create_uow_with_provider,
    get_uow,
    get_uow_statistics,
)


# -------------------- Fixtures --------------------
@pytest.fixture
def fixed_now():
    return datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def mock_datetime(fixed_now):
    with patch("ports.primary.unit_of_work_port.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now
        mock_dt.utcnow.return_value = fixed_now
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        yield mock_dt


@pytest.fixture
def mock_repo():
    repo = MagicMock()
    repo._commit = AsyncMock()
    repo._rollback = AsyncMock()
    repo._flush = AsyncMock()
    repo._savepoint = AsyncMock(return_value={"sp": "data"})
    repo._rollback_to_savepoint = AsyncMock()
    repo._set_uow = MagicMock()
    return repo


@pytest.fixture
def uow(mock_repo):
    uow = InMemoryUnitOfWork(
        isolation_level=IsolationLevel.READ_COMMITTED,
        auto_commit=False,
        retry_on_deadlock=2,
    )
    uow.register_repository("test_repo", mock_repo)
    return uow


@pytest.fixture
def provider():
    return RepositoryProvider(
        journals=MagicMock(),
        ledger_entries=MagicMock(),
        accounts=MagicMock(),
        ar_invoices=MagicMock(),
        ap_invoices=MagicMock(),
        inventory=MagicMock(),
        fixed_assets=MagicMock(),
        bank_accounts=MagicMock(),
        cash_books=MagicMock(),
        legal_entities=MagicMock(),
        employees=MagicMock(),
        customers=MagicMock(),
        suppliers=MagicMock(),
        iam_users=MagicMock(),
        system_settings=MagicMock(),
        tax_transactions=MagicMock(),
    )


# -------------------- Tests for Enums --------------------
class TestEnums:
    def test_isolation_level(self):
        assert IsolationLevel.READ_UNCOMMITTED.value == "read_uncommitted"
        assert IsolationLevel.READ_COMMITTED.value == "read_committed"
        assert IsolationLevel.REPEATABLE_READ.value == "repeatable_read"
        assert IsolationLevel.SERIALIZABLE.value == "serializable"

    def test_transaction_status(self):
        assert TransactionStatus.ACTIVE.value == "active"
        assert TransactionStatus.COMMITTED.value == "committed"
        assert TransactionStatus.ROLLED_BACK.value == "rolled_back"
        assert TransactionStatus.FAILED.value == "failed"


# -------------------- Tests for Exceptions --------------------
class TestDeadlockError:
    def test_raise(self):
        with pytest.raises(DeadlockError):
            raise DeadlockError("deadlock")


# -------------------- Tests for UnitOfWorkPort (abstract base) --------------------
class TestUnitOfWorkPort:
    def test_abstract_methods(self):
        # We just verify that the class is abstract and cannot be instantiated directly
        with pytest.raises(TypeError):
            UnitOfWorkPort()


# -------------------- Tests for InMemoryUnitOfWork --------------------
class TestInMemoryUnitOfWork:
    def test_init(self):
        uow = InMemoryUnitOfWork(
            isolation_level=IsolationLevel.SERIALIZABLE,
            auto_commit=True,
            retry_on_deadlock=5,
        )
        assert uow._isolation_level == IsolationLevel.SERIALIZABLE
        assert uow._auto_commit is True
        assert uow._retry_on_deadlock == 5
        assert uow._status == TransactionStatus.ACTIVE
        assert uow._repositories == {}
        assert uow._savepoints == []
        assert uow._transaction_id is not None
        assert uow._start_time is None

    @pytest.mark.asyncio
    async def test_aenter_aexit_auto_commit(self, uow):
        async with uow as ctx:
            assert ctx is uow
            assert uow._status == TransactionStatus.ACTIVE
            assert uow._start_time is not None
        # Auto_commit False, so status should still be ACTIVE (no commit)
        assert uow._status == TransactionStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_aenter_aexit_auto_commit_true(self):
        uow = InMemoryUnitOfWork(auto_commit=True)
        async with uow:
            uow.register_repository("test", MagicMock())
            # repository _commit will be called, but since we mock, we need to check
            # that commit was called.
        # After exit, status should be COMMITTED (since auto_commit)
        # But commit will only be called if there is a repository with _commit method.
        # We'll test commit separately.

    @pytest.mark.asyncio
    async def test_aenter_aexit_with_exception(self, uow):
        with pytest.raises(ValueError):
            async with uow:
                raise ValueError("test error")
        assert uow._status == TransactionStatus.ROLLED_BACK

    @pytest.mark.asyncio
    async def test_commit_success(self, uow):
        await uow.__aenter__()
        # Register mock repo with _commit
        repo = AsyncMock()
        repo._commit = AsyncMock()
        uow.register_repository("repo2", repo)

        await uow.commit()
        assert uow._status == TransactionStatus.COMMITTED
        repo._commit.assert_called_once()
        assert uow._commit_time is not None

    @pytest.mark.asyncio
    async def test_commit_with_before_hook_abort(self, uow):
        await uow.__aenter__()
        hook = AsyncMock(return_value=False)
        uow.add_before_commit_hook(hook)

        with pytest.raises(RuntimeError, match="aborted transaction"):
            await uow.commit()
        assert uow._status == TransactionStatus.ROLLED_BACK
        hook.assert_called_once()

    @pytest.mark.asyncio
    async def test_commit_with_before_hook_exception(self, uow):
        await uow.__aenter__()
        hook = AsyncMock(side_effect=Exception("hook error"))
        uow.add_before_commit_hook(hook)

        with pytest.raises(RuntimeError, match="Before-commit hook failed"):
            await uow.commit()
        assert uow._status == TransactionStatus.ROLLED_BACK

    @pytest.mark.asyncio
    async def test_commit_repo_commit_failure(self, uow):
        await uow.__aenter__()
        repo = AsyncMock()
        repo._commit = AsyncMock(side_effect=Exception("db error"))
        uow.register_repository("bad_repo", repo)

        with pytest.raises(Exception, match="db error"):
            await uow.commit()
        assert uow._status == TransactionStatus.FAILED

    @pytest.mark.asyncio
    async def test_commit_invalid_status(self, uow):
        await uow.__aenter__()
        await uow.commit()
        with pytest.raises(ValueError, match="Cannot commit in status"):
            await uow.commit()

    @pytest.mark.asyncio
    async def test_rollback(self, uow):
        await uow.__aenter__()
        repo = AsyncMock()
        repo._rollback = AsyncMock()
        uow.register_repository("rollback_repo", repo)

        await uow.rollback()
        assert uow._status == TransactionStatus.ROLLED_BACK
        repo._rollback.assert_called_once()
        assert uow._rollback_time is not None

    @pytest.mark.asyncio
    async def test_rollback_after_commit_does_nothing(self, uow):
        await uow.__aenter__()
        await uow.commit()
        await uow.rollback()
        # Status should remain COMMITTED, not changed
        assert uow._status == TransactionStatus.COMMITTED

    @pytest.mark.asyncio
    async def test_after_commit_hook(self, uow):
        await uow.__aenter__()
        hook = AsyncMock()
        uow.add_after_commit_hook(hook)

        await uow.commit()
        hook.assert_called_once()

    @pytest.mark.asyncio
    async def test_after_rollback_hook(self, uow):
        await uow.__aenter__()
        hook = AsyncMock()
        uow.add_after_rollback_hook(hook)

        await uow.rollback()
        hook.assert_called_once()

    @pytest.mark.asyncio
    async def test_savepoint(self, uow):
        await uow.__aenter__()
        name = await uow.savepoint("sp1")
        assert name == "sp1"
        assert len(uow._savepoints) == 1
        assert uow._savepoints[0]["name"] == "sp1"
        # Test without name
        name2 = await uow.savepoint()
        assert name2 == "sp_1"
        assert len(uow._savepoints) == 2

    @pytest.mark.asyncio
    async def test_savepoint_in_non_active(self, uow):
        await uow.__aenter__()
        await uow.commit()
        with pytest.raises(ValueError, match="non-active transaction"):
            await uow.savepoint()

    @pytest.mark.asyncio
    async def test_rollback_to_savepoint(self, uow):
        await uow.__aenter__()
        await uow.savepoint("sp1")
        # Change some data
        uow.record_change("test_repo", "change1")
        # Rollback to savepoint
        result = await uow.rollback_to_savepoint("sp1")
        assert result is True
        # Change set should be reset to snapshot (empty)
        assert uow._change_set == {}
        assert len(uow._savepoints) == 0  # savepoints before and including sp1 removed
        # Test non-existent savepoint
        result2 = await uow.rollback_to_savepoint("nonexistent")
        assert result2 is False

    @pytest.mark.asyncio
    async def test_release_savepoint(self, uow):
        await uow.__aenter__()
        await uow.savepoint("sp1")
        await uow.savepoint("sp2")
        result = await uow.release_savepoint("sp1")
        assert result is True
        assert len(uow._savepoints) == 1
        assert uow._savepoints[0]["name"] == "sp2"
        # Release non-existent
        result2 = await uow.release_savepoint("nonexistent")
        assert result2 is False

    @pytest.mark.asyncio
    async def test_register_repository(self, uow, mock_repo):
        uow.register_repository("new_repo", mock_repo)
        assert "new_repo" in uow._repositories
        mock_repo._set_uow.assert_called_once_with(uow)

    def test_get_repository(self, uow, mock_repo):
        repo = uow.get_repository("test_repo")
        assert repo is mock_repo
        with pytest.raises(KeyError, match="not registered"):
            uow.get_repository("nonexistent")

    def test_add_hooks(self, uow):
        hook = AsyncMock()
        uow.add_before_commit_hook(hook)
        assert hook in uow._before_commit_hooks
        uow.add_after_commit_hook(hook)
        assert hook in uow._after_commit_hooks
        uow.add_after_rollback_hook(hook)
        assert hook in uow._after_rollback_hooks

    def test_record_change_and_get_change_summary(self, uow):
        uow.record_change("repo1", "change1")
        uow.record_change("repo1", "change2")
        uow.record_change("repo2", "change3")
        summary = uow._get_change_summary()
        assert summary["repo1"] == 2
        assert summary["repo2"] == 1

    @pytest.mark.asyncio
    async def test_flush(self, uow):
        await uow.__aenter__()
        repo = AsyncMock()
        repo._flush = AsyncMock()
        uow.register_repository("flush_repo", repo)

        await uow.flush()
        repo._flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_flush_in_non_active(self, uow):
        await uow.__aenter__()
        await uow.commit()
        with pytest.raises(ValueError, match="Cannot flush in non-active"):
            await uow.flush()

    @pytest.mark.asyncio
    async def test_execute_raw_sql(self, uow):
        await uow.__aenter__()
        result = await uow.execute_raw_sql("SELECT * FROM test", {"id": 1})
        assert result is None
        # Check audit log
        assert any(entry["action"] == "RAW_SQL" for entry in uow._audit_log)

    @pytest.mark.asyncio
    async def test_is_active(self, uow):
        await uow.__aenter__()
        assert await uow.is_active() is True
        await uow.commit()
        assert await uow.is_active() is False

    @pytest.mark.asyncio
    async def test_get_transaction_id(self, uow):
        await uow.__aenter__()
        tx_id = await uow.get_transaction_id()
        assert tx_id == uow._transaction_id
        assert isinstance(tx_id, UUID)

    @pytest.mark.asyncio
    async def test_get_isolation_level(self, uow):
        level = await uow.get_isolation_level()
        assert level == IsolationLevel.READ_COMMITTED.value

    @pytest.mark.asyncio
    async def test_transaction_context_manager(self, uow):
        # Test with success
        async with uow.transaction() as ctx:
            assert ctx is uow
            assert uow._status == TransactionStatus.ACTIVE
        # auto_commit False, so need explicit commit? Actually our uow auto_commit=False,
        # so within the context manager, it doesn't auto commit. But the transaction method
        # does NOT call commit on success unless auto_commit is True. Wait, the implementation:
        # inside transaction(), after yield, if self._auto_commit: commit. So with auto_commit=False,
        # no commit. We'll test with auto_commit=True separately.
        # Let's test with auto_commit=True
        uow_auto = InMemoryUnitOfWork(auto_commit=True)
        async with uow_auto.transaction():
            # register a repo with _commit to verify
            repo = AsyncMock()
            repo._commit = AsyncMock()
            uow_auto.register_repository("repo", repo)
        repo._commit.assert_called_once()

        # Test with exception
        uow_auto2 = InMemoryUnitOfWork(auto_commit=True)
        with pytest.raises(ValueError):
            async with uow_auto2.transaction():
                repo2 = AsyncMock()
                repo2._commit = AsyncMock()
                uow_auto2.register_repository("repo2", repo2)
                raise ValueError("test")
        repo2._commit.assert_not_called()
        assert uow_auto2._status == TransactionStatus.ROLLED_BACK

    @pytest.mark.asyncio
    async def test_execute_with_retry(self, uow):
        # Mock deadlock detector to raise DeadlockError twice then succeed
        async def func():
            if not hasattr(func, "call_count"):
                func.call_count = 0
            func.call_count += 1
            if func.call_count <= 2:
                raise DeadlockError("deadlock")
            return "success"

        await uow._execute_with_retry(func)
        assert func.call_count == 3

    @pytest.mark.asyncio
    async def test_execute_with_retry_exhausted(self, uow):
        async def func():
            raise DeadlockError("deadlock")

        with pytest.raises(DeadlockError):
            await uow._execute_with_retry(func)

    @pytest.mark.asyncio
    async def test_acquire_lock_and_release(self, uow):
        await uow.__aenter__()
        result = await uow._acquire_lock("lock1", 1.0)
        assert result is True
        # Try to acquire same lock again (should succeed, same tx)
        result2 = await uow._acquire_lock("lock1", 1.0)
        assert result2 is True
        # Release
        await uow._release_lock("lock1")
        # Now lock should be free

    @pytest.mark.asyncio
    async def test_acquire_lock_timeout(self, uow):
        await uow.__aenter__()
        # First acquire lock
        await uow._acquire_lock("lock1", 1.0)
        # Try to acquire with a different tx (simulate by using a different uow)
        uow2 = InMemoryUnitOfWork()
        await uow2.__aenter__()
        # Mock time to avoid actual sleep
        with patch("time.time") as mock_time:
            # Simulate timeout by making time advance beyond timeout
            mock_time.side_effect = [0.0, 0.1, 2.0]
            result = await uow2._acquire_lock("lock1", 1.0)
            assert result is False
        # Cleanup
        await uow._release_lock("lock1")


# -------------------- Tests for DeadlockDetector --------------------
class TestDeadlockDetector:
    @pytest.mark.asyncio
    async def test_acquire_release_lock(self):
        detector = DeadlockDetector()
        tx_id = uuid4()
        result = await detector.acquire_lock(tx_id, "lock1", 1.0)
        assert result is True
        assert detector._locks["lock1"] == tx_id

        # Same tx can re-acquire
        result2 = await detector.acquire_lock(tx_id, "lock1", 1.0)
        assert result2 is True

        # Different tx cannot acquire
        tx2 = uuid4()
        with patch("time.time") as mock_time:
            # Simulate timeout
            mock_time.side_effect = [0.0, 2.0]
            result3 = await detector.acquire_lock(tx2, "lock1", 1.0)
            assert result3 is False

        # Release
        await detector.release_lock(tx_id, "lock1")
        assert "lock1" not in detector._locks

    @pytest.mark.asyncio
    async def test_deadlock_detection(self):
        detector = DeadlockDetector()
        tx1 = uuid4()
        tx2 = uuid4()
        # tx1 holds lock1, tx2 holds lock2
        await detector.acquire_lock(tx1, "lock1", 1.0)
        await detector.acquire_lock(tx2, "lock2", 1.0)
        # tx1 waits for lock2, tx2 waits for lock1 -> cycle
        # Simulate tx1 waiting for lock2
        detector._waiting[tx1] = ["lock2"]
        detector._waiting[tx2] = ["lock1"]
        # Now detect cycle
        assert detector._detect_cycle(tx1, "lock2") is True  # tx1 wants lock2 held by tx2, tx2 wants lock1 held by tx1
        assert detector._detect_cycle(tx2, "lock1") is True

        # No cycle if tx1 waits for lock1 (held by itself)
        detector._waiting[tx1] = ["lock1"]
        assert detector._detect_cycle(tx1, "lock1") is False

    @pytest.mark.asyncio
    async def test_acquire_raises_on_deadlock(self):
        detector = DeadlockDetector()
        tx1 = uuid4()
        tx2 = uuid4()
        await detector.acquire_lock(tx1, "lock1", 1.0)
        await detector.acquire_lock(tx2, "lock2", 1.0)
        # tx1 wants lock2, but lock2 held by tx2 -> no deadlock yet
        detector._waiting[tx1] = ["lock2"]
        # Acquiring lock2 by tx1 should raise deadlock because tx2 also wants lock1?
        # Actually we need to set waiting for tx2 as well.
        detector._waiting[tx2] = ["lock1"]
        with pytest.raises(DeadlockError, match="Deadlock detected"):
            await detector.acquire_lock(tx1, "lock2", 1.0)


# -------------------- Tests for RepositoryProvider --------------------
class TestRepositoryProvider:
    def test_provider_attributes(self, provider):
        assert provider.journals() is not None
        assert provider.ledger_entries() is not None
        assert provider.accounts() is not None
        assert provider.ar_invoices() is not None
        assert provider.ap_invoices() is not None
        assert provider.inventory() is not None
        assert provider.fixed_assets() is not None
        assert provider.bank_accounts() is not None
        assert provider.cash_books() is not None
        assert provider.legal_entities() is not None
        assert provider.employees() is not None
        assert provider.customers() is not None
        assert provider.suppliers() is not None
        assert provider.iam_users() is not None
        assert provider.system_settings() is not None
        assert provider.tax_transactions() is not None

    def test_provider_with_none(self):
        provider = RepositoryProvider()
        assert provider.journals() is None
        assert provider.ledger_entries() is None
        # ... etc


# -------------------- Tests for Module-level Functions --------------------
@pytest.mark.asyncio
async def test_get_uow():
    # Reset global
    import ports.primary.unit_of_work_port as uow_module
    uow_module._uow_instance = None
    uow1 = get_uow()
    uow2 = get_uow()
    assert uow1 is uow2
    assert isinstance(uow1, InMemoryUnitOfWork)


@pytest.mark.asyncio
async def test_create_uow_with_provider(provider):
    uow = await create_uow_with_provider(provider)
    assert isinstance(uow, InMemoryUnitOfWork)
    # All repositories should be registered
    expected_repos = [
        "journals", "ledger_entries", "accounts", "ar_invoices",
        "ap_invoices", "inventory", "fixed_assets", "bank_accounts",
        "cash_books", "legal_entities", "employees", "customers",
        "suppliers", "iam_users", "system_settings", "tax_transactions"
    ]
    for repo_name in expected_repos:
        assert repo_name in uow._repositories

    # Test with provider that returns None for some repos
    provider_none = RepositoryProvider()
    uow2 = await create_uow_with_provider(provider_none)
    assert len(uow2._repositories) == 0


@pytest.mark.asyncio
async def test_get_uow_statistics(uow):
    # Reset global for clean state
    import ports.primary.unit_of_work_port as uow_module
    uow_module._uow_instance = uow
    stats = await get_uow_statistics()
    assert stats["status"] == "active"
    assert stats["repositories_registered"] == 1  # test_repo
    assert stats["savepoints_count"] == 0
    assert stats["audit_log_size"] == 0
    assert stats["transaction_id"] == str(uow._transaction_id)

    # With no uow initialized
    uow_module._uow_instance = None
    stats2 = await get_uow_statistics()
    assert stats2["status"] == "not_initialized"
    assert stats2["repositories_registered"] == 0
    assert stats2["transaction_id"] is None


# -------------------- Additional edge cases --------------------
@pytest.mark.asyncio
async def test_uow_audit_logging(uow):
    await uow.__aenter__()
    await uow.commit()
    # Check audit log contains entries
    assert any(entry["action"] == "BEGIN" for entry in uow._audit_log)
    assert any(entry["action"] == "COMMIT" for entry in uow._audit_log)

    # Rollback logging
    uow2 = InMemoryUnitOfWork()
    await uow2.__aenter__()
    await uow2.rollback()
    assert any(entry["action"] == "ROLLBACK" for entry in uow2._audit_log)

    # Error exit
    uow3 = InMemoryUnitOfWork()
    with pytest.raises(ValueError):
        async with uow3:
            raise ValueError("test")
    assert any(entry["action"] == "EXIT_WITH_ERROR" for entry in uow3._audit_log)


@pytest.mark.asyncio
async def test_savepoint_repository_snapshot(uow, mock_repo):
    await uow.__aenter__()
    mock_repo._savepoint.return_value = {"snapshot": "data"}
    await uow.savepoint("sp1")
    assert uow._savepoints[0]["repositories_snapshot"]["test_repo"] == {"snapshot": "data"}
    # Rollback to savepoint should call repo._rollback_to_savepoint
    mock_repo._rollback_to_savepoint.reset_mock()
    await uow.rollback_to_savepoint("sp1")
    mock_repo._rollback_to_savepoint.assert_called_once_with({"snapshot": "data"})


@pytest.mark.asyncio
async def test_release_savepoint_removes_correctly(uow):
    await uow.__aenter__()
    await uow.savepoint("sp1")
    await uow.savepoint("sp2")
    await uow.savepoint("sp3")
    await uow.release_savepoint("sp2")
    assert [sp["name"] for sp in uow._savepoints] == ["sp1", "sp3"]
    await uow.release_savepoint("sp1")
    assert [sp["name"] for sp in uow._savepoints] == ["sp3"]


@pytest.mark.asyncio
async def test_commit_without_repositories(uow):
    # No repositories with _commit method, commit should succeed
    await uow.__aenter__()
    await uow.commit()
    assert uow._status == TransactionStatus.COMMITTED


@pytest.mark.asyncio
async def test_rollback_to_savepoint_updates_change_set(uow):
    await uow.__aenter__()
    await uow.savepoint("sp1")
    uow.record_change("test_repo", "change1")
    uow.record_change("test_repo", "change2")
    assert len(uow._change_set["test_repo"]) == 2
    await uow.rollback_to_savepoint("sp1")
    assert "test_repo" not in uow._change_set


# ============================================================================
# ADDITIONAL COVERAGE TESTS untuk memastikan semua metode UnitOfWorkPort teruji
# ============================================================================

class TestUnitOfWorkPortCoverage:
    """Test tambahan untuk memastikan semua metode UnitOfWorkPort terpanggil."""

    def test_abstract_methods_exist(self):
        """Pastikan semua metode abstract didefinisikan di UnitOfWorkPort."""
        methods = [
            "__aenter__", "__aexit__", "commit", "rollback",
            "savepoint", "rollback_to_savepoint", "release_savepoint",
            "register_repository", "get_repository",
            "add_before_commit_hook", "add_after_commit_hook", "add_after_rollback_hook",
            "flush", "execute_raw_sql", "is_active", "get_transaction_id",
            "get_isolation_level", "transaction"
        ]
        for method in methods:
            assert hasattr(UnitOfWorkPort, method)
            # Pastikan metode tersebut abstract (kecuali transaction yang sudah punya implementasi default)
            if method != "transaction":
                assert getattr(UnitOfWorkPort, method).__isabstractmethod__ is True

    @pytest.mark.asyncio
    async def test_register_repository_on_interface(self):
        """Uji register_repository melalui antarmuka UnitOfWorkPort."""
        uow: UnitOfWorkPort = InMemoryUnitOfWork()
        repo = MagicMock()
        uow.register_repository("test_iface", repo)
        # Verifikasi melalui get_repository
        retrieved = uow.get_repository("test_iface")
        assert retrieved is repo

    @pytest.mark.asyncio
    async def test_get_repository_on_interface(self):
        """Uji get_repository melalui antarmuka UnitOfWorkPort."""
        uow: UnitOfWorkPort = InMemoryUnitOfWork()
        repo = MagicMock()
        uow.register_repository("test_iface2", repo)
        retrieved = uow.get_repository("test_iface2")
        assert retrieved is repo
        with pytest.raises(KeyError):
            uow.get_repository("nonexistent")

    @pytest.mark.asyncio
    async def test_add_before_commit_hook_on_interface(self):
        """Uji add_before_commit_hook melalui antarmuka UnitOfWorkPort."""
        uow: UnitOfWorkPort = InMemoryUnitOfWork()
        hook = AsyncMock(return_value=True)
        uow.add_before_commit_hook(hook)
        assert hook in uow._before_commit_hooks  # type: ignore

    @pytest.mark.asyncio
    async def test_add_after_commit_hook_on_interface(self):
        """Uji add_after_commit_hook melalui antarmuka UnitOfWorkPort."""
        uow: UnitOfWorkPort = InMemoryUnitOfWork()
        hook = AsyncMock()
        uow.add_after_commit_hook(hook)
        assert hook in uow._after_commit_hooks  # type: ignore

    @pytest.mark.asyncio
    async def test_add_after_rollback_hook_on_interface(self):
        """Uji add_after_rollback_hook melalui antarmuka UnitOfWorkPort."""
        uow: UnitOfWorkPort = InMemoryUnitOfWork()
        hook = AsyncMock()
        uow.add_after_rollback_hook(hook)
        assert hook in uow._after_rollback_hooks  # type: ignore

    def test_record_change_method(self):
        """Uji record_change secara langsung."""
        uow = InMemoryUnitOfWork()
        uow.record_change("repo_x", "change_1")
        uow.record_change("repo_x", "change_2")
        uow.record_change("repo_y", "change_3")
        assert uow._change_set["repo_x"] == ["change_1", "change_2"]
        assert uow._change_set["repo_y"] == ["change_3"]
        # Pastikan get_change_summary berfungsi
        summary = uow._get_change_summary()
        assert summary["repo_x"] == 2
        assert summary["repo_y"] == 1

    @pytest.mark.asyncio
    async def test_all_abstract_methods_implemented(self):
        """Pastikan InMemoryUnitOfWork mengimplementasikan semua metode abstract."""
        uow = InMemoryUnitOfWork()
        for method in UnitOfWorkPort.__abstractmethods__:
            assert hasattr(uow, method)
            # Pastikan bisa dipanggil (minimal tidak raise AttributeError)
            attr = getattr(uow, method)
            assert callable(attr)

    @pytest.mark.asyncio
    async def test_register_repository_with_set_uow(self):
        """Uji register_repository memanggil _set_uow pada repository."""
        uow = InMemoryUnitOfWork()
        repo = MagicMock()
        repo._set_uow = MagicMock()
        uow.register_repository("repo_with_set", repo)
        repo._set_uow.assert_called_once_with(uow)

    @pytest.mark.asyncio
    async def test_register_repository_without_set_uow(self):
        """Uji register_repository tidak error jika repository tidak punya _set_uow."""
        uow = InMemoryUnitOfWork()
        repo = MagicMock()
        # Tidak memiliki _set_uow
        uow.register_repository("repo_no_set", repo)
        assert "repo_no_set" in uow._repositories
