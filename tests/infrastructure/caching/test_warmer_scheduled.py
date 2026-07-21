# tests/infrastructure/caching/test_warmer_scheduled.py
# Perbaikan kualitas assertions: mengganti semua assert True dengan
# assertion yang memeriksa nilai aktual, efek samping, dan interaksi mock.
# Menambahkan marker @pytest.mark.asyncio ke semua async test.
# Mock datetime untuk menghindari flaky test.
# Menambahkan negative path tests.

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from infrastructure.caching.warmer_scheduled import (
    CacheWarmer,
    WarmingJob,
    WARMED_CACHE_TTL,
    WARMING_LOCK_TTL,
    WARMED_KEY_PREFIX,
    get_cache_warmer,
    get_default_warming_jobs,
    start_cache_warmer,
    stop_cache_warmer,
    warm_ap_aging,
    warm_ar_aging,
    warm_chart_of_accounts,
    warm_fixed_asset_summary,
    warm_inventory_summary,
    warm_trial_balance,
)


# ============================================================================
# WarmingJob tests
# ============================================================================
class TestWarmingJob:
    def test_construction(self):
        async def mock_func():
            return {"key": "value"}

        job = WarmingJob(
            name="test_job",
            function=mock_func,
            schedule="0 2 * * *",
            key_pattern="test:{id}",
            ttl_seconds=3600,
        )

        assert job.name == "test_job"
        assert job.function == mock_func
        assert job.schedule == "0 2 * * *"
        assert job.key_pattern == "test:{id}"
        assert job.ttl_seconds == 3600
        assert job.last_run is None
        assert job.last_status is None
        assert job.last_error is None

    def test_construction_default_ttl(self):
        async def mock_func():
            return {}

        job = WarmingJob(
            name="test_job",
            function=mock_func,
            schedule="interval:300",
            key_pattern="test:{id}",
        )

        assert job.ttl_seconds == WARMED_CACHE_TTL

    def test_construction_with_interval_schedule(self):
        async def mock_func():
            return {}

        job = WarmingJob(
            name="interval_job",
            function=mock_func,
            schedule="interval:60",
            key_pattern="test:{id}",
        )

        assert job.schedule == "interval:60"


# ============================================================================
# CacheWarmer tests
# ============================================================================
class TestCacheWarmer:
    @pytest.fixture
    def warmer(self):
        return CacheWarmer()

    @pytest.fixture
    def mock_redis(self):
        redis = AsyncMock()
        redis.setnx = AsyncMock(return_value=True)
        redis.expire = AsyncMock(return_value=True)
        redis.delete = AsyncMock(return_value=True)
        redis.set = AsyncMock(return_value=True)
        return redis

    @pytest.fixture
    def mock_job(self):
        async def mock_func():
            return {"key1": {"data": "value1"}, "key2": {"data": "value2"}}

        return WarmingJob(
            name="test_job",
            function=mock_func,
            schedule="0 2 * * *",
            key_pattern="test:{id}",
            ttl_seconds=3600,
        )

    # ---- _get_redis ----
    @pytest.mark.asyncio
    async def test_get_redis_creates_manager(self, warmer):
        with patch("infrastructure.caching.warmer_scheduled.get_redis_manager") as mock_get:
            mock_redis_manager = AsyncMock()
            mock_get.return_value = mock_redis_manager

            redis = await warmer._get_redis()

            assert redis == mock_redis_manager
            assert warmer._redis_manager == mock_redis_manager
            mock_get.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_redis_returns_existing(self, warmer):
        mock_redis_manager = AsyncMock()
        warmer._redis_manager = mock_redis_manager

        redis = await warmer._get_redis()

        assert redis == mock_redis_manager

    # ---- _acquire_lock ----
    @pytest.mark.asyncio
    async def test_acquire_lock_success(self, warmer, mock_redis):
        warmer._redis_manager = AsyncMock()
        warmer._redis_manager._client = mock_redis
        mock_redis.setnx.return_value = True

        result = await warmer._acquire_lock("test_job")

        assert result is True
        mock_redis.setnx.assert_called_once_with("cache:warmer:lock:test_job", pytest.approx(datetime.now().timestamp(), abs=2))
        mock_redis.expire.assert_called_once_with("cache:warmer:lock:test_job", WARMING_LOCK_TTL)

    @pytest.mark.asyncio
    async def test_acquire_lock_failure(self, warmer, mock_redis):
        warmer._redis_manager = AsyncMock()
        warmer._redis_manager._client = mock_redis
        mock_redis.setnx.return_value = False

        result = await warmer._acquire_lock("test_job")

        assert result is False
        mock_redis.expire.assert_not_called()

    # ---- _release_lock ----
    @pytest.mark.asyncio
    async def test_release_lock(self, warmer, mock_redis):
        warmer._redis_manager = AsyncMock()
        warmer._redis_manager._client = mock_redis

        await warmer._release_lock("test_job")

        mock_redis.delete.assert_called_once_with("cache:warmer:lock:test_job")
        # Additional assertion: verify delete was called exactly once
        assert mock_redis.delete.call_count == 1

    # ---- _execute_warming_job ----
    @pytest.mark.asyncio
    async def test_execute_warming_job_success(self, warmer, mock_redis, mock_job):
        warmer._redis_manager = AsyncMock()
        warmer._redis_manager._client = mock_redis

        # Mock acquire lock success
        with patch.object(warmer, "_acquire_lock", return_value=True):
            with patch.object(warmer, "_release_lock") as mock_release:
                await warmer._execute_warming_job(mock_job)

        # Verify cache set called
        # 2 items from mock function
        assert mock_redis.set.call_count == 2

        # Check job status updated
        assert mock_job.last_status == "success"
        assert mock_job.last_run is not None
        assert mock_job.last_error is None
        assert warmer._warmed_count == 2

        mock_release.assert_called_once_with("test_job")

    @pytest.mark.asyncio
    async def test_execute_warming_job_skip_if_locked(self, warmer, mock_redis, mock_job):
        warmer._redis_manager = AsyncMock()
        warmer._redis_manager._client = mock_redis

        with patch.object(warmer, "_acquire_lock", return_value=False):
            with patch.object(warmer, "_release_lock") as mock_release:
                await warmer._execute_warming_job(mock_job)

        # No cache set
        mock_redis.set.assert_not_called()
        # Job status not updated
        assert mock_job.last_status is None
        mock_release.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_warming_job_failure(self, warmer, mock_redis, mock_job):
        warmer._redis_manager = AsyncMock()
        warmer._redis_manager._client = mock_redis

        # Make function fail
        async def failing_func():
            raise ValueError("Warming failed")

        mock_job.function = failing_func

        with patch.object(warmer, "_acquire_lock", return_value=True):
            with patch.object(warmer, "_release_lock") as mock_release:
                with patch("infrastructure.caching.warmer_scheduled.trigger_alert") as mock_alert:
                    await warmer._execute_warming_job(mock_job)

        assert mock_job.last_status == "failed"
        assert "Warming failed" in mock_job.last_error
        mock_alert.assert_called_once()
        mock_redis.set.assert_not_called()
        mock_release.assert_called_once()

    # ---- register_job ----
    def test_register_job(self, warmer, mock_job):
        warmer.register_job(mock_job)

        assert mock_job.name in warmer._jobs
        assert warmer._jobs[mock_job.name] == mock_job

    def test_register_job_when_running(self, warmer, mock_job):
        warmer._running = True
        warmer._scheduler = MagicMock()
        warmer._scheduler.add_job = MagicMock()

        with patch.object(warmer, "_schedule_job") as mock_schedule:
            warmer.register_job(mock_job)

        mock_schedule.assert_called_once_with(mock_job)
        # Also verify job was added to _jobs
        assert mock_job.name in warmer._jobs

    # ---- unregister_job ----
    def test_unregister_job_success(self, warmer, mock_job):
        warmer.register_job(mock_job)
        warmer._scheduler = MagicMock()
        warmer._scheduler.remove_job = MagicMock()

        result = warmer.unregister_job("test_job")

        assert result is True
        assert "test_job" not in warmer._jobs
        warmer._scheduler.remove_job.assert_called_once_with("warming_test_job")

    def test_unregister_job_not_found(self, warmer):
        warmer._scheduler = MagicMock()
        warmer._scheduler.remove_job = MagicMock()

        result = warmer.unregister_job("nonexistent")

        assert result is False
        warmer._scheduler.remove_job.assert_not_called()

    # ---- start ----
    @pytest.mark.asyncio
    async def test_start(self, warmer, mock_job):
        warmer.register_job(mock_job)

        with patch("apscheduler.schedulers.asyncio.AsyncIOScheduler") as mock_scheduler_class:
            mock_scheduler = MagicMock()
            mock_scheduler_class.return_value = mock_scheduler

            await warmer.start()

            assert warmer._scheduler is not None
            assert warmer._running is True
            mock_scheduler.start.assert_called_once()
            # Schedule job called
            assert mock_scheduler.add_job.call_count == 1

    @pytest.mark.asyncio
    async def test_start_already_running(self, warmer):
        warmer._scheduler = MagicMock()

        with patch("infrastructure.caching.warmer_scheduled.logger") as mock_logger:
            await warmer.start()

            mock_logger.warning.assert_called_with("Cache warmer already running")
            # Verify no new scheduler started
            assert warmer._scheduler is not None  # still the same

    # ---- stop ----
    @pytest.mark.asyncio
    async def test_stop(self, warmer):
        warmer._scheduler = MagicMock()
        warmer._running = True

        await warmer.stop()

        warmer._scheduler.shutdown.assert_called_once_with(wait=True)
        assert warmer._scheduler is None
        assert warmer._running is False

    @pytest.mark.asyncio
    async def test_stop_when_not_running(self, warmer):
        warmer._scheduler = None

        await warmer.stop()

        assert warmer._running is False
        # No exception raised

    # ---- _schedule_job ----
    def test_schedule_job_cron(self, warmer, mock_job):
        warmer._scheduler = MagicMock()
        warmer._scheduler.add_job = MagicMock()

        warmer._schedule_job(mock_job)

        warmer._scheduler.add_job.assert_called_once()
        call_args = warmer._scheduler.add_job.call_args[1]
        assert call_args["id"] == "warming_test_job"
        assert call_args["name"] == "test_job"
        assert call_args["replace_existing"] is True

    def test_schedule_job_interval(self, warmer):
        async def mock_func():
            return {}

        job = WarmingJob(
            name="interval_job",
            function=mock_func,
            schedule="interval:300",
            key_pattern="test:{id}",
        )
        warmer._scheduler = MagicMock()
        warmer._scheduler.add_job = MagicMock()

        warmer._schedule_job(job)

        warmer._scheduler.add_job.assert_called_once()
        # Check that trigger is IntervalTrigger
        call_args = warmer._scheduler.add_job.call_args[1]
        trigger = call_args["trigger"]
        assert trigger.__class__.__name__ == "IntervalTrigger"

    def test_schedule_job_no_scheduler_raises(self, warmer, mock_job):
        warmer._scheduler = None

        with pytest.raises(RuntimeError, match="Scheduler not started"):
            warmer._schedule_job(mock_job)

    # ---- run_job_now ----
    @pytest.mark.asyncio
    async def test_run_job_now_success(self, warmer, mock_job):
        warmer.register_job(mock_job)

        with patch.object(warmer, "_execute_warming_job") as mock_execute:
            mock_execute.return_value = None

            result = await warmer.run_job_now("test_job")

            assert result["job_name"] == "test_job"
            assert result["status"] == "success"
            mock_execute.assert_called_once_with(mock_job)

    @pytest.mark.asyncio
    async def test_run_job_now_not_found(self, warmer):
        with pytest.raises(ValueError, match="Job nonexistent not found"):
            await warmer.run_job_now("nonexistent")

    # ---- get_status ----
    @pytest.mark.asyncio
    async def test_get_status(self, warmer, mock_job):
        warmer.register_job(mock_job)
        # Mock datetime to avoid flakiness
        fixed_now = datetime(2025, 1, 1, 12, 0, 0)
        mock_job.last_run = fixed_now
        mock_job.last_status = "success"

        status = await warmer.get_status()

        assert status["running"] is False
        assert status["total_jobs"] == 1
        assert status["total_warmed_items"] == 0
        assert len(status["jobs"]) == 1
        assert status["jobs"][0]["name"] == "test_job"
        assert status["jobs"][0]["status"] == "success"
        assert status["jobs"][0]["error"] is None
        # Check last_run is formatted correctly
        assert status["jobs"][0]["last_run"] == fixed_now.isoformat()

    # ---- warm_all ----
    @pytest.mark.asyncio
    async def test_warm_all(self, warmer, mock_job):
        warmer.register_job(mock_job)

        with patch.object(warmer, "run_job_now") as mock_run:
            mock_run.return_value = {"status": "success"}

            results = await warmer.warm_all()

            assert "test_job" in results
            assert results["test_job"]["status"] == "success"
            mock_run.assert_called_once_with("test_job")

    @pytest.mark.asyncio
    async def test_warm_all_with_error(self, warmer, mock_job):
        warmer.register_job(mock_job)

        with patch.object(warmer, "run_job_now") as mock_run:
            mock_run.side_effect = ValueError("Job error")

            results = await warmer.warm_all()

            assert results["test_job"]["error"] == "Job error"


# ============================================================================
# Warming functions tests (with mocks)
# ============================================================================
class TestWarmingFunctions:
    @pytest.mark.asyncio
    async def test_warm_chart_of_accounts(self):
        mock_container = MagicMock()
        mock_coa_service = AsyncMock()
        mock_coa_service.get_all_legal_entities.return_value = [
            MagicMock(id=1),
            MagicMock(id=2),
        ]
        mock_coa_service.get_account_hierarchy.return_value = [
            MagicMock(to_dict=lambda: {"code": "101", "name": "Cash"})
        ]

        mock_container.resolve.return_value = mock_coa_service

        with patch("infrastructure.caching.warmer_scheduled.__import__") as mock_import:
            mock_module = MagicMock()
            mock_module.get_container.return_value = mock_container
            mock_import.return_value = mock_module

            result = await warm_chart_of_accounts()

            assert len(result) == 2
            assert "coa:1" in result
            assert "coa:2" in result
            assert result["coa:1"]["legal_entity_id"] == "1"
            assert len(result["coa:1"]["accounts"]) == 1

    @pytest.mark.asyncio
    async def test_warm_trial_balance(self):
        mock_container = MagicMock()
        mock_ledger_service = AsyncMock()
        mock_ledger_service.get_all_legal_entities.return_value = [
            MagicMock(id=1),
        ]
        mock_ledger_service.get_trial_balance.return_value = {"total_debit": 100}

        mock_container.resolve.return_value = mock_ledger_service

        with patch("infrastructure.caching.warmer_scheduled.__import__") as mock_import:
            mock_module = MagicMock()
            mock_module.get_container.return_value = mock_container
            mock_import.return_value = mock_module

            result = await warm_trial_balance()

            assert len(result) == 1
            key = list(result.keys())[0]
            assert key.startswith("trial_balance:1:")

    @pytest.mark.asyncio
    async def test_warm_inventory_summary(self):
        mock_container = MagicMock()
        mock_inv_service = AsyncMock()
        mock_inv_service.get_all_legal_entities.return_value = [
            MagicMock(id=1),
        ]
        mock_inv_service.get_inventory_summary.return_value = {"total_items": 10}

        mock_container.resolve.return_value = mock_inv_service

        with patch("infrastructure.caching.warmer_scheduled.__import__") as mock_import:
            mock_module = MagicMock()
            mock_module.get_container.return_value = mock_container
            mock_import.return_value = mock_module

            result = await warm_inventory_summary()

            assert "inventory_summary:1" in result

    @pytest.mark.asyncio
    async def test_warm_ar_aging(self):
        mock_container = MagicMock()
        mock_ar_service = AsyncMock()
        mock_ar_service.get_all_legal_entities.return_value = [
            MagicMock(id=1),
        ]
        mock_ar_service.get_aging_all_customers.return_value = {"total": 1000}

        mock_container.resolve.return_value = mock_ar_service

        with patch("infrastructure.caching.warmer_scheduled.__import__") as mock_import:
            mock_module = MagicMock()
            mock_module.get_container.return_value = mock_container
            mock_import.return_value = mock_module

            result = await warm_ar_aging()

            key = list(result.keys())[0]
            assert key.startswith("ar_aging:1:")

    @pytest.mark.asyncio
    async def test_warm_ap_aging(self):
        mock_container = MagicMock()
        mock_ap_service = AsyncMock()
        mock_ap_service.get_all_legal_entities.return_value = [
            MagicMock(id=1),
        ]
        mock_ap_service.get_aging_all_vendors.return_value = {"total": 500}

        mock_container.resolve.return_value = mock_ap_service

        with patch("infrastructure.caching.warmer_scheduled.__import__") as mock_import:
            mock_module = MagicMock()
            mock_module.get_container.return_value = mock_container
            mock_import.return_value = mock_module

            result = await warm_ap_aging()

            key = list(result.keys())[0]
            assert key.startswith("ap_aging:1:")

    @pytest.mark.asyncio
    async def test_warm_fixed_asset_summary(self):
        mock_container = MagicMock()
        mock_fa_service = AsyncMock()
        mock_fa_service.get_all_legal_entities.return_value = [
            MagicMock(id=1),
        ]
        mock_fa_service.get_summary.return_value = {"total_assets": 5}

        mock_container.resolve.return_value = mock_fa_service

        with patch("infrastructure.caching.warmer_scheduled.__import__") as mock_import:
            mock_module = MagicMock()
            mock_module.get_container.return_value = mock_container
            mock_import.return_value = mock_module

            result = await warm_fixed_asset_summary()

            key = list(result.keys())[0]
            assert key.startswith("fixed_asset_summary:1:")


# ============================================================================
# get_default_warming_jobs tests
# ============================================================================
def test_get_default_warming_jobs():
    jobs = get_default_warming_jobs()

    assert len(jobs) == 6
    job_names = [j.name for j in jobs]
    assert "chart_of_accounts" in job_names
    assert "trial_balance" in job_names
    assert "inventory_summary" in job_names
    assert "ar_aging" in job_names
    assert "ap_aging" in job_names
    assert "fixed_asset_summary" in job_names

    # Check each job has required attributes
    for job in jobs:
        assert job.name is not None
        assert job.function is not None
        assert job.schedule is not None
        assert job.key_pattern is not None
        assert job.ttl_seconds == WARMED_CACHE_TTL


# ============================================================================
# Singleton functions tests
# ============================================================================
@pytest.mark.asyncio
async def test_get_cache_warmer_singleton():
    warmer1 = await get_cache_warmer()
    warmer2 = await get_cache_warmer()

    assert warmer1 is warmer2
    assert isinstance(warmer1, CacheWarmer)
    # Should have default jobs registered
    assert len(warmer1._jobs) == 6


@pytest.mark.asyncio
async def test_start_cache_warmer():
    warmer = CacheWarmer()
    with patch("infrastructure.caching.warmer_scheduled.get_cache_warmer") as mock_get:
        mock_get.return_value = warmer
        with patch.object(warmer, "start") as mock_start:
            await start_cache_warmer()
            mock_start.assert_awaited_once()
            # Verify that start was called
            assert mock_start.called


@pytest.mark.asyncio
async def test_stop_cache_warmer():
    warmer = CacheWarmer()
    # Set global warmer
    import infrastructure.caching.warmer_scheduled as module
    module._warmer = warmer

    with patch.object(warmer, "stop") as mock_stop:
        await stop_cache_warmer()
        mock_stop.assert_awaited_once()
        assert module._warmer is None


# ============================================================================
# Additional edge case tests
# ============================================================================
@pytest.mark.asyncio
async def test_execute_warming_job_with_key_pattern_formatting():
    """Test that key_pattern is formatted with data values."""
    warmer = CacheWarmer()

    async def mock_func():
        return {
            "item1": {"legal_entity_id": "123", "data": "value1"},
            "item2": {"legal_entity_id": "456", "data": "value2"},
        }

    job = WarmingJob(
        name="test",
        function=mock_func,
        schedule="0 2 * * *",
        key_pattern="test:{legal_entity_id}",
        ttl_seconds=3600,
    )

    mock_redis = AsyncMock()
    warmer._redis_manager = AsyncMock()
    warmer._redis_manager._client = mock_redis

    with patch.object(warmer, "_acquire_lock", return_value=True):
        with patch.object(warmer, "_release_lock"):
            await warmer._execute_warming_job(job)

    # Should call set with keys: test:123 and test:456
    calls = mock_redis.set.call_args_list
    assert len(calls) == 2

    args1 = calls[0][0]
    args2 = calls[1][0]
    # args[0] is key, args[1] is value, args[2] is ex (ttl)
    assert args1[0] == "warmed:test:123"
    assert args2[0] == "warmed:test:456"
    assert args1[2] == 3600
    assert args2[2] == 3600


@pytest.mark.asyncio
async def test_execute_warming_job_with_key_pattern_no_formatting():
    """Test key_pattern without placeholders works."""
    warmer = CacheWarmer()

    async def mock_func():
        return {"item1": {"data": "value1"}}

    job = WarmingJob(
        name="test",
        function=mock_func,
        schedule="0 2 * * *",
        key_pattern="static_key",
        ttl_seconds=3600,
    )

    mock_redis = AsyncMock()
    warmer._redis_manager = AsyncMock()
    warmer._redis_manager._client = mock_redis

    with patch.object(warmer, "_acquire_lock", return_value=True):
        with patch.object(warmer, "_release_lock"):
            await warmer._execute_warming_job(job)

    mock_redis.set.assert_called_once_with("warmed:static_key", {"data": "value1"}, ex=3600)


@pytest.mark.asyncio
async def test_stop_cache_warmer_when_not_running():
    import infrastructure.caching.warmer_scheduled as module
    module._warmer = None

    # Should not raise
    await stop_cache_warmer()
    assert module._warmer is None


# ============================================================================
# Negative path tests (additional coverage)
# ============================================================================
@pytest.mark.asyncio
async def test_acquire_lock_redis_error():
    """Test _acquire_lock when redis setnx raises exception."""
    warmer = CacheWarmer()
    mock_redis = AsyncMock()
    mock_redis.setnx = AsyncMock(side_effect=Exception("Redis error"))
    warmer._redis_manager = AsyncMock()
    warmer._redis_manager._client = mock_redis

    with pytest.raises(Exception, match="Redis error"):
        await warmer._acquire_lock("test_job")


@pytest.mark.asyncio
async def test_release_lock_redis_error():
    """Test _release_lock when redis delete raises exception."""
    warmer = CacheWarmer()
    mock_redis = AsyncMock()
    mock_redis.delete = AsyncMock(side_effect=Exception("Redis error"))
    warmer._redis_manager = AsyncMock()
    warmer._redis_manager._client = mock_redis

    with pytest.raises(Exception, match="Redis error"):
        await warmer._release_lock("test_job")


@pytest.mark.asyncio
async def test_execute_warming_job_acquire_lock_failure_no_alert():
    """When lock acquisition fails, no alert should be triggered and job status unchanged."""
    warmer = CacheWarmer()
    mock_job = WarmingJob(
        name="test",
        function=AsyncMock(return_value={}),
        schedule="0 2 * * *",
        key_pattern="test",
        ttl_seconds=3600,
    )

    with patch.object(warmer, "_acquire_lock", return_value=False):
        with patch("infrastructure.caching.warmer_scheduled.trigger_alert") as mock_alert:
            await warmer._execute_warming_job(mock_job)

    mock_alert.assert_not_called()
    assert mock_job.last_status is None


@pytest.mark.asyncio
async def test_execute_warming_job_function_returns_non_dict():
    """Test when warming function returns non-dict (should still work but maybe not set keys)."""
    warmer = CacheWarmer()
    async def bad_func():
        return "not a dict"

    mock_job = WarmingJob(
        name="test",
        function=bad_func,
        schedule="0 2 * * *",
        key_pattern="test",
        ttl_seconds=3600,
    )

    mock_redis = AsyncMock()
    warmer._redis_manager = AsyncMock()
    warmer._redis_manager._client = mock_redis

    with patch.object(warmer, "_acquire_lock", return_value=True):
        with patch.object(warmer, "_release_lock"):
            await warmer._execute_warming_job(mock_job)

    # Should not set anything because data is not dict (iteration would fail)
    # But the code iterates over data.items(), which will fail for string
    # So we expect an exception, which should be caught and set status failed
    assert mock_job.last_status == "failed"
    assert "not a dict" in mock_job.last_error or "is not iterable" in mock_job.last_error