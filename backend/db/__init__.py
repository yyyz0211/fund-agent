"""SQLAlchemy 持久化层。

模块:
    session    — engine 工厂、Session 工厂、get_session()
    models     — ORM 表:Fund、Watchlist、FundNav、MarketData
    init_db    — create_all 包装(CLI + 库函数)
    repositories — 按领域拆分、给 services 使用的 CRUD / upsert 帮助函数
"""
