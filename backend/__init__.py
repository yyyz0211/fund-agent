"""基金代理后端包。

Phase 1:确定性基金数据层 + 轻量 LangChain/DeepSeek agent。
子包:
    config   — 配置(由环境变量驱动)
    db       — SQLAlchemy 模型、Session、初始化、仓储
    services — 供 tools 调用的领域服务(fund / market / collector / metrics)
    tools    — 围绕 services 的 LangChain tool 包装
    agent    — 轻量的 tool-calling agent(DeepSeek,走 OpenAI 兼容 API)
    scripts  — 手动 smoke / 验证入口
"""