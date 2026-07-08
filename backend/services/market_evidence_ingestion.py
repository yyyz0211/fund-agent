"""market_evidence_ingestion: 编排全量 evidence 采集, 失败隔离, 去重 upsert。

签名锁定 untracked 测试期望:
    result = ing.ingest_market_evidence(
        trade_date="...", brief_type="...", adapters=[...], session=...,
    )
    assert result["inserted"] == 1
    assert result["fetched"] == 2
    assert result["errors"] == []
    assert result["categories"] == {"policy": 1}

Adapter 抛异常 → 记录进 `errors`, 不中断。
"""
from __future__ import annotations

from typing import Any

from backend.db.repository import upsert_market_evidence
from backend.db.session import get_session


def _adapter_name(adapter: Any) -> str:
    return getattr(adapter, "source", None) or type(adapter).__name__


def ingest_market_evidence(
    *,
    trade_date: str,
    brief_type: str = "post_market",
    adapters: list | None = None,
    session=None,
) -> dict:
    """跑全部 adapters, 失败隔离, 去重 upsert。

    Args:
        trade_date: YYYY-MM-DD
        brief_type: pre_market / post_market
        adapters: source adapter 列表; None 时返回 insert=0/fetched=0/...
        session: 可选 SQLAlchemy session; None 时使用进程内 session

    Returns:
        {"inserted": int, "fetched": int, "errors": [...],
         "categories": {<category>: <count>, ...}}
    """
    if not adapters:
        return {"inserted": 0, "fetched": 0, "errors": [], "categories": {}}

    owns = session is None
    s = session or get_session()
    inserted = 0
    fetched = 0
    errors: list[dict] = []
    categories: dict[str, int] = {}

    try:
        for adapter in adapters:
            name = _adapter_name(adapter)
            try:
                rows = adapter.fetch(
                    client=None,  # adapter 内部可选用 client, 这里不强制注入
                    trade_date=trade_date,
                    brief_type=brief_type,
                )
            except Exception as exc:  # noqa: BLE001
                errors.append({"adapter": name, "error": str(exc)})
                continue
            if not rows:
                continue
            for row in rows:
                # 校验关键字段
                if not (row.get("source_url") and row.get("title") and row.get("category")):
                    errors.append({
                        "adapter": name,
                        "error": "row missing required keys (source_url/title/category)",
                    })
                    continue
                fetched += 1
                # 强制覆盖 trade_date/brief_type, 防止 adapter 传错
                row["trade_date"] = trade_date
                row["brief_type"] = brief_type
                try:
                    created = upsert_market_evidence(s, row)
                except Exception as exc:  # noqa: BLE001
                    errors.append({"adapter": name, "error": f"upsert: {exc}"})
                    continue
                if created:
                    inserted += 1
                    categories[row["category"]] = categories.get(row["category"], 0) + 1
        try:
            s.commit()
        except Exception as exc:  # noqa: BLE001
            errors.append({"adapter": "session", "error": f"commit: {exc}"})
    finally:
        if owns:
            s.close()

    return {
        "inserted": inserted,
        "fetched": fetched,
        "errors": errors,
        "categories": categories,
    }