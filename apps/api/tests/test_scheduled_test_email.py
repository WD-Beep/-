from unittest.mock import patch

import pytest

from app.core.config import Settings
from app.scheduler.manager import SCHEDULED_TEST_EMAIL_JOB_ID, SchedulerManager


def _settings(*, enabled: bool = True) -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/test",
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_user="sender@example.com",
        smtp_password="secret",
        smtp_from="sender@example.com",
        smtp_test_recipient="ops@example.com",
        smtp_test_schedule_enabled=enabled,
        smtp_test_interval_minutes=15,
    )


@pytest.mark.asyncio
async def test_scheduler_registers_scheduled_test_email_when_enabled():
    manager = SchedulerManager()
    SchedulerManager._instance = manager
    try:
        with patch("app.scheduler.manager.settings", _settings(enabled=True)):
            manager.start()
            job = manager.scheduler.get_job(SCHEDULED_TEST_EMAIL_JOB_ID)
            assert job is not None
            assert job.id == SCHEDULED_TEST_EMAIL_JOB_ID
    finally:
        manager.shutdown()
        SchedulerManager._instance = None


@pytest.mark.asyncio
async def test_scheduler_skips_scheduled_test_email_when_disabled():
    manager = SchedulerManager()
    SchedulerManager._instance = manager
    try:
        with patch("app.scheduler.manager.settings", _settings(enabled=False)):
            manager.start()
            assert manager.scheduler.get_job(SCHEDULED_TEST_EMAIL_JOB_ID) is None
    finally:
        manager.shutdown()
        SchedulerManager._instance = None
