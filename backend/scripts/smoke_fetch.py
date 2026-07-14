"""手动 smoke 测试:跑一遍 AKShare → DB → agent 的全链路。

Phase 1 链路:refresh / latest / metrics / market / thin agent
Phase 3 新增:basic_info / nav_history (全量+区间) / indices / watchlist CRUD
Phase 4 新增:LangGraph QA flow

用法:
    cd /path/to/fund-agent
    .venv/bin/python -m backend.scripts.smoke_fetch 110011
需要 backend/.env 里有 DEEPSEEK_API_KEY(可选,无 key 时跳过 agent 步骤)。
"""
import os
import sys

from backend.db.init_db import init_db
from backend.services.fund import fund_service as fs
from backend.services.market import market_service as ms
from backend.services.watchlist import watchlist_service as ws


def main(fund_code: str) -> None:
    """依次打印各步结果。"""
    os.makedirs("backend/data", exist_ok=True)
    init_db()

    # ── Phase 1 链路 ────────────────────────────────────────────
    print(f"[1] refresh_fund({fund_code}) ...")
    r = fs.refresh_fund(fund_code)
    print("   ", r)

    print("[2] get_latest_nav ...")
    print("   ", fs.get_latest_nav(fund_code))

    print("[3] get_metrics(period=1m) ...")
    print("   ", fs.get_metrics(fund_code, period="1m"))

    print("[4] refresh_market ...")
    print("   ", ms.refresh_market())

    # ── Phase 3 新增 service ────────────────────────────────────
    print("[5] get_basic_info ...")
    print("   ", fs.get_basic_info(fund_code))

    print("[6] get_nav_history (全量) ...")
    print("   ", fs.get_nav_history(fund_code))

    print("[7] get_nav_history (区间 2026-01-01~2026-03-31) ...")
    print("   ", fs.get_nav_history(fund_code, start_date="2026-01-01", end_date="2026-03-31"))

    print("[8] get_indices ...")
    print("   ", ms.get_indices())

    # ── Phase 3 自选池 ──────────────────────────────────────────
    print(f"[9] add_fund_to_watchlist({fund_code}) ...")
    print("   ", ws.add(fund_code, note="smoke test"))

    print("[10] get_watchlist ...")
    print("   ", ws.list_watchlist())

    print("[11] update_fund_note ...")
    print("   ", ws.update_note(fund_code, "smoke test updated"))

    print(f"[12] remove_fund_from_watchlist({fund_code}) ...")
    print("   ", ws.remove(fund_code))

    # ── Agent(可选) ─────────────────────────────────────────────
    print("[13] thin agent (skipped if no DEEPSEEK_API_KEY) ...")
    try:
        from backend.agent.thin_agent import ask
        print("   ", ask(f"基金 {fund_code} 最新净值是多少?近一个月最大回撤呢?"))
    except RuntimeError as e:
        print("    skipped:", e)

    print("[14] LangGraph QA (skipped if no DEEPSEEK_API_KEY) ...")
    try:
        from backend.graph.qa_graph import ask as graph_ask
        print("   ", graph_ask(f"基金 {fund_code} 最新净值是多少?近一个月最大回撤呢?"))
    except RuntimeError as e:
        print("    skipped:", e)


if __name__ == "__main__":
    code = sys.argv[1] if len(sys.argv) > 1 else "110011"
    main(code)
