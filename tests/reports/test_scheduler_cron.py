from datetime import datetime

import pytest


class TestSchedulerCron:
    @pytest.fixture
    def setup_scheduler(self):
        """Setup ReportScheduler instance for testing"""
        from reports.scheduler_cron import ReportScheduler

        scheduler = ReportScheduler()
        return scheduler

    def test_init_with_default_config(self, setup_scheduler):
        """Test initialization with default configuration"""
        scheduler = setup_scheduler

        assert hasattr(scheduler, '_config') or hasattr(scheduler, 'scheduler')

    @pytest.mark.asyncio
    async def test_schedule_basic_job(self, setup_scheduler):
        """Test scheduling a basic job"""
        scheduler = setup_scheduler

        def dummy_task():
            return "Task executed"

        job_id = await scheduler.schedule_job(
            job_id='test_job',
            func=dummy_task,
            cron_expression='*/5 * * * *'
        )

        assert job_id == 'test_job'

    def test_validate_cron_expression(self, setup_scheduler):
        """Test validation of cron expressions"""
        scheduler = setup_scheduler

        valid_expr = '0 9 * * *'
        is_valid = scheduler.validate_cron_expression(valid_expr)
        assert is_valid is True

        invalid_expr = 'invalid cron'
        is_valid = scheduler.validate_cron_expression(invalid_expr)
        assert is_valid is False

    def test_calculate_next_run_time(self, setup_scheduler):
        """Test calculation of next run time for cron jobs"""
        scheduler = setup_scheduler

        cron_expr = '0 9 * * *'
        next_run = scheduler.calculate_next_run(cron_expr)

        assert isinstance(next_run, datetime)

    @pytest.mark.asyncio
    async def test_pause_and_resume_job(self, setup_scheduler):
        """Test pausing and resuming scheduled jobs"""
        scheduler = setup_scheduler

        def dummy_task():
            return "Paused task"

        job_id = await scheduler.schedule_job(
            job_id='pause_test',
            func=dummy_task,
            cron_expression='* * * * *'
        )

        await scheduler.pause_job(job_id)

        job = scheduler.get_job(job_id)
        assert job is not None

        await scheduler.resume_job(job_id)

        job = scheduler.get_job(job_id)
        assert job is not None

    @pytest.mark.asyncio
    async def test_remove_job(self, setup_scheduler):
        """Test removing scheduled jobs"""
        scheduler = setup_scheduler

        def dummy_task():
            return "Removable task"

        job_id = await scheduler.schedule_job(
            job_id='removable_job',
            func=dummy_task,
            cron_expression='* * * * *'
        )

        assert scheduler.job_exists(job_id) is True

        result = await scheduler.remove_job(job_id)

        assert result is True

    @pytest.mark.asyncio
    async def test_list_all_jobs(self, setup_scheduler):
        """Test listing all scheduled jobs"""
        scheduler = setup_scheduler

        def dummy_task():
            return "List test task"

        job_ids = []
        for i in range(3):
            job_id = await scheduler.schedule_job(
                job_id=f'list_test_{i}',
                func=dummy_task,
                cron_expression='* * * * *'
            )
            job_ids.append(job_id)

        jobs_list = scheduler.list_jobs()

        assert len(jobs_list) >= 3
