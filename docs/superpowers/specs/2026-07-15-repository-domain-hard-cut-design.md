# Repository 领域化硬切换设计

**版本**：1.0  
**日期**：2026-07-15  
**状态**：已确认

## 1. 目标

将 `backend/db/repository.py` 中的持久化实现一次性迁入
`backend/db/repositories/` 下的六个领域模块，并在同一变更中更新仓库内所有消费者。
迁移完成后删除旧模块，不保留 re-export、弃用层或双实现。

本次是结构性纯迁移：不得改变 SQL、查询排序、幂等键、返回结构、异常语义、
`flush()` 行为或事务所有权。

## 2. 方案决策

采用全量硬切换，而不是兼容 facade 或逐领域迁移：

- 六个领域模块在一个原子变更中成为实现的唯一权威来源。
- backend、API、脚本和测试中的旧导入全部改为新领域入口。
- 删除 `backend/db/repository.py`。
- 若任一领域无法维持行为等价，则不提交部分迁移。

该方案接受一次性较大的导入改动，以换取没有兼容窗口和长期迁移债务。

## 3. 领域边界

```text
backend/db/repositories/
├── __init__.py     # 仅暴露领域模块，不聚合全部函数
├── fund.py         # 基金、净值、交易和基金画像
├── watchlist.py    # 自选、投资计划和待确认买入
├── market.py       # 市场快照和市场证据
├── briefing.py     # 简报持久化
├── knowledge.py    # 电报、分类、知识文档、来源、匹配和队列
└── jobs.py         # 后台任务状态查询
```

私有序列化和 patch helper 跟随使用它的领域移动。helper 不在领域间复制；只有确有
两个以上领域共同使用且语义完全一致时才提取共享模块，本次预期不需要新增共享基类。

`list_knowledge_reindex_jobs` 归入 `jobs.py`。其余现有公开函数沿用当前六个模块
`__all__` 表达的领域归属；迁移时补齐遗漏的私有 helper，不新增 repository API。

## 4. 导入规则

消费者直接导入领域模块，并优先保留模块别名，以便测试替换依赖：

```python
from backend.db.repositories import fund as fund_repo
from backend.db.repositories import knowledge as knowledge_repo
```

只使用单个稳定函数且现有测试不依赖模块 monkeypatch 时，可以直接导入函数：

```python
from backend.db.repositories.briefing import upsert_briefing
```

迁移完成后，运行时代码和测试中不得出现：

- `backend.db.repository`
- `from backend.db import repository`
- `from backend.db.repository import ...`

`backend/db/repositories/__init__.py` 只导出六个领域模块，不重新聚合所有函数，避免
形成新的单体 facade。

## 5. 数据与事务不变量

- repository 继续接收调用方提供的 SQLAlchemy `Session`。
- repository 不创建 Session，不调用 `commit()`、`rollback()` 或 `close()`。
- 写操作继续只调用 `flush()`；原本不 flush 的只读路径保持不变。
- ORM 查询条件、join、排序、limit 和锁语义逐行保持。
- 字典字段、日期格式、JSON 处理、`None` 语义和返回类型保持。
- 唯一冲突、upsert、幂等键和 PostgreSQL 方言行为保持。
- 不顺带重命名函数、参数、模型或数据库字段。

## 6. 测试策略

### 6.1 结构契约

新增 AST/路径契约测试，验证：

- `backend/db/repository.py` 不存在。
- Python 源码中没有旧 repository 导入。
- 六个领域模块均可独立导入。
- repository 函数不拥有事务。

### 6.2 行为回归

- 现有 repository 测试改从相应领域模块导入，断言内容不变。
- service、API 和后台任务测试同步更新 monkeypatch 目标。
- 按领域运行 fund、watchlist、market、briefing、knowledge 和 jobs 测试。
- 最后使用 PostgreSQL worker schema fixture 运行完整 backend 测试。
- 运行 `compileall`、`git diff --check` 和旧导入全文门禁。

本次不以测试代码重排为目标；测试只做导入和 patch 目标迁移，以及新增结构契约。

## 7. 提交边界与回滚

设计文档与实施计划各自独立提交。实现以一个原子提交交付，包含：

1. 六个领域模块中的真实实现；
2. 所有生产与测试消费者的新导入；
3. 删除旧 `repository.py`；
4. 结构契约测试。

若全量回归失败且无法证明与迁移无关，则不创建实现提交。回滚整个实现提交即可恢复
旧单体模块，不需要数据库 migration 或数据修复。

## 8. 完成标准

- 六个领域模块是 repository 实现的唯一来源。
- 旧 `backend/db/repository.py` 已删除，仓库内无旧导入。
- 全部 repository/service/API/job 行为测试通过。
- PostgreSQL 全量 backend 测试通过。
- 无 SQL、返回结构和事务所有权变化。
- 工作区中不存在临时兼容层或重复实现。
