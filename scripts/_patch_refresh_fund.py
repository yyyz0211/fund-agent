from pathlib import Path

p = Path("/Users/leon/fund-agent/backend/services/fund_service.py")
text = p.read_text(encoding="utf-8")

old = '''def refresh_fund(fund_code: str, session=None) -> dict:
    """拉取一只基金的最新基础信息和净值走势并入库。

    流程:fetch_fund_info → upsert_fund → fetch_fund_nav_history →
    upsert_navs。任一 fetch 失败,直接返回它的错误字典(不下半段)。

    返回字段:
      - `already_up_to_date`:True 表示本地已是最新,LLM 不必再调
        本工具。这是为了避免 `navs_inserted=0` 被模型误解为"上次
        没拉成功"而触发重复调用 —— 这是 graph 里"同一只 fund
        被刷 N 次"循环的主要诱因。
      - `navs_inserted`:本次实际新增的 NAV 行数,与旧字段名保持
        向下兼容。
    """
    s = _with_session(session)
    owns = session is None
    try:
        info = dc.fetch_fund_info(fund_code)
        if isinstance(info, dict) and "error" in info:
            return info
        repo.upsert_fund(s, {k: info.get(k) for k
                             ("fund_code", "fund_name", "fund_type", "manager", "company")})
        navs = dc.fetch_fund_nav_history(fund_code)
        if isinstance(navs, dict) and "error" in navs:
            return navs
        inserted = repo.upsert_navs(s, fund_code, navs)
        return {
            "fund_code": fund_code,
            "navs_inserted": inserted,
            "already_up_to_date": inserted == 0,
            "source": dc.SOURCE,
            "as_of": dc.today_str(),
        }
    finally:
        if owns:
            s.close()'''

new = '''def refresh_fund(fund_code: str, session=None) -> dict:
    """拉取一只基金的最新基础信息和净值走势并入库。

    流程(2026-07 调整):先 fetch_fund_nav_history(必须成功) →
    fetch_fund_info(失败仅 warning, 不阻断)。原因:雪球蛋卷
    `danjuanfunds.com` 在 2026-06 后 100% 返回"版本过低",
    导致 fund_name/manager/company 这一组元信息拿不到,但东财
    `fund_open_fund_info_em` 的 NAV 历史仍然能跑;如果死守旧顺序
    拉不到 fund_name 就放弃,用户连 NAV 都没有,跟"这只基金
    没拉过"没区别。

    返回字段:
      - `already_up_to_date`:True 表示本地已是最新。
      - `navs_inserted`:本次实际新增的 NAV 行数。
      - `fund_info_warn`:str | None —— 拉取 fund_name/manager 等
        失败时放原因(成功为 None)。前端可以提示"基础信息未拉取"
        但不影响 NAV 显示。
    """
    s = _with_session(session)
    owns = session is None
    try:
        navs = dc.fetch_fund_nav_history(fund_code)
        if isinstance(navs, dict) and "error" in navs:
            return navs
        inserted = repo.upsert_navs(s, fund_code, navs)

        info = dc.fetch_fund_info(fund_code)
        fund_info_warn = None
        if isinstance(info, dict) and "error" in info:
            fund_info_warn = info["error"]
        else:
            repo.upsert_fund(s, {k: info.get(k) for k
                                 in ("fund_code", "fund_name",
                                     "fund_type", "manager", "company")})
        return {
            "fund_code": fund_code,
            "navs_inserted": inserted,
            "already_up_to_date": inserted == 0,
            "fund_info_warn": fund_info_warn,
            "source": dc.SOURCE,
            "as_of": dc.today_str(),
        }
    finally:
        if owns:
            s.close()'''

count = text.count(old)
print(f"occurrences: {count}")
assert count == 1
p.write_text(text.replace(old, new), encoding="utf-8")
print("OK")
