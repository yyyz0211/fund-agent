"""Scheduler: 定时任务调度.

本目录包含:
- jobs.py: JobSpec 定义规范
- scheduler.py: 原调度逻辑

新代码建议使用 JobSpec 定义任务。
"""
from __future__ import annotations

from backend.scheduler.jobs import JobSpec, cron_job, interval_job
from backend.scheduler.scheduler import get_scheduler, shutdown_scheduler, start_scheduler

__all__ = [
    "JobSpec",
    "cron_job",
    "interval_job",
    "start_scheduler",
    "shutdown_scheduler",
    "get_scheduler",
]
