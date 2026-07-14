# ADR-001: 业务异常体系 & 硬编码清理

**状态**: 已实施
**日期**: 2026-07-14
**对应规格**: `docs/superpowers/specs/2026-07-14-fund-agent-refactoring-design.md` §4.3 & §4.4

---

## §1. 业务异常体系(规格书 4.3)

### 类别

`backend/exceptions.py` 暴露七个异常类,均为 `FundAgentError` 子类:

| 异常                      | 用途                       | 抛出场景示例                                     |
|--------------------------|---------------------------|----------------------------------------------|
| `FundAgentError`         | 基础业务异常                 | 兜底                                          |
| `ResourceNotFoundError`  | 资源不存在                  | 基金代码未注册、job 不存在                          |
| `InputValidationError`   | 参数验证失败                 | period 不支持、向量维度不匹配                       |
| `DataSourceError`        | 外部数据源错误               | akshare 返回维度异常、curl 5xx                    |
| `DataSourceTimeoutError` | 外部数据源超时               | subprocess.TimeoutExpired                     |
| `DatabaseConflictError`  | 数据库冲突                  | 唯一约束违反 / 死锁                                |
| `DependencyUnavailableError` | 可选依赖不可用           | DEEPSEEK_API_KEY 缺失、pgvector 不可用            |

### 何时抛出哪个

- **参数错误** → `InputValidationError`,`field=` 标识出错字段,`details=` 给上游更多信息
- **资源找不到** → `ResourceNotFoundError`
- **外部源错误** → `DataSourceError` / `DataSourceTimeoutError`,`source=` 标识数据源
- **DB 冲突** → `DatabaseConflictError`
- **可选依赖失败** → `DependencyUnavailableError`,`dependency=` + `fallback=` 标识降级路径
- **其它业务 bug** → 兜底 `FundAgentError`

### API 层映射

`backend/api/app.py` 通过 `_register_exception_handlers()` 把异常映射到 HTTP:

| 异常                       | HTTP 状态 |
|---------------------------|----------|
| `ResourceNotFoundError`   | 404       |
| `InputValidationError`    | 422       |
| `DataSourceError`         | 502       |
| `DataSourceTimeoutError`  | 504       |
| `DatabaseConflictError`   | 409       |
| `DependencyUnavailableError` | 503    |
| 其它 `FundAgentError`     | 500       |
| 未分类 `Exception`        | 500,不泄露 stack trace |

API 响应统一格式:

```json
{
  "error": {
    "code": "input_validation",
    "message": "unsupported period: 2y",
    "field": "period",
    "details": {"allowed": ["1w", "1m", "3m", "6m", "1y"]}
  }
}
```

### 日志脱敏(规格书 4.3 约束)

`backend.exceptions` 提供两个工具:

- `redact_string(value: str) -> str`:删除字符串内嵌的 OpenAI / GitHub / AWS / Google 等 API key
- `redact_dict(payload: dict) -> dict`:递归清洗 dict/list/tuple,敏感 key 整值替换为 `***`

API 异常响应在返回前会调用 `redact_dict(exc.details)`;`ContextLogger` 同样在打印前清洗。

敏感 key 白名单:

```python
{"api_key", "apikey", "api-key", "authorization", "auth", "password",
 "passwd", "secret", "token", "access_token", "refresh_token",
 "private_key", "database_url", "db_password"}
```

### 结构化日志

`backend.logging_utils` 提供 `get_logger(name, default_context=...)`:

- 默认上下文可在模块入口绑定,如 `log = get_logger(__name__, default_context={"stage": "ingest"})`
- 每次记录时通过 `.info(msg, extra={...})` 或 `.bind(job_id=...)` 子 logger 携带额外上下文
- 输出格式:`[stage=ingest fund_code=110011] processing`,上下文按 key 排序
- 标准字段:`job_id` / `fund_code` / `source` / `stage` / `trigger`
- 所有输出在打印前统一 redact

### 禁止的模式

- ❌ `except Exception: pass` — 必须记录或返回显式降级状态
- ❌ 业务日志输出未脱敏的 API key / 数据库密码 / 完整持仓
- ❌ 直接 `raise HTTPException(status_code=502, detail=...)` 绕过业务异常体系
- ❌ `raise ValueError("unsupported period")` 这种"含义不明的内置异常"

### 允许的边界

规格书 4.3 允许在以下位置捕获宽异常,但必须记录上下文:

- 进程入口(如 alembic 启动迁移)
- 后台线程(如 scheduler job)
- 外部数据源调用边界(如 httpx 失败回退 curl)
- 显式降级路径(如可选 embedding 服务不可用)

---

## §2. 硬编码清理(规格书 4.4)

### 路径

- ✅ 启动路径基于 `Path(__file__).resolve().parent` 解析项目根
- ✅ 临时文件由 `tempfile` 模块生成,不写死 `/tmp/...`
- ⚠️ `backend/README.md` 仍有 `cd /Users/leon/fund-agent` 文档示例 —— 这些是**文档命令**而非代码路径,允许保留

### 魔法 timeout / 重试 / 批大小

必须进入 `backend.config.settings.Settings`,通过环境变量覆盖。

新增/迁移的字段:

| 字段                                     | 默认  | 用途                          |
|----------------------------------------|-------|-------------------------------|
| `db_pool_timeout_seconds`              | 10.0  | SQLAlchemy 连接池               |
| `cls_timeout_seconds`                  | 15.0  | CLS HTTP 请求                  |
| `cls_retry_base_seconds`               | 1.0   | CLS 重试退避                    |
| `knowledge_classification_retry_seconds` | 300 | 知识分类冷却                    |
| `knowledge_index_retry_seconds`        | 300   | 知识索引冷却                    |
| `market_index_history_timeout_seconds` | 5.0   | akshare index 历史超时         |
| `market_policy_page_timeout_seconds`   | 10.0  | policy_page 抓取超时            |

### 新增配置的 checklist

每个新增 Settings 字段必须:

1. 在 `Settings` 模型里有类型注解 + 默认值
2. 字段名带分组前缀(如 `cls_*`, `knowledge_*`, `market_*`, `briefing_*`)
3. 至少一个 unit test 覆盖默认值

### 协议常量 ≠ 运行参数

规格书 4.4 明确:协议常量保留代码常量。例如:

- `_PERIOD_ROWS = {"1w": 5, "1m": 21, ...}` 是协议语义,不是运行参数 → 留在代码
- `volatility()` 默认 `periods_per_year=252` 是行业惯例,不是部署配置 → 留在代码

### 测试路径

测试 fixture 里允许魔法值(测试隔离 / sleep),但必须注明意图:

```python
time.sleep(0.05)  # 等 holder 进入锁
```