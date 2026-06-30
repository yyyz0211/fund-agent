import time
from datetime import date

SOURCE = "akshare"


def today_str() -> str:
    return date.today().isoformat()


def with_retry(fn, *args, retries: int = 3, base_delay: float = 0.5,
               sleep=time.sleep, **kwargs):
    last = None
    for attempt in range(retries):
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001 — collector boundary, re-raised below
            last = e
            if attempt < retries - 1:
                sleep(base_delay * (2 ** attempt))
    raise last


def fetch_fund_info(fund_code: str) -> dict:
    try:
        import akshare as ak
        df = with_retry(ak.fund_individual_info_em, fund_code)
        kv = dict(zip(df["item"], df["value"])) if "item" in df.columns \
            else dict(zip(df.iloc[:, 0], df.iloc[:, 1]))
        return {
            "fund_code": fund_code,
            "fund_name": kv.get("基金简称") or kv.get("基金名称"),
            "fund_type": kv.get("基金类型"),
            "manager": kv.get("基金经理"),
            "company": kv.get("基金管理人") or kv.get("基金公司"),
            "source": SOURCE,
            "as_of": today_str(),
        }
    except Exception as e:  # noqa: BLE001
        return {"error": f"fetch_fund_info failed for {fund_code}: {e}", "source": SOURCE}


def fetch_fund_nav_history(fund_code: str) -> list[dict] | dict:
    try:
        import akshare as ak
        df = with_retry(ak.fund_open_fund_info_em, fund_code, indicator="累计净值走势")
        out = []
        prev = None
        for _, r in df.iterrows():
            acc = float(r["累计净值"])
            dr = (acc / prev - 1) if prev not in (None, 0) else 0.0
            out.append({
                "nav_date": str(r["净值日期"]),
                "unit_nav": None,
                "accumulated_nav": acc,
                "daily_return": dr,
                "source": SOURCE,
                "source_updated_at": today_str(),
            })
            prev = acc
        return out
    except Exception as e:  # noqa: BLE001
        return {"error": f"fetch_fund_nav_history failed for {fund_code}: {e}", "source": SOURCE}


_INDEX_SYMBOLS = {"000300": ("沪深300", "index"),
                  "000001": ("上证指数", "index"),
                  "399001": ("深证成指", "index")}


def fetch_market_indices() -> list[dict] | dict:
    try:
        import akshare as ak
        df = with_retry(ak.stock_zh_index_spot_em)
        out = []
        for _, r in df.iterrows():
            code = str(r.get("代码", ""))
            if code in _INDEX_SYMBOLS:
                name, cat = _INDEX_SYMBOLS[code]
                out.append({
                    "symbol": code, "name": name, "category": cat,
                    "close": float(r["最新价"]),
                    "change_pct": float(r["涨跌幅"]),
                    "market_date": today_str(), "source": SOURCE,
                })
        return out
    except Exception as e:  # noqa: BLE001
        return {"error": f"fetch_market_indices failed: {e}", "source": SOURCE}