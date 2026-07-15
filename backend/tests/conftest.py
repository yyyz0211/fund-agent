"""pytest 全局配置。

测试环境默认关闭定时调度器,避免 FastAPI 启动钩子起真实后台线程
(APScheduler)污染测试或造成线程泄漏。个别调度器测试自己传 enabled=True
走假调度器,不受此环境变量影响。
"""
import os

os.environ.setdefault("SCHEDULER_ENABLED", "false")

pytest_plugins = ("backend.tests.postgres_fixtures",)
