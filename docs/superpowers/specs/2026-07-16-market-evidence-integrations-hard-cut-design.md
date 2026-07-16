# 市场证据 Integrations 硬切换设计

**版本**：1.0
**日期**：2026-07-16
**状态**：已确认

## 1. 背景与目标

当前五类市场证据 adapter 位于 `backend/services/market_sources/`。其中政策页、FRED、
行业热度是外部来源适配逻辑，CLS 和 CNInfo adapter 还直接反向依赖
`backend.services` 下的客户端或采集器。该结构把外部系统边界留在 service 层，并使
adapter 难以独立替换和测试。

本次将以下五类 adapter 一次性硬切换到 `backend/integrations/`：

- 财联社电报（CLS）；
- 基金公告（CNInfo/AKShare/Eastmoney）；
- FRED 宏观数据；
- 政策页面；
- 行业热度快照。

迁移完成后删除 `backend/services/market_sources/`，不保留 re-export、弃用模块、旧导入
兼容层或双实现。业务层只依赖 `backend.integrations`，而 integrations 不得反向导入
`backend.services`。

## 2. 范围

### 2.1 本次包含

- 移动五类 adapter、默认来源常量、默认 adapter factory 和共用 HTML/URL helper；
- 通过 callable 注入解除 CLS、CNInfo 对 service 模块的反向依赖；
- 更新生产代码、测试与 monkeypatch 目标到新导入路径；
- 新增硬切换结构契约和依赖方向契约；
- 为 CNInfo 增加缺失的依赖接线测试，详见第 7 节。

### 2.2 本次不包含

- 不移动或重构 `backend/services/market/data_collector.py`；
- 不移动或重构 `backend/services/knowledge/cls_telegraph_client.py`；
- 不修改外部 URL、HTTP timeout、retry、默认来源列表或 Settings 字段；
- 不把 adapter 改造成自动注册插件，也不调整 `AdapterRegistry`；
- 不统一现有 `MarketSourceAdapter` protocol 与 adapter 在 `trade_date` 类型、metadata
  暴露方式上的历史差异；
- 不重写异常处理、日志策略或 ingestion 流程；
- 不顺带处理 AKShare 并发、缓存或其他市场采集逻辑。

大型采集客户端的边界治理留给后续独立规格，避免一次迁移同时承担结构移动与客户端
重构两类风险。

## 3. 方案决策

采用“provider 子包 + callable 依赖注入”的硬切换方案：

```text
backend/integrations/
├── __init__.py
├── protocols.py
├── registry.py
├── market_evidence.py       # 默认常量与 build_default_adapters
├── _html.py                 # 私有 HTML/URL helper
├── cls/
│   ├── __init__.py
│   └── adapter.py
├── cninfo/
│   ├── __init__.py
│   └── adapter.py
├── fred/
│   ├── __init__.py
│   └── adapter.py
├── policy/
│   ├── __init__.py
│   └── adapter.py
└── sector/
    ├── __init__.py
    └── adapter.py
```

选择 provider 子包是为了让每个外部来源拥有独立、可扩展的边界；选择 callable 注入是
为了让 integrations 仅描述“如何把供应商结果转换为 evidence”，而不依赖业务 service
的具体存放位置。

不采用以下方案：

1. **直接移动并保留反向导入**：改动较小，但 `integrations → services` 会固化错误的
   依赖方向。
2. **只移动三个自包含 adapter**：短期风险低，但留下两套 adapter 入口和未完成迁移，
   不符合本阶段硬切换目标。

## 4. 模块职责与公开入口

`backend/integrations/market_evidence.py` 是五类 adapter 的聚合与默认构造入口，包含：

- `DEFAULT_POLICY_ADAPTERS`；
- `DEFAULT_FRED_SERIES`；
- `build_default_adapters(...)`。

各 provider 子包只导出本来源的 adapter 类。生产消费者使用明确入口：

```python
from backend.integrations.market_evidence import build_default_adapters
from backend.integrations.cls import ClsTelegraphAdapter
```

`backend/integrations/__init__.py` 不重新导出所有 adapter 和 factory，避免创建新的宽
facade。`_html.py` 是私有实现细节，只供 integrations 内部使用。

现有 `protocols.py` 与 `registry.py` 保留。此次迁移不要求五类 adapter 注册到
`AdapterRegistry`，也不借结构迁移扩大其公开契约。

## 5. 依赖注入与数据流

### 5.1 组合根

`backend/services/market/market_evidence_service.py` 继续作为业务组合根。它负责：

1. 读取 Settings；
2. 创建并关闭共享 HTTP client；
3. 将 `cls_telegraph_client.fetch_roll_list` 与
   `data_collector.fetch_announcements` 注入默认 factory；
4. 将 factory 返回的 adapter 列表交给现有 ingestion；
5. 保留当前 session、单飞与结果状态语义。

调用关系固定为：

```text
market_evidence_service
  ├── services.knowledge.cls_telegraph_client.fetch_roll_list
  ├── services.market.data_collector.fetch_announcements
  └── integrations.market_evidence.build_default_adapters
        ├── integrations.cls.ClsTelegraphAdapter
        ├── integrations.cninfo.CninfoAnnouncementAdapter
        ├── integrations.fred.FredSeriesAdapter
        ├── integrations.policy.PolicyPageAdapter
        └── integrations.sector.SectorHeatAdapter
```

依赖方向只能是 `services → integrations`。`backend/integrations/**/*.py` 中不得导入
`backend.services`。

### 5.2 Factory 契约

`build_default_adapters` 保留现有 keyword-only 参数，并增加两个显式依赖参数：

```python
def build_default_adapters(
    *,
    client,
    fetch_cls_roll_list,
    fetch_announcements,
    brief_type: str = "post_market",
    sector_snapshot: dict | None = None,
) -> list:
    ...
```

两个 callable 都是必填依赖；所有生产和测试消费者必须显式传入，不允许 factory
从 service 层获取默认实现或在缺失时静默降级。即使 pre-market 当前不会构造 CLS 与
CNInfo adapter，也沿用同一完整签名，使组合根始终明确声明依赖。factory 纯构造测试传
fake callable，因此不会触发外部请求。是否构造 CLS 仍受现有 `CLS_ENABLED` 配置控制。

### 5.3 Adapter 构造契约

- `ClsTelegraphAdapter` 构造时接收必填的 `fetch_roll_list` callable 和 `app_version`；
  `fetch()` 只调用注入的 callable，不复制或导入 client 模块的默认版本常量；
- `CninfoAnnouncementAdapter` 构造时接收 `fetch_announcements` callable，`fetch()` 只调用
  该依赖；
- FRED、Policy、Sector adapter 只移动模块，不新增业务依赖；
- callable 的参数和返回字典沿用现有 client/collector 契约，不新建 DTO。

依赖应在构造阶段确定，避免测试通过修改模块全局变量替换依赖。adapter 仍接受现有
`fetch(..., client, trade_date, brief_type)` 调用形式。

## 6. 行为不变量

除第 7 节明确列出的 CNInfo 接线修正外，迁移必须保持：

- pre-market 与 post-market 的默认 adapter 种类、数量和顺序；
- `sector_snapshot is None` 时跳过 Sector adapter；
- CLS 启用条件、categories、per-category limit、timeout、app version、retry 参数；
- evidence 的字段名、字段默认值、category、source、reliability 和 URL 生成规则；
- Policy/FRED/CLS 的解析与过滤行为；
- 单个 adapter 失败返回空列表的约定；
- CLS 按 category 隔离失败、继续处理后续 category，并维护 `last_errors`；
- factory 遇到 CLS 配置或构造失败时记录 warning 并继续返回其他 adapter；
- ingestion 的去重、写库、错误聚合与事务所有权。

本次不新增网络调用发生在 factory 构造阶段。所有外部调用仍只发生在 adapter
`fetch()` 或现有业务预取流程中。

## 7. CNInfo 现有接线缺陷

当前 `CninfoAnnouncementAdapter` 导入了 `data_collector` 模块，却在 `fetch()` 中调用未
绑定的 `fetch_announcements(...)`。该 `NameError` 被 adapter 的宽异常捕获转为空列表，
所以当前生产路径无法产生 announcement evidence。

硬切换时明确修正此缺陷：组合根注入
`data_collector.fetch_announcements`，adapter 调用注入的 callable。该修正会使已有公告
数据首次正常进入 evidence ingestion，是本次唯一允许的有意行为变化。

为控制风险，修正不得改变：

- collector 的 `limit` 参数与默认 adapter limit；
- 公告标题过滤、日期 fallback、基金代码 URL 和 symbols 生成；
- collector 抛错时返回空列表的失败隔离语义；
- evidence 列表达到 limit 时停止的规则。

## 8. 错误处理

- 每个 adapter 继续遵守“不得向 ingestion 抛出外部请求或解析异常”的现有契约；
- CLS 单 category 异常继续写入 `last_errors`，不阻断其他 category；
- CLS 自建 HTTP client 时继续在 `finally` 中关闭；共享 client 仍由组合根关闭；
- CNInfo 注入 callable 抛错时返回空列表；
- factory 的 CLS 配置错误继续记录现有 warning 文案语义；
- 不在本次迁移中引入统一重试装饰器或新的 exception 类型。

## 9. 测试策略

### 9.1 RED 门禁与结构契约

实施先增加会失败的契约测试，要求：

- `backend/services/market_sources/` 不存在；
- Python 源码中没有 `backend.services.market_sources` 导入；
- `backend/integrations/` 不导入 `backend.services`；
- 五个 provider 子包和 `integrations.market_evidence` 可独立导入；
- 生产组合根向 factory 传入两个 callable。

### 9.2 Adapter 行为测试

- 将 Policy、FRED、CLS 现有测试迁到新入口，断言保持不变；
- CLS 测试通过构造参数注入 fake callable，不再 monkeypatch service client 模块；
- 新增 CNInfo 成功映射测试、collector 异常隔离测试和 limit 测试；
- 为 Sector 与 Policy/FRED helper 保留输出形状和绝对 URL 回归；
- 断言 CLS `last_errors` 与 category 失败隔离行为不变。

### 9.3 Factory 与组合根测试

- factory 测试只使用 fake callable 和 fake Settings，不访问网络；
- 断言 pre-market/post-market adapter 类型、数量与顺序；
- 断言 CLS disabled、配置异常，以及缺少必填 callable 时立即报 `TypeError`；
- 断言组合根注入现有 CLS client 与公告 collector，并继续关闭 HTTP client；
- 更新 briefing 与 market evidence 测试的 import/patch 目标。

### 9.4 全量验证

- 运行 adapter、market evidence、briefing 相关定向测试；
- 运行 AST/路径依赖契约；
- 使用 PostgreSQL worker schema fixture 运行完整 backend 测试；
- 运行 `compileall`、`git diff --check` 和旧路径全文门禁。

## 10. 提交边界与回滚

设计文档与实施计划分别独立提交。实现以一个原子提交交付，包含：

1. 新 provider 子包和 factory；
2. 组合根 callable 注入；
3. 所有生产与测试导入切换；
4. CNInfo 接线回归测试；
5. 删除旧 `market_sources` 目录；
6. 硬切换与依赖方向契约。

若无法同时满足行为测试和依赖方向门禁，则不提交部分迁移。回滚整个实现提交即可恢复
旧目录；本次不包含数据库 migration 或数据修复。

## 11. 完成标准

- 五类 adapter 的唯一实现位于 `backend/integrations/`；
- `backend/services/market_sources/` 已删除且仓库内无旧导入；
- integrations 不反向依赖 services；
- 默认 adapter 集合、顺序、配置与 evidence 形状保持，CNInfo 接线缺陷按第 7 节修正；
- 现有 ingestion、事务所有权与业务单飞语义不变；
- 定向测试、结构契约与 PostgreSQL backend 全量测试通过；
- 工作区不存在兼容层、重复实现或迁移临时文件。
