from backend.db.session import get_session
from backend.db import repository as repo
from backend.services import data_collector as dc
from backend.services import metric_service as metrics


def _with_session(session):
    return session or get_session()


def refresh_fund(fund_code: str, session=None) -> dict:
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
