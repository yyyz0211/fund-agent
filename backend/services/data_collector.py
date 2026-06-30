"""AKShare 数据源封装。

设计要点:
- `with_retry` 是一个通用的指数退避重试包装,默认 3 次,每次延迟
  翻倍。`sleep` 参数可注入,让单测不用真等。
- 所有 `fetch_*` 都遵循"成功 → 业务字典 / 失败 → `{"error", ...}`
  二选一"的契约,这样上层 service 和 tool 不必处理异常,
  只需要判断有没有 `error` 键。
- AKShare 列名为中文,偶尔会改名;每个 parse 都包在 try/except
  里,失败时返回错误字典。联网路径的"正确性"由
  `scripts/smoke_fetch.py` 在真实环境下验证,不在单测里。
"""
import time
from datetime import date

SOURCE = "akshare"


def today_str() -> str:
    """今天日期的 ISO 字符串(YYYY-MM-DD),用于给结果打 `as_of` 戳。"""
    return date.today().isoformat()


def with_retry(fn, *args, retries: int = 3, base_delay: float = 0.5,
               sleep=time.sleep, **kwargs):
    """以指数退避策略重试调用 `fn`,最后一次失败时原样抛出。

    Args:
        fn: 被调用的可调用对象,任意参数。
        retries: 最大尝试次数(默认 3)。
        base_delay: 第一次重试前的等待秒数,之后每次翻倍。
        sleep: 可注入的 sleep,测试中传入 `lambda _: None` 即可。
    """
    last = None
    for attempt in range(retries):
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001 — collector 边界异常,在下方重抛
            last = e
            if attempt < retries - 1:
                sleep(base_delay * (2 ** attempt))
    raise last


def fetch_fund_info(fund_code: str) -> dict:
    """拉取一只基金的基础信息(名称、类型、经理、基金公司)。

    成功:返回 `{fund_code, fund_name, fund_type, manager, company,
    source, as_of}`;失败:返回 `{error, source}`。
    """
    try:
        import akshare as ak
        df = with_retry(ak.fund_individual_info_em, fund_code)
        # 新老版本的 AKShare 列名不同,两种方式都兼容一下
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
    """拉取基金累计净值走势,返回按日期升序的列表。

    每行包含 `{nav_date, unit_nav, accumulated_nav, daily_return,
    source, source_updated_at}`。`daily_return` 在本地计算
    (因为 AKShare 给的累计净值,逐日涨跌幅由我们自己得出)。
    `unit_nav` 在 AKShare 的累计净值走势接口里拿不到,先置 None。
    """
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


# 关注的指数代码 → (中文名, 类别)。股票 spot 接口一次返回所有指数,
# 我们只保留这几个常用的。
_INDEX_SYMBOLS = {"000300": ("沪深300", "index"),
                  "000001": ("上证指数", "index"),
                  "399001": ("深证成指", "index")}


def fetch_market_indices() -> list[dict] | dict:
    """拉取主要指数当日行情,过滤出我们关注的指数。

    返回:`[{"symbol", "name", "category", "close", "change_pct",
    "market_date", "source"}]`。失败返回错误字典。
    """
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