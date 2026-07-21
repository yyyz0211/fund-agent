"""基金领域服务。

读取接口接收可选 `session`:调用方传入时沿用其事务,否则通过
`session_scope()` 创建短事务。刷新接口先完成网络拉取,再开启短写事务。

所有成功返回都是普通 dict 并带 `source` / `as_of`,失败返回
`{"error": ..., "source": ...}`(沿用 collector 的契约)。失败 dict 可
额外带 `error_kind`(`not_found` / `invalid_param` / `data_source`),供
API 层稳定映射 HTTP 状态码,不再靠 error 文案子串猜测。LLM 侧忽略该键。
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from backend.db.repositories import fund as fund_repo
from backend.db.session_scope import session_scope
from backend.exceptions import InputValidationError
from backend.services.market import data_collector as dc
from backend.services.shared import metric_service as metrics
from backend.services.fund import pnl_service as psvc
from backend.services.watchlist import watchlist_service as wsvc


_REFRESH_FETCH_WORKERS = 2
_AUTO_REFRESH_POLICIES = {"if_missing_or_stale", "always", "never"}


def refresh_fund(fund_code: str, session=None) -> dict:
    """拉取一只基金的最新基础信息和净值走势并入库。

    网络拉取与数据库写入分为两个阶段,避免等待 AkShare 时持有事务。

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
    navs, info = _collect_refresh_data(fund_code)
    if isinstance(navs, dict) and "error" in navs:
        return navs

    if session is None:
        with session_scope() as s:
            inserted, fund_info_warn = _persist_refresh_data(s, fund_code, navs, info)
    else:
        inserted, fund_info_warn = _persist_refresh_data(
            session, fund_code, navs, info,
        )

    return {
        "fund_code": fund_code,
        "navs_inserted": inserted,
        "already_up_to_date": inserted == 0,
        "fund_info_warn": fund_info_warn,
        "source": dc.SOURCE,
        "as_of": dc.today_str(),
    }


def _persist_refresh_data(
    session,
    fund_code: str,
    navs: list[dict],
    info: dict,
) -> tuple[int, str | None]:
    """写入已抓取的基金数据；调用方拥有事务。"""
    inserted = fund_repo.upsert_navs(session, fund_code, navs)
    if isinstance(info, dict) and "error" in info:
        return inserted, info["error"]
    fund_repo.upsert_fund(session, {
        key: info.get(key)
        for key in ("fund_code", "fund_name", "fund_type", "manager", "company")
    })
    return inserted, None


def _collector_error(label: str, fund_code: str, exc: Exception) -> dict:
    return {
        "error": f"{label} failed for {fund_code}: {exc}",
        "source": dc.SOURCE,
    }


def _collect_refresh_data(fund_code: str) -> tuple[list[dict] | dict, dict]:
    """并行读取 NAV 与基础信息;写库仍由 `refresh_fund` 串行完成。"""
    with ThreadPoolExecutor(max_workers=_REFRESH_FETCH_WORKERS) as executor:
        nav_future = executor.submit(dc.fetch_fund_nav_history, fund_code)
        info_future = executor.submit(dc.fetch_fund_info, fund_code)
        try:
            navs = nav_future.result()
        except Exception as exc:  # noqa: BLE001
            navs = _collector_error("fetch_fund_nav_history", fund_code, exc)
        try:
            info = info_future.result()
        except Exception as exc:  # noqa: BLE001
            info = _collector_error("fetch_fund_info", fund_code, exc)
    return navs, info


def get_latest_nav(fund_code: str, session=None) -> dict:
    """从本地库读最新一天的累计净值。

    没有任何 NAV 数据时,返回 `{error, source}`,提示先调
    `refresh_fund`,而不是裸抛异常 —— 这样 LLM 可以把"数据缺失"
    当作可解释的失败处理。
    """
    if session is None:
        with session_scope() as s:
            return get_latest_nav(fund_code, session=s)

    from sqlalchemy import select
    from backend.db.models import FundNav
    row = session.scalars(select(FundNav).where(FundNav.fund_code == fund_code)
                          .order_by(FundNav.nav_date.desc())).first()
    if row is None:
        return {"error": f"no nav data for {fund_code}; call refresh_fund first",
                "error_kind": "not_found",
                "source": dc.SOURCE}
    return {"fund_code": fund_code, "nav_date": row.nav_date,
            "accumulated_nav": row.accumulated_nav,
            "daily_return": row.daily_return,
            "source": row.source or dc.SOURCE, "as_of": row.source_updated_at}


def get_nav_by_date(fund_code: str, nav_date: str, session=None) -> dict:
    """按净值日精确读取本地 NAV。无匹配行返回 error dict。"""
    if session is None:
        with session_scope() as s:
            return get_nav_by_date(fund_code, nav_date, session=s)

    row = fund_repo.get_nav_by_date(session, fund_code, nav_date)
    if row is None:
        return {
            "error": f"no nav data for {fund_code} on date {nav_date}; call refresh_fund first",
            "error_kind": "not_found",
            "source": dc.SOURCE,
        }
    return row


def get_metrics(fund_code: str, period: str = "1m", session=None) -> dict:
    """从本地库读累计净值序列,跑区间/累计收益、最大回撤、波动率。

    数据不足(<2 个点)时返回错误字典。`period` 取自
    `metric_service` 支持的集合。
    """
    if session is None:
        with session_scope() as s:
            return get_metrics(fund_code, period=period, session=s)

    navs = fund_repo.get_accumulated_navs(session, fund_code)
    if len(navs) < 2:
        return {"error": f"insufficient nav data for {fund_code}; call refresh_fund first",
                "error_kind": "not_found",
                "source": dc.SOURCE}
    try:
        period_ret = metrics.period_return(navs, period)
    except (ValueError, InputValidationError) as e:
        return {"error": str(e), "source": dc.SOURCE}
    return {
        "fund_code": fund_code,
        "period": period,
        "period_return": period_ret,
        "cumulative_return": metrics.cumulative_return(navs),
        "max_drawdown": metrics.max_drawdown(navs),
        "volatility": metrics.volatility(navs),
        "source": dc.SOURCE,
        "as_of": dc.today_str(),
    }


def get_basic_info(fund_code: str, session=None) -> dict:
    """从本地库读基金基础信息。无数据返回可读 error dict（提示先 refresh_fund）。"""
    if session is None:
        with session_scope() as s:
            return get_basic_info(fund_code, session=s)

    from backend.db.models import Fund
    row = session.get(Fund, fund_code)
    if row is None:
        return {"error": f"本地无 {fund_code} 基础信息，请先 refresh_fund",
                "error_kind": "not_found",
                "source": dc.SOURCE}
    return {"fund_code": row.fund_code, "fund_name": row.fund_name,
            "fund_type": row.fund_type, "manager": row.manager,
            "company": row.company, "source": dc.SOURCE, "as_of": dc.today_str()}


def get_nav_history(fund_code: str, start_date: str = "", end_date: str = "",
                    session=None) -> dict:
    """从本地库读带日期的净值序列，支持可选区间过滤（空字符串=不限）。

    nav_date 为 YYYY-MM-DD 字符串，区间过滤用字符串比较。无数据返回 error dict。
    """
    if session is None:
        with session_scope() as s:
            return get_nav_history(
                fund_code,
                start_date=start_date,
                end_date=end_date,
                session=s,
            )

    from sqlalchemy import select
    from backend.db.models import FundNav
    stmt = select(FundNav).where(FundNav.fund_code == fund_code)
    if start_date:
        stmt = stmt.where(FundNav.nav_date >= start_date)
    if end_date:
        stmt = stmt.where(FundNav.nav_date <= end_date)
    rows = session.scalars(stmt.order_by(FundNav.nav_date)).all()
    if not rows:
        return {"error": f"本地无 {fund_code} 净值数据，请先 refresh_fund",
                "error_kind": "not_found",
                "source": dc.SOURCE}
    navs = [{"nav_date": r.nav_date, "accumulated_nav": r.accumulated_nav,
             "daily_return": r.daily_return} for r in rows]
    return {"fund_code": fund_code, "navs": navs, "count": len(navs),
            "source": dc.SOURCE, "as_of": dc.today_str()}


def _summary_value(result: dict, key: str, errors: dict[str, str]) -> dict | None:
    if isinstance(result, dict) and "error" in result:
        errors[key] = result["error"]
        return None
    return result


def _parse_iso_date(value) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _auto_refresh_reason(
    latest_nav: dict | None,
    refresh_policy: str,
    stale_days: int,
) -> str | None:
    if refresh_policy == "never":
        return None
    if refresh_policy == "always":
        return "always"
    if not latest_nav or latest_nav.get("error"):
        return "missing_nav"

    nav_date = _parse_iso_date(latest_nav.get("nav_date"))
    today = _parse_iso_date(dc.today_str())
    if not nav_date or not today:
        return "stale_nav"
    if (today - nav_date).days > stale_days:
        return "stale_nav"
    return None


def _local_lookup_payload(fund_code: str, period: str, session) -> dict:
    errors: dict[str, str] = {}
    fund = _summary_value(
        get_basic_info(fund_code, session=session),
        "fund",
        errors,
    )
    latest_nav = _summary_value(
        get_latest_nav(fund_code, session=session),
        "latest_nav",
        errors,
    )
    metric_payload = _summary_value(
        get_metrics(fund_code, period=period, session=session),
        "metrics",
        errors,
    )
    nav_history = _summary_value(
        get_nav_history(fund_code, session=session),
        "nav_history",
        errors,
    )
    return {
        "fund_code": fund_code,
        "fund": fund,
        "latest_nav": latest_nav,
        "metrics": metric_payload,
        "nav_history": nav_history,
        "errors": errors,
        "source": dc.SOURCE,
        "as_of": dc.today_str(),
    }


def lookup_fund_auto(
    fund_code: str,
    period: str = "1y",
    refresh_policy: str = "if_missing_or_stale",
    stale_days: int = 3,
    session=None,
) -> dict:
    """读取基金数据;本地缺失或过期时先主动刷新再返回。

    这是给 LangGraph 问答使用的确定性入口:LLM 不需要自己串
    `get_latest_fund_nav -> refresh_fund -> get_metrics`,只调用本函数
    并根据 `refresh` / `errors` 解释结果即可。
    """
    if refresh_policy not in _AUTO_REFRESH_POLICIES:
        return {
            "fund_code": fund_code,
            "error": f"unsupported refresh_policy: {refresh_policy}",
            "error_kind": "invalid_param",
            "source": dc.SOURCE,
            "as_of": dc.today_str(),
        }

    initial_latest = get_latest_nav(fund_code, session=session)
    reason = _auto_refresh_reason(initial_latest, refresh_policy, stale_days)
    refresh_meta = {
        "attempted": False,
        "reason": reason,
        "result": None,
        "error": None,
    }

    if reason:
        refresh_meta["attempted"] = True
        try:
            result = refresh_fund(fund_code, session=session)
        except Exception as exc:  # noqa: BLE001
            result = {"error": str(exc), "source": dc.SOURCE}
        refresh_meta["result"] = result
        if isinstance(result, dict) and result.get("error"):
            refresh_meta["error"] = result["error"]

    if session is None:
        with session_scope() as s:
            payload = _local_lookup_payload(fund_code, period=period, session=s)
    else:
        payload = _local_lookup_payload(fund_code, period=period, session=session)
    payload["refresh"] = refresh_meta
    return payload


def diagnose_fund_auto(
    fund_code: str,
    period: str = "1y",
    refresh_policy: str = "if_missing_or_stale",
    stale_days: int = 3,
    session=None,
) -> dict:
    """主动补齐本地基金数据后运行确定性基金体检。"""
    lookup = lookup_fund_auto(
        fund_code,
        period=period,
        refresh_policy=refresh_policy,
        stale_days=stale_days,
        session=session,
    )
    if "error" in lookup:
        return lookup

    from backend.services.shared import diagnosis_service as ds

    if session is None:
        with session_scope() as s:
            diagnosis = ds.diagnose_fund(fund_code, period=period, session=s)
    else:
        diagnosis = ds.diagnose_fund(fund_code, period=period, session=session)
    if not isinstance(diagnosis, dict):
        return {
            "fund_code": fund_code,
            "error": "diagnose_fund returned non-dict result",
            "refresh": lookup.get("refresh"),
            "source": dc.SOURCE,
            "as_of": dc.today_str(),
        }
    out = dict(diagnosis)
    out["refresh"] = lookup.get("refresh")
    out["lookup_errors"] = lookup.get("errors", {})
    out["lookup_as_of"] = lookup.get("as_of")
    return out


def get_summary(
    fund_code: str,
    period: str = "1m",
    start_date: str = "",
    session=None,
) -> dict:
    """聚合详情页首屏需要的本地只读数据,不触发联网刷新。"""
    if session is None:
        with session_scope() as s:
            return get_summary(
                fund_code,
                period=period,
                start_date=start_date,
                session=s,
            )

    errors: dict[str, str] = {}
    fund = _summary_value(
        get_basic_info(fund_code, session=session),
        "fund",
        errors,
    )
    latest_nav = _summary_value(
        get_latest_nav(fund_code, session=session),
        "latest_nav",
        errors,
    )
    metric_payload = _summary_value(
        get_metrics(fund_code, period=period, session=session),
        "metrics",
        errors,
    )
    nav_history = _summary_value(
        get_nav_history(fund_code, start_date=start_date, session=session),
        "nav_history",
        errors,
    )
    watchlist = wsvc.get_one(fund_code, session=session)
    pnl = psvc.calculate_pnl(fund_codes=[fund_code], session=session)
    pnl_item = next(
        (item for item in pnl.get("items", []) if item["fund_code"] == fund_code),
        None,
    )
    pnl_skipped = next(
        (item for item in pnl.get("skipped", []) if item["fund_code"] == fund_code),
        None,
    )

    return {
        "fund_code": fund_code,
        "fund": fund,
        "latest_nav": latest_nav,
        "metrics": metric_payload,
        "nav_history": nav_history,
        "watchlist": watchlist,
        "pnl_item": pnl_item,
        "pnl_skipped": pnl_skipped,
        "errors": errors,
        "source": dc.SOURCE,
        "as_of": dc.today_str(),
    }
