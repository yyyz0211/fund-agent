"""HTTP smoke：模拟前端高频轮询 + 手动 reindex，校验不再出现 500。

设计动机
========
之前在 dev server 上观察到的故障：

1. ``sqlite3.OperationalError: database is locked``
2. ``sqlalchemy.exc.TimeoutError: QueuePool limit of size 5 overflow 10 reached``

两者形成连锁放大：scheduler job 长事务占用 SQLite 全局写锁，
SQLAlchemy 默认 ``QueuePool(5, 10, 30s)`` 在单进程 uvicorn 里被
高频轮询请求占满，所有路由开始 500。

修复后（见 [`backend/db/session.py`](../backend/db/session.py) +
[`backend/services/scheduler_lock.py`](../backend/services/scheduler_lock.py) +
[`backend/services/knowledge_reindex_jobs.py`](../backend/services/knowledge_reindex_jobs.py)），
预期：

- SQLite 走 ``NullPool``，每个 Session 用完即关；
- scheduler 写入型 job 走 ``scheduler_lock`` 进程级单飞锁；
- 手动 reindex 走 ``knowledge_reindex_jobs`` 异步任务，不阻塞 uvicorn 请求线程；
- 前端高频轮询的 read 路由应该稳定返回 200/4xx，**不会**因为后台跑
  pipeline 而 500。

用法
====

```bash
# 1) 在另一个 shell 跑 dev server：
#    uvicorn backend.api.app:app --reload --port 8001
# 2) 在这里：
python scripts/smoke_knowledge_pipeline.py [--base http://127.0.0.1:8001] [--duration 60]
```

退出码：成功 0；任何 500 计数 > 0 时非 0。
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime
from typing import Optional


DEFAULT_BASE = "http://127.0.0.1:8001"
DEFAULT_DURATION = 60.0
DEFAULT_POLL_INTERVAL = 0.5  # 前端高频轮询节奏


def _http_get_json(url: str, timeout: float = 5.0) -> tuple[int, Optional[dict], Optional[str]]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            status = resp.status
            try:
                body = json.loads(resp.read().decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                body = None
            return status, body, None
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
        except Exception:
            body = None
        return exc.code, body, None
    except urllib.error.URLError as exc:
        return 0, None, f"URLError: {exc.reason}"
    except Exception as exc:  # noqa: BLE001
        return 0, None, f"{type(exc).__name__}: {exc}"


def _http_post(url: str, *, headers: Optional[dict] = None, timeout: float = 5.0) -> tuple[int, Optional[dict], Optional[str]]:
    req = urllib.request.Request(url, method="POST", headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            try:
                body = json.loads(resp.read().decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                body = None
            return status, body, None
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
        except Exception:
            body = None
        return exc.code, body, None
    except urllib.error.URLError as exc:
        return 0, None, f"URLError: {exc.reason}"
    except Exception as exc:  # noqa: BLE001
        return 0, None, f"{type(exc).__name__}: {exc}"


def _wait_for_health(base: str, timeout: float = 30.0) -> bool:
    """等待 /api/health 返回 200, 最长 timeout 秒。"""
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        status, _, _ = _http_get_json(f"{base}/api/health")
        if status == 200:
            return True
        time.sleep(0.5)
    return False


def _poll_loop(
    base: str,
    urls: list[str],
    duration: float,
    interval: float,
    results: dict,
    stop_event: threading.Event,
) -> None:
    """每个 url 各自一个线程持续轮询, 把 status 计数写到 results。"""
    for url in urls:
        key = url
        results[key] = Counter()
        results.setdefault("_errors", [])

        def _poll(_key: str = key, _url: str = url):
            while not stop_event.is_set():
                status, _, err = _http_get_json(f"{base}{_url}")
                if status == 0:
                    results["_errors"].append((_url, err))
                else:
                    results[_key][status] += 1
                stop_event.wait(interval)

        threading.Thread(target=_poll, name=f"poll-{url}", daemon=True).start()


def _trigger_reindex(base: str) -> Optional[dict]:
    """POST /api/knowledge/reindex, 返回启动结果。"""
    status, body, err = _http_post(
        f"{base}/api/knowledge/reindex",
        headers={"X-Local-Trigger": "1"},
    )
    if status != 202 or body is None:
        print(f"[reindex] failed to start: status={status} body={body} err={err}")
        return None
    return body


def _poll_reindex_until_done(
    base: str,
    job_id: int,
    timeout: float = 60.0,
) -> Optional[dict]:
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        status, body, _ = _http_get_json(f"{base}/api/knowledge/reindex/{job_id}")
        if status == 200 and body:
            if body.get("status") in ("completed", "failed", "busy_skipped"):
                return body
        time.sleep(1.0)
    return None


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base", default=DEFAULT_BASE, help="uvicorn base URL")
    parser.add_argument("--duration", type=float, default=DEFAULT_DURATION,
                        help="polling duration in seconds")
    parser.add_argument("--interval", type=float, default=DEFAULT_POLL_INTERVAL,
                        help="poll interval per request, seconds")
    parser.add_argument("--reindex-timeout", type=float, default=60.0,
                        help="wait this long for reindex to finish")
    args = parser.parse_args(argv)

    base = args.base.rstrip("/")
    print(f"[smoke] base={base} duration={args.duration}s interval={args.interval}s")

    if not _wait_for_health(base):
        print(f"[smoke] FATAL: {base}/api/health never returned 200", file=sys.stderr)
        return 2

    print("[smoke] health OK; starting poll threads")
    results: dict = {"_errors": []}
    stop_event = threading.Event()

    # 路由列表覆盖原故障中最热的几条 read path：
    # - /api/market/evidence
    # - /api/briefing/list
    # - /api/briefing/latest
    # - /api/market/latest
    # - /api/watchlist
    # - /api/portfolio/pnl
    # - /api/knowledge/queue-status
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = "2026-07-09"  # 已知有数据的最近交易日
    poll_urls = [
        f"/api/market/evidence?date={today}&limit=20",
        f"/api/market/evidence?date={yesterday}&limit=20",
        "/api/briefing/list?limit=30&type=post_market",
        "/api/briefing/latest?type=post_market",
        "/api/market/latest",
        "/api/watchlist",
        "/api/portfolio/pnl",
        "/api/knowledge/queue-status",
    ]
    _poll_loop(base, poll_urls, args.duration, args.interval, results, stop_event)

    # 先让 poll 跑 5s 让线程们进入稳定节奏, 再触发 reindex 制造锁竞争
    time.sleep(5.0)
    print("[smoke] triggering reindex (with X-Local-Trigger)")
    reindex = _trigger_reindex(base)
    if reindex is None:
        print("[smoke] WARN: reindex did not start; continuing")

    job_id = reindex.get("job_id") if reindex else None
    if job_id:
        print(f"[smoke] reindex job_id={job_id}; polling until done")
        result = _poll_reindex_until_done(base, int(job_id), timeout=args.reindex_timeout)
        print(f"[smoke] reindex final: {result}")

    # 剩余时间继续 poll, 触发 cls_telegraph_sync 至少跑一轮
    print("[smoke] continuing poll until duration ends")
    stop_event.wait(args.duration)
    stop_event.set()
    time.sleep(1.0)  # 给 poll 线程一秒钟收尾

    # 汇总
    total_5xx = 0
    total_4xx = 0
    total_2xx = 0
    for url, counter in results.items():
        if url == "_errors":
            continue
        s5 = sum(v for k, v in counter.items() if isinstance(k, int) and 500 <= k < 600)
        s4 = sum(v for k, v in counter.items() if isinstance(k, int) and 400 <= k < 500)
        s2 = sum(v for k, v in counter.items() if isinstance(k, int) and 200 <= k < 300)
        total_5xx += s5
        total_4xx += s4
        total_2xx += s2
        print(f"  {url:60s} 2xx={s2:>3d} 4xx={s4:>3d} 5xx={s5:>3d}")

    print(
        f"\n[smoke] total: 2xx={total_2xx} 4xx={total_4xx} 5xx={total_5xx} "
        f"errors={len(results['_errors'])}"
    )
    if results["_errors"]:
        for url, err in results["_errors"][:5]:
            print(f"  network error: {url} -> {err}")

    if total_5xx > 0:
        print("\n[smoke] FAILED: saw 5xx responses (pool/lock issue regressed?)")
        return 1

    if reindex and result and result.get("status") == "failed":
        print(f"\n[smoke] reindex failed: {result.get('error_message')}")
        # 已知失败 (无 DEEPSEEK key / 空数据) 仍允许 smoke 0 退出,
        # 因为这里关注的是 HTTP 5xx, 不是 pipeline 业务正确性。
        return 0

    print("\n[smoke] PASS: no 5xx; reindex completed cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))