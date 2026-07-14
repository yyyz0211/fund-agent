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

事务边界:
- `_fetch_evidence_items` 完成所有 adapter 网络拉取(无 DB 调用),
  校验关键字段后返回纯 dict list;errors 累计在调用方传入的列表里。
- `ingest_market_evidence` 先调用 fetch 阶段(事务外),再开短事务
  完成 per-row upsert。session=None 时 `session_scope()` 自管理
  commit/close;外部传入 session 时只 flush,不开新事务、不 commit/close。
"""
from __future__ import annotations

from typing import Any

from backend.db.repository import upsert_market_evidence
from backend.db.session_scope import session_scope


def _adapter_name(adapter: Any) -> str:
    return getattr(adapter, "source", None) or type(adapter).__name__


def _fetch_evidence_items(
    *,
    adapters: list,
    trade_date: str,
    brief_type: str,
    errors: list[dict],
) -> list[tuple[str, dict]]:
    """纯网络阶段:跑全部 adapters, 失败隔离, 校验关键字段。

    无 DB 调用,可在事务外执行。错误累计到传入 `errors` 列表;
    返回 `(adapter_name, row_dict)` 元组列表 — 保留 adapter 来源,
    便于 upsert 阶段写错误时能指明来源 adapter。
    """
    items: list[tuple[str, dict]] = []
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
        for item in getattr(adapter, "last_errors", []) or []:
            if isinstance(item, dict):
                err = item.get("error") or str(item)
                errors.append({"adapter": name, "error": err, "details": item})
            else:
                errors.append({"adapter": name, "error": str(item)})
        if not rows:
            continue
        for row in rows:
            if not (row.get("source_url") and row.get("title") and row.get("category")):
                errors.append({
                    "adapter": name,
                    "error": "row missing required keys (source_url/title/category)",
                })
                continue
            # 强制覆盖 trade_date/brief_type, 防止 adapter 传错
            row["trade_date"] = trade_date
            row["brief_type"] = brief_type
            items.append((name, row))
    return items


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
        session: 可选 SQLAlchemy session; None 时使用 `session_scope()`
                 自行管理事务边界。

    Returns:
        {"inserted": int, "fetched": int, "errors": [...],
         "categories": {<category>: <count>, ...}}
    """
    if not adapters:
        return {"inserted": 0, "fetched": 0, "errors": [], "categories": {}}

    errors: list[dict] = []
    fetched = 0
    inserted = 0
    categories: dict[str, int] = {}

    # 阶段 1:adapter 拉取,无 DB 调用
    items = _fetch_evidence_items(
        adapters=adapters,
        trade_date=trade_date,
        brief_type=brief_type,
        errors=errors,
    )
    fetched = len(items)

    # 阶段 2:短事务 upsert。session=None 时自管,传入 session 时只 flush。
    def _write(s) -> None:
        nonlocal inserted
        for adapter_name, row in items:
            try:
                created = upsert_market_evidence(s, row)
            except Exception as exc:  # noqa: BLE001
                errors.append({"adapter": adapter_name,
                               "error": f"upsert: {exc}",
                               "source_url": row.get("source_url")})
                continue
            if created:
                inserted += 1
                categories[row["category"]] = categories.get(row["category"], 0) + 1

    try:
        if session is None:
            with session_scope() as s:
                _write(s)
        else:
            _write(session)
    except Exception as exc:  # noqa: BLE001
        errors.append({"adapter": "session", "error": f"commit: {exc}"})

    return {
        "inserted": inserted,
        "fetched": fetched,
        "errors": errors,
        "categories": categories,
    }