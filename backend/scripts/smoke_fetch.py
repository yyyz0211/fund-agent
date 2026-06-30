"""手动 smoke 测试:跑一遍真实 AKShare → DB → thin agent 的全链路。

用法:
    cd /Users/leon/fund-agent
    python -m backend.scripts.smoke_fetch 110011
需要 backend/.env 里有 DEEPSEEK_API_KEY(可选,无 key 时跳过第 5 步)。
"""
import os
import sys

from backend.db.init_db import init_db
from backend.services import fund_service as fs
from backend.services import market_service as ms


def main(fund_code: str) -> None:
    """依次打印:refresh / latest / metrics / market / agent 五步的结果。"""
    os.makedirs("backend/data", exist_ok=True)
    init_db()

    print(f"[1] refresh_fund({fund_code}) ...")
    print("   ", fs.refresh_fund(fund_code))

    print("[2] get_latest_nav ...")
    print("   ", fs.get_latest_nav(fund_code))

    print("[3] get_metrics(period=1m) ...")
    print("   ", fs.get_metrics(fund_code, period="1m"))

    print("[4] refresh_market ...")
    print("   ", ms.refresh_market())

    print("[5] thin agent (skipped if no DEEPSEEK_API_KEY) ...")
    try:
        from backend.agent.thin_agent import ask
        print("   ", ask(f"基金 {fund_code} 最新净值是多少?近一个月最大回撤呢?"))
    except RuntimeError as e:
        print("    skipped:", e)


if __name__ == "__main__":
    # 不传参时默认 110011(易方达蓝筹精选),便于日常快速验证。
    code = sys.argv[1] if len(sys.argv) > 1 else "110011"
    main(code)