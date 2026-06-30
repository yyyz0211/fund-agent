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

    流程:fetch_fund_info → upsert_fund → fetch_fund_nav_history →
    upsert_navs。任一 fetch 失败,直接返回它的错误字典(不下半段)。
    """
    s = _with_session(session)
    owns = session is None
    try:
        info = dc.fetch_fund_info(fund_code)
        if isinstance(info, dict) and "error" in info:
            return info
        repo.upsert_fund(s, {k: info.get(k) for k in
                             ("fund_code", "fund_name", "fund_type", "manager", "company")})
        navs = dc.fetch_fund_nav_history(fund_code)
        if isinstance(navs, dict) and "error" in navs:
            return navs
        inserted = repo.upsert_navs(s, fund_code, navs)
        return {"fund_code": fund_code, "navs_inserted": inserted,
                "source": dc.SOURCE, "as_of": dc.today_str()}
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
        return {
            "fund_code": fund_code,
            "period": period,
            "period_return": metrics.period_return(navs, period),
            "cumulative_return": metrics.cumulative_return(navs),
            "max_drawdown": metrics.max_drawdown(navs),
            "volatility": metrics.volatility(navs),
            "source": dc.SOURCE,
            "as_of": dc.today_str(),
        }
    finally:
        if owns:
            s.close()