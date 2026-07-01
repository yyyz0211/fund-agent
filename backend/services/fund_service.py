"""基金领域服务。

三个工具就绪接口,各自接收可选 `session` —— 为空时自己开/关一个
(`get_session()`),测试可以传入 in-memory Session。

所有成功返回都是普通 dict 并带 `source` / `as_of`,失败返回
`{"error": ..., "source": ...}`(沿用 collector 的契约)。
"""
from backend.db.session import get_session
from backend.db import repository as repo
from backend.services import data_collector as dc
from backend.services import metric_service as metrics


def _with_session(session):
    """有 session 用传入的;否则开一个新的(由调用方负责关闭)。"""
    return session or get_session()


def refresh_fund(fund_code: str, session=None) -> dict:
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
            repo.upsert_fund(s, {k: info.get(k) for k in
                                 ("fund_code", "fund_name", "fund_type", "manager", "company")})
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
            s.close()


def get_latest_nav(fund_code: str, session=None) -> dict:
    """从本地库读最新一天的累计净值。

    没有任何 NAV 数据时,返回 `{error, source}`,提示先调
    `refresh_fund`,而不是裸抛异常 —— 这样 LLM 可以把"数据缺失"
    当作可解释的失败处理。
    """
    s = _with_session(session)
    owns = session is None
    try:
        from sqlalchemy import select
        from backend.db.models import FundNav
        row = s.scalars(select(FundNav).where(FundNav.fund_code == fund_code)
                        .order_by(FundNav.nav_date.desc())).first()
        if row is None:
            return {"error": f"no nav data for {fund_code}; call refresh_fund first",
                    "source": dc.SOURCE}
        return {"fund_code": fund_code, "nav_date": row.nav_date,
                "accumulated_nav": row.accumulated_nav,
                "source": row.source or dc.SOURCE, "as_of": row.source_updated_at}
    finally:
        if owns:
            s.close()


def get_metrics(fund_code: str, period: str = "1m", session=None) -> dict:
    """从本地库读累计净值序列,跑区间/累计收益、最大回撤、波动率。

    数据不足(<2 个点)时返回错误字典。`period` 取自
    `metric_service` 支持的集合。
    """
    s = _with_session(session)
    owns = session is None
    try:
        navs = repo.get_accumulated_navs(s, fund_code)
        if len(navs) < 2:
            return {"error": f"insufficient nav data for {fund_code}; call refresh_fund first",
                    "source": dc.SOURCE}
        try:
            period_ret = metrics.period_return(navs, period)
        except ValueError as e:
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
    finally:
        if owns:
            s.close()


def get_basic_info(fund_code: str, session=None) -> dict:
    """从本地库读基金基础信息。无数据返回可读 error dict（提示先 refresh_fund）。"""
    s = _with_session(session)
    owns = session is None
    try:
        from backend.db.models import Fund
        row = s.get(Fund, fund_code)
        if row is None:
            return {"error": f"本地无 {fund_code} 基础信息，请先 refresh_fund",
                    "source": dc.SOURCE}
        return {"fund_code": row.fund_code, "fund_name": row.fund_name,
                "fund_type": row.fund_type, "manager": row.manager,
                "company": row.company, "source": dc.SOURCE, "as_of": dc.today_str()}
    finally:
        if owns:
            s.close()


def get_nav_history(fund_code: str, start_date: str = "", end_date: str = "",
                    session=None) -> dict:
    """从本地库读带日期的净值序列，支持可选区间过滤（空字符串=不限）。

    nav_date 为 YYYY-MM-DD 字符串，区间过滤用字符串比较。无数据返回 error dict。
    """
    s = _with_session(session)
    owns = session is None
    try:
        from sqlalchemy import select
        from backend.db.models import FundNav
        stmt = select(FundNav).where(FundNav.fund_code == fund_code)
        if start_date:
            stmt = stmt.where(FundNav.nav_date >= start_date)
        if end_date:
            stmt = stmt.where(FundNav.nav_date <= end_date)
        rows = s.scalars(stmt.order_by(FundNav.nav_date)).all()
        if not rows:
            return {"error": f"本地无 {fund_code} 净值数据，请先 refresh_fund",
                    "source": dc.SOURCE}
        navs = [{"nav_date": r.nav_date, "accumulated_nav": r.accumulated_nav,
                 "daily_return": r.daily_return} for r in rows]
        return {"fund_code": fund_code, "navs": navs, "count": len(navs),
                "source": dc.SOURCE, "as_of": dc.today_str()}
    finally:
        if owns:
            s.close()
