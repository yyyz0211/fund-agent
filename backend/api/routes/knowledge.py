"""知识库 / RAG 检索路由。"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from backend.api.deps import get_db_session
from backend.config.settings import get_settings
from backend.db.init_db import rebuild_pgvector_schema
from backend.db.session import engine as default_engine
from backend.services import knowledge_reindex_jobs, knowledge_search_service


router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


@router.post("/vector-schema/rebuild")
def rebuild_vector_schema(
    confirm: bool = Query(default=False),
    _trigger: str | None = Header(default=None, alias="X-Local-Trigger"),
):
    """Explicit destructive rebuild of the disposable PostgreSQL vector index."""
    if not _trigger or _trigger.lower() not in ("1", "true"):
        raise HTTPException(status_code=403, detail="missing X-Local-Trigger header")
    try:
        requeued = rebuild_pgvector_schema(
            default_engine,
            get_settings().knowledge_embedding_dimensions,
            confirmed=confirm,
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "rebuilt", "requeued_documents": requeued}


@router.get("/search")
def search_knowledge(
    query: str = Query(default=""),
    fund_code: str | None = Query(default=None),
    topic: str | None = Query(default=None),
    source_type: str | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=50),
    include_pending: bool = Query(default=False),
    session: Session = Depends(get_db_session),
):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=400, detail="date_from must not be later than date_to")
    try:
        result = knowledge_search_service.search_knowledge(
            query=query,
            fund_code=fund_code,
            topic=topic,
            source_type=source_type,
            date_from=date_from.isoformat() if date_from else None,
            date_to=date_to.isoformat() if date_to else None,
            limit=limit,
            include_pending=include_pending,
            session=session,
        )
        session.commit()
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/queue-status")
def queue_status(
    source_type: str | None = Query(default=None),
    classification_status: str | None = Query(default=None),
    index_status: str | None = Query(default=None),
    since: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db_session),
):
    return knowledge_search_service.get_queue_status(
        source_type=source_type,
        classification_status=classification_status,
        index_status=index_status,
        since=since,
        limit=limit,
        session=session,
    )


@router.post("/reindex", status_code=status.HTTP_202_ACCEPTED)
def reindex_knowledge(
    response: Response,
    _trigger: str | None = Header(default=None, alias="X-Local-Trigger"),
    limit: int | None = Query(default=None, ge=1, le=200),
    session: Session = Depends(get_db_session),
):
    """异步触发一次知识库增量准入、索引和基金匹配。

    行为变更（vs 旧版）：
    - 立刻在 `knowledge_reindex_jobs` 表落一行 pending，并启动后台线程
      执行 pipeline；不阻塞 uvicorn 工作线程。
    - 锁被占（scheduler job 正在跑）时，job 状态会变成 `busy_skipped`，
      不会让请求线程挂着等几十秒。
    - 必须带 `X-Local-Trigger` 头，避免部署时被外部请求误触发。

    轮询：`GET /api/knowledge/reindex/{job_id}`。
    """
    if not _trigger or _trigger.lower() not in ("1", "true"):
        raise HTTPException(status_code=403, detail="missing X-Local-Trigger header")

    job = knowledge_reindex_jobs.create_job(trigger="manual", session=session)
    job_id = int(job.id)
    session.commit()
    pipeline_kwargs = {"trigger": "manual"}
    if limit is not None:
        pipeline_kwargs["limit"] = int(limit)
    knowledge_reindex_jobs.run_job_in_background(job_id, pipeline_kwargs=pipeline_kwargs)

    response.headers["Location"] = f"/api/knowledge/reindex/{job_id}"
    return {
        "status": "started",
        "job_id": job_id,
        "trigger": "manual",
        "poll_url": f"/api/knowledge/reindex/{job_id}",
    }


@router.get("/reindex/{job_id}")
def get_reindex_status(job_id: int):
    """查询 reindex 任务状态。"""
    snapshot = knowledge_reindex_jobs.get_job(job_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"job {job_id} not found")
    return snapshot


@router.get("/reindex")
def list_reindex_jobs(limit: int = Query(default=20, ge=1, le=100)):
    """列出最近 N 条 reindex 任务,按 id 倒序。"""
    return {"jobs": knowledge_reindex_jobs.list_jobs(limit=limit)}
