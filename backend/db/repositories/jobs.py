"""Jobs repository: 后台任务状态相关持久化。"""
from __future__ import annotations

from sqlalchemy import select

from backend.db.models import KnowledgeReindexJob


def list_knowledge_reindex_jobs(s, limit: int = 20) -> list[KnowledgeReindexJob]:
    """返回最近 N 条知识库重建任务,按 id 倒序。"""
    return list(s.scalars(
        select(KnowledgeReindexJob)
        .order_by(KnowledgeReindexJob.id.desc())
        .limit(max(1, int(limit)))
    ).all())


__all__ = ["list_knowledge_reindex_jobs"]
