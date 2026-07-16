"""知识库重建任务 (`KnowledgeReindexJob`) 的服务层。

设计动机：
- 把 `run_knowledge_pipeline_once` 从请求线程里挪到后台线程,耗时秒级,
  让前端通过 `job_id` 轮询状态。
- scheduler 触发的 run_knowledge_pipeline_once 也复用同一张表,
  方便前后端统一观察所有重建任务。
- 完整 pipeline 使用稳定业务键 `knowledge_reindex:pipeline` 单飞，避免
  手动与定时触发重复执行；CLS 同步等其它业务使用不同 key，仍可并发。
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from backend.db.repositories import jobs as jobs_repo
from backend.db.models import KnowledgeReindexJob
from backend.db.session_scope import session_scope

logger = logging.getLogger(__name__)

_PIPELINE_SINGLEFLIGHT_KEY = "knowledge_reindex:pipeline"


def create_job(*, trigger: str, session: Optional[Session] = None) -> KnowledgeReindexJob:
    """落一条 pending 任务并返回 ORM 实例。

    Args:
        trigger: `manual` 或 `scheduled`。
        session: 复用的 session；为空时新建。事务由调用方决定提交时机。
    """
    if session is None:
        with session_scope() as s:
            return create_job(trigger=trigger, session=s)
    job = KnowledgeReindexJob(trigger=trigger, status="pending")
    session.add(job)
    session.flush()
    return job


def mark_running(job_id: int) -> None:
    """把任务标记为 running（独立 session/事务，避免长时间持有）。"""
    with session_scope() as s:
        job = s.get(KnowledgeReindexJob, job_id)
        if job is None:
            return
        job.status = "running"
        job.started_at = datetime.utcnow()


def mark_completed(job_id: int, *, result: dict, latency_ms: int) -> None:
    """任务成功完成,落 result 和耗时。"""
    with session_scope() as s:
        job = s.get(KnowledgeReindexJob, job_id)
        if job is None:
            return
        job.status = "completed"
        job.finished_at = datetime.utcnow()
        job.latency_ms = int(latency_ms)
        try:
            job.result_json = json.dumps(result, ensure_ascii=False)
        except (TypeError, ValueError):
            job.result_json = json.dumps({"unparseable": True}, ensure_ascii=False)


def mark_failed(job_id: int, *, error: str, latency_ms: Optional[int] = None) -> None:
    """任务失败,落 error_message。"""
    with session_scope() as s:
        job = s.get(KnowledgeReindexJob, job_id)
        if job is None:
            return
        job.status = "failed"
        job.finished_at = datetime.utcnow()
        if latency_ms is not None:
            job.latency_ms = int(latency_ms)
        # 截断超长错误，避免任务状态行和 API payload 无限制膨胀。
        job.error_message = (error or "")[:2000]


def get_job(job_id: int, *, session: Optional[Session] = None) -> Optional[dict]:
    """读一条任务的快照(纯 dict,不持有 ORM session)。"""
    if session is None:
        with session_scope() as s:
            return get_job(job_id, session=s)
    job = session.get(KnowledgeReindexJob, job_id)
    if job is None:
        return None
    return {
        "job_id": int(job.id),
        "trigger": job.trigger,
        "status": job.status,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "latency_ms": job.latency_ms,
        "result": _safe_load_json(job.result_json),
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }


def list_jobs(*, limit: int = 20, session: Optional[Session] = None) -> list[dict]:
    """返回最近 N 条任务(降序)。"""
    if session is None:
        with session_scope() as s:
            return list_jobs(limit=limit, session=s)
    rows = jobs_repo.list_knowledge_reindex_jobs(session, limit=limit)
    return [
        {
            "job_id": int(r.id),
            "trigger": r.trigger,
            "status": r.status,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "latency_ms": r.latency_ms,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "error_message": r.error_message,
        }
        for r in rows
    ]


def run_job_in_background(
    job_id: int,
    *,
    pipeline_kwargs: dict,
) -> threading.Thread:
    """在后台线程跑 pipeline,负责状态写入。

    Args:
        job_id: `KnowledgeReindexJob.id`。
        pipeline_kwargs: 传给 `run_knowledge_pipeline_once` 的 kwargs
            (例如 `{"trigger": "manual", "limit": 50}`)。

    Returns:
        启动的 `threading.Thread` 实例(daemon=True),调用方可选择 join。
    """
    from backend.services.knowledge.knowledge_search_service import run_knowledge_pipeline_once
    from backend.services.shared.process_singleflight import (
        SingleflightBusy,
        process_singleflight,
    )

    def _runner():
        started = datetime.utcnow()
        try:
            with process_singleflight(
                _PIPELINE_SINGLEFLIGHT_KEY,
                timeout_seconds=0.0,
            ):
                mark_running(job_id)
                try:
                    result = run_knowledge_pipeline_once(**pipeline_kwargs)
                except Exception as exc:  # noqa: BLE001
                    latency = int((datetime.utcnow() - started).total_seconds() * 1000)
                    logger.exception("[knowledge_reindex] job=%s failed", job_id)
                    mark_failed(
                        job_id,
                        error=f"{type(exc).__name__}: {exc}",
                        latency_ms=latency,
                    )
                    return

                latency = int((datetime.utcnow() - started).total_seconds() * 1000)
                mark_completed(job_id, result=result, latency_ms=latency)
        except SingleflightBusy as exc:
            logger.warning("[knowledge_reindex] job=%s busy_skipped: %s", job_id, exc)
            _mark_busy_skipped(job_id, error=str(exc))

    thread = threading.Thread(
        target=_runner,
        name=f"knowledge-reindex-{job_id}",
        daemon=True,
    )
    thread.start()
    return thread


def _mark_busy_skipped(job_id: int, *, error: str) -> None:
    with session_scope() as s:
        job = s.get(KnowledgeReindexJob, job_id)
        if job is None:
            return
        job.status = "busy_skipped"
        job.finished_at = datetime.utcnow()
        job.error_message = (error or "")[:2000]


def _safe_load_json(value: Optional[str]) -> Optional[dict]:
    if not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def recover_interrupted_jobs(older_than_seconds: int) -> int:
    """把 stale pending/running 任务标记为 interrupted。

    Args:
        older_than_seconds: 只处理超过此秒数的任务。

    Returns:
        被标记为 interrupted 的任务数量。
    """
    from datetime import timedelta
    from backend.config.settings import get_settings

    cutoff = datetime.utcnow() - timedelta(seconds=older_than_seconds)
    recovered = 0
    with session_scope() as s:
        stale = s.query(KnowledgeReindexJob).filter(
            KnowledgeReindexJob.status.in_(["pending", "running"]),
            KnowledgeReindexJob.created_at < cutoff,
        ).all()
        for job in stale:
            job.status = "interrupted"
            job.finished_at = datetime.utcnow()
            job.error_message = (
                f"Recovered after {older_than_seconds}s stale. "
                f"Original created_at={job.created_at.isoformat()}"
            )[:2000]
            recovered += 1
    return recovered
