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
import signal
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import date
import re
import threading

import akshare as ak
import logging
from backend.config.settings import get_settings
_logger = logging.getLogger(__name__)

def _log_empty(field: str, reason: str) -> None:
    """fetch_* 返回 [] 的统一日志入口。

    旧实现 silent-pass 把"akshare 列名变了/接口挂了"和"真实无数据"混在一起,
    排查时无法区分。统一走 warning 级别一条 stderr。
    """
    _logger.warning("data_collector: %s empty (%s)", field, reason)


SOURCE = "akshare"
_PROFILE_FETCH_WORKERS = 3
_PROFILE_SOURCE_TIMEOUT_SECONDS = 5.0
_SINA_SCALE_CATEGORIES = ("股票型基金", "混合型基金", "债券型基金", "QDII基金", "货币型基金")


# 全局串行化锁 — 防止 libmini_racer.dylib (akshare 内嵌 V8) 的 worker pool race。
# 根因: 多个线程同时调 ak.* 时,
#   `address_pool_manager.cc(67) Check failed: !pool->IsInitialized()` 会让 uvicorn 进程崩。
# 所有 fetch_* 函数都包了此锁, 任意时刻最多一个线程进入 akshare (即 mini_racer)。
AKSHARE_LOCK = threading.Lock()


def _akshare_serial(fn):
    """装饰器: 在 fn 入口拿 AKSHARE_LOCK, 退出释放。"""
    def wrapper(*args, **kwargs):
        with AKSHARE_LOCK:
            return fn(*args, **kwargs)
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


def today_str() -> str:
    """今天日期的 ISO 字符串(YYYY-MM-DD),用于给结果打 `as_of` 戳。"""
    return date.today().isoformat()


def with_retry(fn, *args, retries: int = 3, base_delay: float = 0.5,
               sleep=time.sleep, timeout: float | None = None, **kwargs):
    """以指数退避策略重试调用 `fn`,最后一次失败时原样抛出。

    Args:
        fn: 被调用的可调用对象,任意参数。
        retries: 最大尝试次数(默认 3)。
        base_delay: 第一次重试前的等待秒数,之后每次翻倍。
        sleep: 可注入的 sleep,测试中传入 `lambda _: None` 即可。
        timeout: 单次调用的秒数上限。None = 不超时(向后兼容)。
                 设为正数后,通过 signal.SIGALRM 强制终止长时间挂起的 HTTP 调用,
                 避免 akshare 卡死时 collect_market_intel 阻塞 60s+。
    """
    if timeout is not None and timeout > 0:
        return _with_retry_and_timeout(
            fn, *args, retries=retries, base_delay=base_delay,
            sleep=sleep, timeout=timeout, **kwargs,
        )
    last = None
    for attempt in range(retries):
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001 — collector 边界异常,在下方重抛
            last = e
            if attempt < retries - 1:
                sleep(base_delay * (2 ** attempt))
    raise last


def _with_retry_and_timeout(fn, *args, retries, base_delay, sleep, timeout, **kwargs):
    """with_retry 的 SIGALRM timeout 版本。macOS/Linux 兼容(Windows 不支持)。"""
    def _handler(signum, frame):
        raise TimeoutError(f"{getattr(fn, '__name__', 'fn')} timeout after {timeout}s")

    last: Exception | None = None
    for attempt in range(retries):
        old = signal.signal(signal.SIGALRM, _handler)
        # `setitimer` 比 `alarm` 支持小数秒
        signal.setitimer(signal.ITIMER_REAL, timeout)
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001
            last = e
            if attempt < retries - 1:
                sleep(base_delay * (2 ** attempt))
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, old)
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


@_akshare_serial
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


@_akshare_serial
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


def _normalize_index_symbol(symbol: str) -> str:
    """把 6 位指数代码转成 akshare 需要的带前缀格式。

    规则(根据 akshare 实测):
    - 上证综指 ``000001``、沪深300 ``000300`` 等 → ``sh``(0 开头但属于上交所的指数)
    - 深证成指 ``399001`` 等 → ``sz``
    - 北交所 ``8xx`` / ``4xx`` → ``bj``
    - 已带前缀的格式则原样返回
    """
    s = (symbol or "").strip().lower()
    if not s:
        return s
    if s[:2] in ("sh", "sz", "bj"):
        return s
    # akshare 实测:0 开头但属于上交所指数(如 000001/000300);3 开头才是深证
    if s.startswith("3"):
        return f"sz{s}"
    if s.startswith("0"):
        return f"sh{s}"
    if s.startswith(("8", "4")):
        return f"bj{s}"
    return s


@_akshare_serial
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


@_akshare_serial
def fetch_index_history(symbol: str, days: int = 30) -> list[dict] | dict:
    """拉取某指数近 N 个交易日的日级序列(升序)。

    用于前端 sparkline: 返回精简后的 ``[{"date", "close", "source"}]``
    列表,长度 <= ``days``。日期格式 ``YYYY-MM-DD``。

    使用 ``ak.stock_zh_index_daily(symbol=...)`` 拉日线,失败时返回
    错误字典(同其他 ``fetch_*`` 约定)。

    Symbol 接受不带前缀的 6 位代码(如 ``"000001"``),内部会按
    沪/深/北自动加 ``sh``/``sz``/``bj`` 前缀。
    """
    full_symbol = _normalize_index_symbol(symbol)
    try:
        # 单次 timeout 取自 settings.market_index_history_timeout_seconds:
        # collect_market_intel 会为每个 index 调一次,30+ 个 industry/concept
        # history × 无 timeout = 整个 refresh 卡 60s+。
        df = with_retry(
            ak.stock_zh_index_daily,
            symbol=full_symbol,
            timeout=get_settings().market_index_history_timeout_seconds,
        )
        if df is None or getattr(df, "empty", True):
            return {"error": f"fetch_index_history empty for {symbol}", "source": SOURCE}
        date_col = _find_col(df, "date", "日期")
        close_col = _find_col(df, "close", "收盘", "收盘价", "最新价")
        if date_col is None or close_col is None:
            return {"error": f"fetch_index_history cols miss for {symbol}: "
                              f"date={date_col} close={close_col}", "source": SOURCE}
        rows = list(df[[date_col, close_col]].to_dict("records"))
        rows = [r for r in rows if not _is_missing(r.get(date_col)) and not _is_missing(r.get(close_col))]
        rows.sort(key=lambda r: str(r[date_col]))
        rows = rows[-days:]
        out: list[dict] = []
        for r in rows:
            close = _to_float(r[close_col])
            if close is None:
                continue
            d = str(r[date_col])
            if len(d) >= 10:
                d = d[:10]
            out.append({"date": d, "close": close, "source": SOURCE})
        if not out:
            return {"error": f"fetch_index_history no rows for {symbol}", "source": SOURCE}
        return out
    except Exception as e:  # noqa: BLE001
        return {"error": f"fetch_index_history failed for {symbol}: {e}", "source": SOURCE}


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


def _to_flow_yi(value, col_name: str | None = None) -> float | None:
    """把资金流字段统一成“亿元”。

    AKShare 不同接口的资金流列有的直接是“亿”,有的是“万元”;没有单位时
    沿用当前市场快照契约,按“亿”处理。
    """
    if _is_missing(value):
        return None

    unit_hint = f"{col_name or ''} {value}"
    text = str(value).strip()
    for token in (",", "亿元人民币", "亿元", "亿份", "亿", "万元", "万", "元", "%"):
        text = text.replace(token, "")
    try:
        n = float(text)
    except ValueError:
        return None

    if "亿" in unit_hint:
        return n
    if "万" in unit_hint:
        return n / 10000
    if "元" in unit_hint:
        return n / 100000000
    return n


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
    has_code_col = False
    for _, row in df.iterrows():
        for col in code_cols:
            if col in row:
                has_code_col = True
                if _norm_code(row.get(col)) == fund_code:
                    return row
    if len(df) == 1 and not has_code_col:
        return next(df.iterrows())[1]
    return None


def _parse_scale_frame(fund_code: str, df) -> dict:
    row = _find_code_row(df, fund_code)
    if row is None:
        return {"scale": None, "scale_date": None}
    return {
        "scale": _to_float(_pick(
            row,
            "基金规模", "基金规模(亿元)", "基金规模(亿)",
            "期末净资产", "净资产", "规模", "最新规模", "份额规模",
        )),
        "scale_date": str(_pick(row, "截止日期", "报告期", "日期", "更新日期") or "") or None,
    }


def _rank_parts(value) -> tuple[int | None, int | None]:
    """解析组合排名字段,例如 `25/100`、`25 | 100`、`第25名/共100只`。"""
    if _is_missing(value):
        return None, None
    text = str(value).replace(",", "").strip()
    nums = [int(x) for x in re.findall(r"\d+", text)]
    if not nums:
        return None, None
    if len(nums) >= 2:
        return nums[0], nums[1]
    return nums[0], None


def _rank_position(row) -> int | None:
    value = _pick(
        row,
        "同类排名", "排名", "近1年同类排名", "近1年排名", "今年来排名",
        "近一年排名", "近1年同类排名走势", "近1年排名走势",
    )
    direct = _to_int(value)
    if direct is not None:
        return direct
    position, _total = _rank_parts(value)
    return position


def _rank_total(row) -> int | None:
    direct = _to_int(_pick(
        row,
        "同类总数", "总数", "近1年同类总数", "今年来同类总数",
        "近一年同类总数",
    ))
    if direct is not None:
        return direct
    _position, total = _rank_parts(_pick(
        row,
        "同类排名", "排名", "近1年同类排名", "近1年排名", "今年来排名",
        "近一年排名", "近1年同类排名走势", "近1年排名走势",
    ))
    return total


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


def _fetch_scale_from_sina(fund_code: str) -> tuple[dict, list[str]]:
    """用新浪开放式基金规模做低频 fallback。返回规模结果和错误列表。"""
    errors: list[str] = []
    for category in _SINA_SCALE_CATEGORIES:
        try:
            df = _call_with_typeerror_fallback(ak.fund_scale_open_sina, symbol=category)
            parsed = _parse_scale_frame(fund_code, df)
            if parsed.get("scale") is not None:
                return parsed, errors
        except Exception as exc:  # noqa: BLE001
            errors.append(f"scale fallback {category} failed: {exc}")
    return {"scale": None, "scale_date": None}, errors


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


@_akshare_serial
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
        scale_payload = _parse_scale_frame(fund_code, frames.get("scale"))
        if scale_payload.get("scale") is None:
            fallback_payload, fallback_errors = _fetch_scale_from_sina(fund_code)
            out["errors"].extend(fallback_errors)
            if fallback_payload.get("scale") is not None:
                scale_payload = fallback_payload
        out.update(scale_payload)
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


# ---------------------------------------------------------------------------
# 市场宽度采集（涨跌家数 / 涨跌停 / 成交额）
# ---------------------------------------------------------------------------

@_akshare_serial
def fetch_market_breadth() -> dict:
    """拉取今日 A 股市场宽度指标。

    调用 ``akshare.stock.stock_market_activity_legu()`` 获取涨跌家数/涨跌停。

    非交易日该接口可能返回空 DataFrame 或关键 key 缺失,此时 ``up + down == 0``。
    前端依赖 ``stale`` 字段区分"全 0 = 数据不可用"与"真无交易"。

    成功返回:
        {
            "up": int, "down": int, "limit_up": int, "limit_down": int,
            "volume": float（亿元）, "amount": float（亿元）,
            "total": int, "source": "akshare", "as_of": "YYYY-MM-DD",
            "stale": bool  # True 表示数据不可信(接口空 / 关键列缺失 / 全 0)
        }
    失败返回: {"error": str, "source": str}
    """
    try:
        df = ak.stock_market_activity_legu()
        if df is None or getattr(df, "empty", True) or len(df) == 0:
            return _empty_breadth(SOURCE)

        # 转换为 dict: item=行标签, value=数值
        kv = dict(zip(df["item"], df["value"]))

        def _num(key, default=0.0):
            val = kv.get(key)
            if val is None:
                return default
            try:
                return float(val)
            except (TypeError, ValueError):
                return default

        up = int(_num("上涨"))
        down = int(_num("下跌"))
        limit_up = int(_num("涨停"))
        limit_down = int(_num("跌停"))
        total = up + down

        # 活跃度统计日期
        as_of = str(kv.get("统计日期", ""))[:10]
        if as_of == "":
            as_of = today_str()

        # staleness 标记:
        # - 关键 key 缺失(无法信任数值)
        # - up + down == 0(可能非交易日真没数据,也可能是接口静默失败)
        missing_keys = any(k not in kv for k in ("上涨", "下跌", "涨停", "跌停"))
        stale = missing_keys or total == 0

        return {
            "up": up,
            "down": down,
            "limit_up": limit_up,
            "limit_down": limit_down,
            "volume": 0.0,  # stock_market_activity_legu 不含成交额
            "amount": 0.0,
            "total": total,
            "source": SOURCE,
            "as_of": as_of,
            "stale": stale,
        }
    except Exception as e:  # noqa: BLE001
        return {"error": f"fetch_market_breadth failed: {e}", "source": SOURCE,
                "stale": True, "stale_reason": "exception"}


def _empty_breadth(source: str) -> dict:
    """接口返回空 DataFrame 时使用,明确标记 ``stale=True``。"""
    return {"up": 0, "down": 0, "limit_up": 0, "limit_down": 0,
            "volume": 0.0, "amount": 0.0, "total": 0, "source": source,
            "as_of": today_str(), "stale": True, "stale_reason": "empty_dataframe"}


def _find_col(df, *names) -> str | None:
    """在 DataFrame 列中查找第一个存在的列名。"""
    for name in names:
        if name in df.columns:
            return name
    return None


# ---------------------------------------------------------------------------
# 板块涨跌快照
# ---------------------------------------------------------------------------

@_akshare_serial
def fetch_sector_snapshot(limit_n: int = 10) -> list[dict]:
    """拉取今日行业板块涨跌幅，取 top-N + bottom-N。

    使用 ``akshare.stock.stock_board_industry_summary_ths()`` 拉申万行业实时行情，
    按涨跌幅排序取强势 / 弱势各若干。

    非交易日可能返回少量数据或空列表，此时返回空列表。

    成功返回:
        [{"name": str, "change_pct": float, "source": "akshare"}, ...]
    失败返回: []
    """
    try:
        df = ak.stock_board_industry_summary_ths()
        if df is None or getattr(df, "empty", True) or len(df) == 0:
            return []

        name_col = "板块"
        change_col = "涨跌幅"

        if name_col not in df.columns or change_col not in df.columns:
            return []

        rows = []
        for _, row in df.iterrows():
            try:
                name = str(row.get(name_col, "")).strip()
                change = _to_float(row.get(change_col))
                if name and change is not None:
                    rows.append({
                        "name": name,
                        "change_pct": change,
                        "source": SOURCE,
                    })
            except Exception:  # noqa: BLE001
                continue

        if not rows:
            return []

        rows.sort(key=lambda r: r["change_pct"], reverse=True)
        top = rows[:limit_n]
        bottom = rows[-limit_n:] if len(rows) > limit_n else []
        # 避免重复
        result = list(top)
        for b in bottom:
            if b not in result:
                result.append(b)
        return result

    except Exception:  # noqa: BLE001
        return []


@_akshare_serial
def fetch_concept_sectors(limit_n: int = 10) -> list[dict]:  # noqa: F811
    """拉取概念板块涨跌幅 top/bottom。优先使用概念板块列表接口。"""
    try:
        df = None
        errors = []
        for fn_name in ("stock_board_concept_name_em", "stock_board_concept_spot_em", "stock_fund_flow_concept"):
            fn = getattr(ak, fn_name, None)
            if fn is None:
                errors.append(f"{fn_name}=missing")
                continue
            try:
                candidate = fn(symbol="即时") if fn_name == "stock_fund_flow_concept" else fn()
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{fn_name}={type(exc).__name__}: {exc}")
                continue
            if candidate is not None and not getattr(candidate, "empty", True) and len(candidate) > 0:
                df = candidate
                break

        if df is None or getattr(df, "empty", True) or len(df) == 0:
            _log_empty("concept_sectors", "akshare empty df; " + "; ".join(errors))
            return []
        change_col = _find_col(df, "涨跌幅", "涨跌幅(%)", "涨跌幅%", "阶段涨跌幅", "行业-涨跌幅")
        name_col = _find_col(df, "板块名称", "名称", "板块", "概念名称", "概念板块", "行业")
        if change_col is None or name_col is None:
            _log_empty("concept_sectors",
                f"col miss: change={change_col} name={name_col} cols={list(df.columns)[:6]}")
            return []
        rows = []
        for _, row in df.iterrows():
            try:
                name = str(row.get(name_col, "")).strip()
                change = _to_float(row.get(change_col))
                if name and change is not None:
                    rows.append({"name": name, "change_pct": change, "source": SOURCE})
            except Exception:
                continue
        if not rows:
            _log_empty("concept_sectors", "row parse empty")
            return []
        rows.sort(key=lambda r: r["change_pct"], reverse=True)
        top = rows[:limit_n]
        bottom = rows[-limit_n:] if len(rows) > limit_n else []
        result = list(top)
        for b in bottom:
            if b not in result:
                result.append(b)
        return result
    except Exception as exc:
        _log_empty("concept_sectors", f"{type(exc).__name__}: {exc}")
        return []


@_akshare_serial
def fetch_industry_flows(limit_n: int = 10) -> list[dict]:
    """拉取行业板块资金流向（净流入 top/bottom）。来源: stock_board_industry_summary_ths()"""
    try:
        df = ak.stock_board_industry_summary_ths()
        if df is None or getattr(df, "empty", True) or len(df) == 0:
            return []
        name_col = "板块"
        flow_col = _find_col(df, "净流入", "净流入(万元)", "资金净流入")
        if name_col not in df.columns or flow_col is None:
            return []
        rows = []
        for _, row in df.iterrows():
            try:
                name = str(row.get(name_col, "")).strip()
                flow = _to_flow_yi(row.get(flow_col), flow_col)
                if name and flow is not None:
                    rows.append({"name": name, "net_flow": flow, "source": SOURCE})
            except Exception:
                continue
        if not rows:
            return []
        rows.sort(key=lambda r: r["net_flow"], reverse=True)
        top = rows[:limit_n]
        bottom = rows[-limit_n:] if len(rows) > limit_n else []
        result = list(top)
        for b in bottom:
            if b not in result:
                result.append(b)
        return result
    except Exception:
        return []


@_akshare_serial
def fetch_concept_flows(limit_n: int = 10) -> list[dict]:
    """拉取概念板块资金流向（净流入 top/bottom）。优先使用概念资金流接口。"""
    try:
        df = None
        errors = []
        for fn_name in ("stock_fund_flow_concept", "stock_board_concept_summary_ths"):
            fn = getattr(ak, fn_name, None)
            if fn is None:
                errors.append(f"{fn_name}=missing")
                continue
            try:
                candidate = fn(symbol="即时") if fn_name == "stock_fund_flow_concept" else fn()
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{fn_name}={type(exc).__name__}: {exc}")
                continue
            if candidate is not None and not getattr(candidate, "empty", True) and len(candidate) > 0:
                df = candidate
                break

        if df is None or getattr(df, "empty", True) or len(df) == 0:
            _log_empty("concept_flows", "akshare empty df; " + "; ".join(errors))
            return []
        name_col = _find_col(df, "板块", "板块名称", "概念板块", "概念名称", "行业")
        flow_col = _find_col(df, "净流入", "资金净流入", "净流入(万元)", "净额", "主力净流入", "净流入额")
        if name_col is None or flow_col is None:
            _log_empty("concept_flows",
                f"col miss: name={name_col} flow={flow_col} cols={list(df.columns)[:6]}")
            return []
        rows = []
        for _, row in df.iterrows():
            try:
                name = str(row.get(name_col, "")).strip()
                flow = _to_flow_yi(row.get(flow_col), flow_col)
                if name and flow is not None:
                    rows.append({"name": name, "net_flow": flow, "source": SOURCE})
            except Exception:
                continue
        if not rows:
            return []
        rows.sort(key=lambda r: r["net_flow"], reverse=True)
        top = rows[:limit_n]
        bottom = rows[-limit_n:] if len(rows) > limit_n else []
        result = list(top)
        for b in bottom:
            if b not in result:
                result.append(b)
        return result
    except Exception:
        return []


@_akshare_serial
def fetch_sector_history(name: str, kind: str = "industry", days: int = 10) -> list[dict] | dict:
    """拉取某行业/概念板块近 N 个交易日的日涨跌幅序列(升序)。

    用于前端 sparkline: 返回精简的
    ``[{"date", "change_pct", "source"}]``,长度 <= ``days``。
    ``change_pct`` 是接口原始值(同花顺接口 = 百分比,0.5 表示 +0.5%)。

    Args:
        name: 板块名,例如 ``"电子"`` / ``"AI算力"``。需要能映射到
            akshare 的板块指数代码;若映射失败,返回错误字典。
        kind: ``"industry"`` 或 ``"concept"``
        days: 保留尾 N 条

    失败: 返回 ``{"error", "source"}`` 字典(同其他 ``fetch_*`` 约定)。

    Note:
        ``ak.stock_board_industry_index_ths`` 需要 symbol 在它内置的
        code_map 中,且外网必须可达。生产环境若外网中断或 symbol
        不识别,本函数会返回 error 字典,调用方应降级(不画 sparkline)。
    """
    if kind not in ("industry", "concept"):
        return {"error": f"fetch_sector_history kind must be industry|concept, got {kind!r}", "source": SOURCE}
    fn = ak.stock_board_industry_index_ths if kind == "industry" else ak.stock_board_concept_index_ths
    try:
        from datetime import timedelta
        end = date.today()
        start = end - timedelta(days=max(days * 2 + 30, 60))  # 多取一些以防非交易日
        df = with_retry(fn, symbol=name,
                        start_date=start.strftime("%Y%m%d"),
                        end_date=end.strftime("%Y%m%d"),
                        timeout=get_settings().market_index_history_timeout_seconds)
        if df is None or getattr(df, "empty", True):
            return {"error": f"fetch_sector_history empty for {name} ({kind})", "source": SOURCE}
        date_col = _find_col(df, "date", "日期")
        change_col = _find_col(df, "涨跌幅", "change_pct", "涨跌幅(%)")
        if date_col is None or change_col is None:
            return {"error": f"fetch_sector_history cols miss for {name} ({kind}): "
                              f"date={date_col} change={change_col}", "source": SOURCE}
        rows = list(df[[date_col, change_col]].to_dict("records"))
        rows = [r for r in rows if not _is_missing(r.get(date_col)) and not _is_missing(r.get(change_col))]
        rows.sort(key=lambda r: str(r[date_col]))
        rows = rows[-days:]
        out: list[dict] = []
        for r in rows:
            # akshare 同花顺板块接口的"涨跌幅"是百分比(0.5 表示 +0.5%),
            # 前端 formatPctWithSign 会再 * 100,这里保持原值。
            v = _to_float(r[change_col])
            if v is None:
                continue
            d = str(r[date_col])
            if len(d) >= 10:
                d = d[:10]
            out.append({"date": d, "change_pct": v, "source": SOURCE})
        if not out:
            return {"error": f"fetch_sector_history no rows for {name} ({kind})", "source": SOURCE}
        return out
    except Exception as e:  # noqa: BLE001
        return {"error": f"fetch_sector_history failed for {name} ({kind}): {e}", "source": SOURCE}


@_akshare_serial
def fetch_theme_boards(limit_n: int = 20) -> list[dict]:
    """拉取当日涨停板，按涨停原因归类为题材。akshare: stock_zt_pool_em()"""
    try:
        df = ak.stock_zt_pool_em(date=today_str())
        if df is None or getattr(df, "empty", True) or len(df) == 0:
            return []
        reason_col = _find_col(df, "涨停统计", "涨停原因", "连板数")
        name_col = _find_col(df, "股票代码", "代码", "股票名称", "名称")
        change_col = _find_col(df, "涨跌幅")
        if name_col is None:
            return []
        # 归类: 按涨停原因（reason_col）分组
        themes: dict[str, list] = {}
        for _, row in df.iterrows():
            reason = str(row.get(reason_col, "其他")).strip() if reason_col else "其他"
            name = str(row.get(name_col, ""))
            change = _to_float(row.get(change_col)) if change_col else None
            if reason not in themes:
                themes[reason] = []
            themes[reason].append({"name": name, "change_pct": change})
        result = []
        for reason, stocks in themes.items():
            result.append({
                "theme": reason,
                "count": len(stocks),
                "stocks": stocks[:5],
                "source": SOURCE,
            })
        result.sort(key=lambda x: x["count"], reverse=True)
        return result[:limit_n]
    except Exception:
        return []


@_akshare_serial
def fetch_breadth_indicators() -> dict:
    """拉取情绪指标: 连板高度 top5。akshare: stock_zt_pool_strong_em(date=today_str())"""
    try:
        df = ak.stock_zt_pool_strong_em(date=today_str())
        board_height = []
        if df is not None and not getattr(df, "empty", True):
            name_col = _find_col(df, "名称")
            board_col = _find_col(df, "连板数")
            if name_col and board_col:
                for _, row in df.head(5).iterrows():
                    try:
                        name = str(row.get(name_col, ""))
                        boards = _to_float(row.get(board_col))
                        if name and boards is not None:
                            board_height.append({"name": name, "boards": boards})
                    except Exception:
                        continue
        return {"board_height": board_height, "source": SOURCE, "as_of": today_str()}
    except Exception:
        return {"board_height": [], "source": SOURCE, "as_of": today_str()}


@_akshare_serial
def fetch_overseas_markets() -> list[dict]:
    """拉取外围市场: 美股主要指数 + 港股 + 国内油价。akshare: index_global_hist_sina() + energy_oil_hist()"""
    result = []
    targets = [
        ("US", "纳斯达克综合指数", "IXIC"),
        ("US", "标普500指数", "SPX"),
        ("HK", "恒生指数", "HSI"),
    ]
    for market, name, symbol in targets:
        try:
            df = ak.index_global_hist_sina(symbol=symbol, period="daily",
                                          start_date="20260701", end_date="20260707")
            if df is not None and not getattr(df, "empty", True):
                last = df.iloc[-1]
                close_col = _find_col(df, "收盘", "收盘价", "收盘指数")
                change_col = _find_col(df, "涨跌幅")
                if close_col:
                    result.append({
                        "market": market, "name": name, "symbol": symbol,
                        "close": _to_float(last.get(close_col)),
                        "change_pct": _to_float(last.get(change_col)) if change_col else None,
                        "source": SOURCE, "as_of": today_str(),
                    })
        except Exception:
            continue
    # 国内油价
    try:
        oil_df = ak.energy_oil_hist()
        if oil_df is not None and not getattr(oil_df, "empty", True):
            last = oil_df.iloc[-1]
            result.append({
                "market": "COMMODITY", "name": "国内汽油均价", "symbol": "GASOLINE",
                "close": _to_float(last.get("汽油价格")),
                "change_pct": _to_float(last.get("汽油涨跌")),
                "source": SOURCE, "as_of": today_str(),
            })
    except Exception:
        pass
    return result


@_akshare_serial
def fetch_announcements(limit: int = 50) -> list[dict]:
    """拉取近 N 天基金重要公告。akshare: fund_announcement_dividend_em(symbol=fund_code)"""
    try:
        from backend.db.session import get_session
        from backend.db.models import Watchlist
        from sqlalchemy import select
        s = get_session()
        try:
            codes = [r.fund_code for r in s.scalars(select(Watchlist.fund_code)).all()]
        finally:
            s.close()
        rows = []
        for code in codes[:20]:
            try:
                div_df = ak.fund_announcement_dividend_em(symbol=code)
                if div_df is not None and not getattr(div_df, "empty", True):
                    title_col = _find_col(div_df, "公告标题")
                    date_col = _find_col(div_df, "公告日期")
                    name_col = _find_col(div_df, "基金名称")
                    if title_col and date_col:
                        for _, row in div_df.head(3).iterrows():
                            title = str(row.get(title_col, "")).strip()
                            ann_date = str(row.get(date_col, ""))[:10]
                            fund_name = str(row.get(name_col, code))
                            if title and len(title) > 5:
                                rows.append({
                                    "title": title, "ann_date": ann_date,
                                    "fund_code": code, "fund_name": fund_name,
                                    "source": SOURCE,
                                })
            except Exception:
                continue
        rows.sort(key=lambda x: x["ann_date"], reverse=True)
        return rows[:limit]
    except Exception:
        return []
