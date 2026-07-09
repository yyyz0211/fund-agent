"""领域服务。

    metric_service   — 纯 Python 的金融指标计算(无 I/O)
    data_collector   — AKShare 封装,带重试 + 错误字典契约
    fund_service     — 给 tool 用的基金操作(refresh / latest / metrics)
    market_service   — 给 tool 用的市场指数刷新
    cls_telegraph_client — 财联社电报协议客户端（签名/规范化/HTTP）
    cls_telegraph_sync_service — 财联社电报准实时同步
"""

from backend.services import cls_telegraph_client
