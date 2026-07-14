"""Scheduler jobs: Job 定义规范.

用于描述定时任务的元信息,与 APScheduler 解耦。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal, Mapping


@dataclass(frozen=True, slots=True)
class JobSpec:
    """Job 定义规范"""

    id: str  # 唯一标识,用于单飞和日志
    callable: Callable[[], object]  # 执行逻辑
    trigger: Literal["cron", "interval"]  # 触发类型
    trigger_kwargs: Mapping[str, object]  # 触发参数
    max_instances: int = 1  # 最大并发实例数
    coalesce: bool = True  # 是否合并错过触发
    misfire_grace_time: int | None = None  # 错过触发宽限期(秒)
    jitter: int | None = None  # 随机延迟(秒)

    def to_apscheduler_kwargs(self) -> dict:
        """转换为 APScheduler.add_job() 参数"""
        kwargs = dict(self.trigger_kwargs)
        kwargs.update(
            id=self.id,
            trigger=self.trigger,
            max_instances=self.max_instances,
            coalesce=self.coalesce,
        )
        if self.misfire_grace_time is not None:
            kwargs["misfire_grace_time"] = self.misfire_grace_time
        if self.jitter is not None:
            kwargs["jitter"] = self.jitter
        return kwargs


def cron_job(
    id: str,
    callable: Callable[[], object],
    trigger_kwargs: Mapping[str, object],
    max_instances: int = 1,
    coalesce: bool = True,
    misfire_grace_time: int | None = None,
    jitter: int | None = None,
) -> JobSpec:
    """创建 Cron JobSpec"""
    return JobSpec(
        id=id,
        callable=callable,
        trigger="cron",
        trigger_kwargs=trigger_kwargs,
        max_instances=max_instances,
        coalesce=coalesce,
        misfire_grace_time=misfire_grace_time,
        jitter=jitter,
    )


def interval_job(
    id: str,
    callable: Callable[[], object],
    trigger_kwargs: Mapping[str, object],
    max_instances: int = 1,
    coalesce: bool = True,
    misfire_grace_time: int | None = None,
    jitter: int | None = None,
) -> JobSpec:
    """创建 Interval JobSpec"""
    return JobSpec(
        id=id,
        callable=callable,
        trigger="interval",
        trigger_kwargs=trigger_kwargs,
        max_instances=max_instances,
        coalesce=coalesce,
        misfire_grace_time=misfire_grace_time,
        jitter=jitter,
    )


__all__ = [
    "JobSpec",
    "cron_job",
    "interval_job",
]
