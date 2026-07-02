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
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import date

import akshare as ak

SOURCE = "akshare"
_PROFILE_FETCH_WORKERS = 3
_PROFILE_SOURCE_TIMEOUT_SECONDS = 5.0


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


def _parse_xq_fund_info(fund_code: str, df) -> dict:
    """解析雪球基金基础信息 DataFrame。"""
    kv = dict(zip(df["item"], df["value"]))
    return {
        "fund_code": fund_code,
        "fund_name": kv.get("基金名称") or kv.get("基金简称"),
        "fund_type": kv.get("基金类型"),
        "manager": kv.get("基金经理"),
        "company": kv.get("基金公司"),
        "source": SOURCE,
        "as_of": today_str(),
    }


def _parse_ths_fund_info(fund_code: str, df) -> dict:
    """解析同花顺基金基础信息 DataFrame。"""
    kv = dict(zip(df["字段"], df["值"]))
    return {
        "fund_code": fund_code,
        "fund_name": kv.get("基金简称") or kv.get("基金名称"),
        "fund_type": kv.get("投资类型") or kv.get("基金类型"),
        "manager": kv.get("基金经理"),
        "company": kv.get("基金管理人") or kv.get("基金公司"),
        "source": SOURCE,
        "as_of": today_str(),
    }


def fetch_fund_info(fund_code: str) -> dict:
    """拉取一只基金的基础信息(名称、类型、经理、基金公司)。

    AKShare 1.18 已经把老的 `fund_individual_info_em` 移除了,改用雪球
    的 `fund_individual_basic_info_xq`;当雪球拒服或列结构变化时,再 fallback
    到同花顺 `fund_info_ths`。

    成功:返回 `{fund_code, fund_name, fund_type, manager, company,
    source, as_of}`;失败:返回 `{error, source}`。
    """
    try:
        df = with_retry(ak.fund_individual_basic_info_xq, symbol=fund_code)
        return _parse_xq_fund_info(fund_code, df)
    except Exception as xq_error:  # noqa: BLE001
        try:
            df = with_retry(ak.fund_info_ths, symbol=fund_code)
            return _parse_ths_fund_info(fund_code, df)
        except Exception as ths_error:  # noqa: BLE001
            return {
                "error": (
                    f"fetch_fund_info failed for {fund_code}: "
                    f"xq={xq_error}; ths={ths_error}"
                ),
                "source": SOURCE,
            }


def fetch_fund_nav_history(fund_code: str) -> list[dict] | dict:
    """拉取基金净值走势,返回按日期升序的列表。

    AKShare 1.18 的 `fund_open_fund_info_em` 在 `indicator="累计净值走势"`
    下只返回 `净值日期` / `累计净值` 两列,`单位净值走势` 才有
    `单位净值` / `日增长率`。我们两次调用后按 `净值日期` 拼接,
    把 `unit_nav` 填上;`daily_return` 在本地用累计净值算
    (因为源接口的 `日增长率` 是字符串,本地算更稳)。
    """
    try:
        acc_df = with_retry(ak.fund_open_fund_info_em, fund_code,
                            indicator="累计净值走势")
        unit_df = with_retry(ak.fund_open_fund_info_em, fund_code,
                             indicator="单位净值走势")
        unit_by_date = dict(zip(unit_df["净值日期"], unit_df["单位净值"]))
        out = []
        prev = None
        for _, r in acc_df.iterrows():
            acc = float(r["累计净值"])
            dr = (acc / prev - 1) if prev not in (None, 0) else 0.0
            out.append({
                "nav_date": str(r["净值日期"]),
                "unit_nav": float(unit_by_date[str(r["净值日期"])])
                            if str(r["净值日期"]) in unit_by_date else None,
                "accumulated_nav": acc,
                "daily_return": dr,
                "source": SOURCE,
                "source_updated_at": today_str(),
            })
            prev = acc
        return out
    except Exception as e:  # noqa: BLE001
        return {"error": f"fetch_fund_nav_history failed for {fund_code}: {e}",
                "source": SOURCE}


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


def _is_missing(value) -> bool:
    if value is None:
        return True
    try:
        if value != value:
            return True
    except Exception:  # noqa: BLE001
        pass
    return str(value).strip() in {"", "-", "--", "nan", "NaN", "None"}


def _norm_code(value) -> str:
    if _is_missing(value):
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 6:
        return digits[:6]
    if digits:
        return digits.zfill(6)
    return text


def _pick(row, *keys):
    for key in keys:
        if key in row and not _is_missing(row.get(key)):
            return row.get(key)
    return None


def _to_float(value) -> float | None:
    if _is_missing(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    for token in (",", "亿元", "亿份", "亿元人民币", "亿", "%"):
        text = text.replace(token, "")
    try:
        return float(text)
    except ValueError:
        return None


def _to_int(value) -> int | None:
    n = _to_float(value)
    return int(n) if n is not None else None


def _to_ratio(value) -> float | None:
    if _is_missing(value):
        return None
    has_percent = isinstance(value, str) and "%" in value
    n = _to_float(value)
    if n is None:
        return None
    if has_percent or abs(n) > 1:
        return n / 100
    return n


def _find_code_row(df, fund_code: str):
    if df is None or getattr(df, "empty", False):
        return None
    code_cols = ("基金代码", "代码", "fund_code")
    for _, row in df.iterrows():
        for col in code_cols:
            if col in row and _norm_code(row.get(col)) == fund_code:
                return row
    if len(df) == 1:
        return next(df.iterrows())[1]
    return None


def _parse_scale_frame(fund_code: str, df) -> dict:
    row = _find_code_row(df, fund_code)
    if row is None:
        return {"scale": None, "scale_date": None}
    return {
        "scale": _to_float(_pick(row, "基金规模", "期末净资产", "净资产", "规模")),
        "scale_date": str(_pick(row, "截止日期", "报告期", "日期") or "") or None,
    }


def _rank_position(row) -> int | None:
    return _to_int(_pick(row, "同类排名", "排名", "近1年同类排名", "近1年排名", "今年来排名"))


def _rank_total(row) -> int | None:
    return _to_int(_pick(row, "同类总数", "总数", "近1年同类总数", "今年来同类总数"))


def _peer_category(row) -> str | None:
    value = _pick(row, "基金类型", "基金类别", "类型", "分类")
    return str(value) if value is not None else None


def _parse_rank_frame(fund_code: str, df) -> dict:
    row = _find_code_row(df, fund_code)
    if row is None:
        return {
            "peer_category": None,
            "rank_total": None,
            "rank_position": None,
            "peer_candidates": [],
        }
    category = _peer_category(row)
    peers = []
    if df is not None and not getattr(df, "empty", False):
        for _, peer_row in df.iterrows():
            code = _norm_code(_pick(peer_row, "基金代码", "代码", "fund_code"))
            if not code or code == fund_code:
                continue
            peer_type = _peer_category(peer_row)
            if category and peer_type and peer_type != category:
                continue
            name = _pick(peer_row, "基金简称", "基金名称", "名称", "fund_name")
            rank = _rank_position(peer_row)
            peers.append({
                "fund_code": code,
                "fund_name": str(name) if name is not None else None,
                "fund_type": peer_type or category,
                "rank_position": rank,
            })
    peers.sort(key=lambda item: item["rank_position"] if item["rank_position"] is not None else 10**9)
    return {
        "peer_category": category,
        "rank_total": _rank_total(row),
        "rank_position": _rank_position(row),
        "peer_candidates": peers[:5],
    }


def _parse_holdings_frame(df) -> float | None:
    if df is None or getattr(df, "empty", False):
        return None
    ratios = []
    for _, row in df.head(10).iterrows():
        ratio = _to_ratio(_pick(row, "占净值比例", "持仓占比", "市值占基金资产净值比例"))
        if ratio is not None:
            ratios.append(ratio)
    return sum(ratios) if ratios else None


def _parse_industry_frame(df) -> float | None:
    if df is None or getattr(df, "empty", False):
        return None
    ratios = []
    for _, row in df.iterrows():
        ratio = _to_ratio(_pick(row, "占净值比例", "占比", "净值比例"))
        if ratio is not None:
            ratios.append(ratio)
    return max(ratios) if ratios else None


def _parse_manager_frame(fund_code: str, df) -> str | None:
    row = _find_code_row(df, fund_code)
    if row is None:
        return None
    manager = _pick(row, "基金经理", "姓名", "基金经理姓名")
    if manager is None:
        return None
    parts = [str(manager)]
    start_date = _pick(row, "任职日期", "开始管理时间", "上任日期")
    if start_date is not None:
        parts.append(f"任职日期:{start_date}")
    return " ".join(parts)


def _profile_year() -> str:
    return str(date.today().year - 1)


def _call_with_typeerror_fallback(fn, *args, **kwargs):
    try:
        return with_retry(fn, *args, **kwargs)
    except TypeError:
        return with_retry(fn)


def _collect_profile_frames(fund_code: str) -> tuple[dict, list[str], list[str]]:
    year = _profile_year()
    calls = {
        "scale": lambda: with_retry(ak.fund_scale_change_em),
        "rank": lambda: _call_with_typeerror_fallback(ak.fund_open_fund_rank_em, symbol="全部"),
        "holdings": lambda: _call_with_typeerror_fallback(
            ak.fund_portfolio_hold_em, symbol=fund_code, date=year,
        ),
        "industry": lambda: _call_with_typeerror_fallback(
            ak.fund_portfolio_industry_allocation_em, symbol=fund_code, date=year,
        ),
        "manager": lambda: with_retry(ak.fund_manager_em),
    }
    executor = ThreadPoolExecutor(max_workers=_PROFILE_FETCH_WORKERS)
    futures = {key: executor.submit(call) for key, call in calls.items()}
    frames: dict[str, object] = {}
    missing: list[str] = []
    errors: list[str] = []
    try:
        for key, future in futures.items():
            try:
                frames[key] = future.result(timeout=_PROFILE_SOURCE_TIMEOUT_SECONDS)
            except TimeoutError:
                missing.append(key)
                errors.append(f"{key} timeout")
            except Exception as exc:  # noqa: BLE001
                missing.append(key)
                errors.append(f"{key} failed: {exc}")
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    return frames, missing, errors


def fetch_fund_profile(fund_code: str) -> dict:
    """拉取基金体检增强画像。

    这些字段都是可选增强,所以单个 AkShare 源失败不会让整次采集失败。
    调用方应把 `missing_data` 展示给用户,并继续使用本地 NAV/metrics
    生成低置信度诊断。
    """
    frames, missing_data, errors = _collect_profile_frames(fund_code)
    out = {
        "fund_code": fund_code,
        "scale": None,
        "scale_date": None,
        "peer_category": None,
        "rank_total": None,
        "rank_position": None,
        "peer_candidates": [],
        "top10_holding_pct": None,
        "top_industry_pct": None,
        "manager_summary": None,
        "missing_data": list(dict.fromkeys(missing_data)),
        "errors": errors,
        "source": SOURCE,
        "as_of": today_str(),
    }

    try:
        out.update(_parse_scale_frame(fund_code, frames.get("scale")))
    except Exception as exc:  # noqa: BLE001
        out["errors"].append(f"scale parse failed: {exc}")
        out["missing_data"].append("scale")

    try:
        out.update(_parse_rank_frame(fund_code, frames.get("rank")))
    except Exception as exc:  # noqa: BLE001
        out["errors"].append(f"rank parse failed: {exc}")
        out["missing_data"].extend(["rank", "peers"])

    try:
        out["top10_holding_pct"] = _parse_holdings_frame(frames.get("holdings"))
    except Exception as exc:  # noqa: BLE001
        out["errors"].append(f"holdings parse failed: {exc}")
        out["missing_data"].append("holdings")

    try:
        out["top_industry_pct"] = _parse_industry_frame(frames.get("industry"))
    except Exception as exc:  # noqa: BLE001
        out["errors"].append(f"industry parse failed: {exc}")
        out["missing_data"].append("industry")

    try:
        out["manager_summary"] = _parse_manager_frame(fund_code, frames.get("manager"))
    except Exception as exc:  # noqa: BLE001
        out["errors"].append(f"manager parse failed: {exc}")
        out["missing_data"].append("manager")

    if out["scale"] is None:
        out["missing_data"].append("scale")
    if out["rank_position"] is None or out["rank_total"] is None:
        out["missing_data"].append("rank")
    if not out["peer_candidates"]:
        out["missing_data"].append("peers")
    if out["top10_holding_pct"] is None:
        out["missing_data"].append("holdings")
    if out["top_industry_pct"] is None:
        out["missing_data"].append("industry")
    if out["manager_summary"] is None:
        out["missing_data"].append("manager")

    out["missing_data"] = list(dict.fromkeys(out["missing_data"]))
    return out
