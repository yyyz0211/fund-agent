# 定时数据刷新设计

> 本 spec 规划一个新增能力：后端进程内的定时数据刷新。
> 目标是在现有 `fund_service.refresh_fund` 和 `fund_profile_service.refresh_profile`
> 之上，加一个 APScheduler 调度器，每日收盘后自动刷新自选池全部基金的 NAV 和体检画像，
> 让用户打开前端看到的是当天数据，而不是上次手动刷新时的数据。

## 1. 背景

当前项目的数据新鲜度完全依赖用户手动动作：

- 详情页 "立即拉取" 按钮 → `POST /api/funds/{code}/refresh`。
- 加自选 / 建仓时的一次性 preload job（`watchlist_preload_jobs`）。
- 体检页 "刷新体检数据" → `POST /api/funds/{code}/diagnosis/refresh`。

没有任何自动机制。用户如果几天不点刷新，PnL、净值曲线、体检结论都停留在旧数据上。
roadmap 技术选型里已经写明 "定时任务：APScheduler / cron"，但一直没落地。

本阶段用 APScheduler 在 FastAPI 进程内起一个后台调度器，复用已有的刷新服务，
不引入独立进程、不引入外部 cron 依赖，贴合 "本地单用户 / 闲置电脑" 的部署形态。

## 2. 目标

- 每日固定时间（默认 20:00 Asia/Shanghai，A 股收盘且净值公布后）自动刷新自选池全部基金。
- 刷新内容：NAV 历史（`refresh_fund`）+ 体检画像（`refresh_profile`）。
- 调度器随 FastAPI 进程启动，随进程停止而停止。
- 可通过环境变量开关调度、配置刷新时间。
- 提供一个只读接口查看 "上次自动刷新" 的结果（成功数 / 失败数 / 时间）。
- 提供一个手动 "立即全量刷新" 接口，触发与定时任务相同的逻辑（方便测试和即时更新）。

## 3. 范围

本阶段包含：

- APScheduler 后台调度器（`BackgroundScheduler`），进程内单例。
- 一个批量刷新服务：遍历自选池 → 逐只 `refresh_fund` + `refresh_profile` → 汇总结果。
- 启动/停止钩子接入 FastAPI 生命周期。
- 环境变量配置：开关、cron 时间、时区。
- 只读的 "上次刷新结果" 接口 + 手动触发接口。
- 单元测试（调度注册、批量刷新逻辑、接口）。

本阶段不包含：

- 持久化的刷新历史（进程重启后 "上次结果" 丢失，可接受；只保留内存里最近一次）。
- 分布式 / 多实例调度（本地单进程场景不需要）。
- 每只基金独立的定时策略（统一一个全量任务）。
- 失败重试队列（单次失败记入结果，等下一天或手动重试）。
- 交易日历判断（周末/节假日照跑，AkShare 无新数据时 `refresh_fund` 返回 `already_up_to_date`，是无害 no-op）。

## 4. 产品行为

- 后端进程启动后，如果 `SCHEDULER_ENABLED=true`（默认 true），注册一个每日 cron 任务。
- 到点时任务遍历自选池全部 `fund_code`，逐只刷新 NAV + 画像，把结果汇总进内存里的 "上次刷新" 快照。
- 单只基金刷新失败（网络 / AkShare 报错）不中断整批，记入 `failed` 列表继续下一只。
- 前端可在自选页顶部 / 设置区展示 "数据更新于 X，成功 N 只，失败 M 只"（前端展示为可选增强，本阶段后端先把接口备好）。
- 用户想立即更新时，可调 `POST /api/admin/refresh-all` 手动触发同一套逻辑。

## 5. 工程分析

### 5.1 可复用的现有能力

- `fund_service.refresh_fund(code)`：拉 NAV + 基础信息，已有 `already_up_to_date` / `fund_info_warn` 契约。
- `fund_profile_service.refresh_profile(code)`：拉体检画像，返回 `missing_data` / `errors`。
- `watchlist_service.list_watchlist()`：拿全部自选行。
- `watchlist_preload_jobs`：已有的 "有界线程池 + 内存 job 快照" 模式，可作为写法参照。

### 5.2 并发与限流

- 批量刷新在调度线程里串行逐只跑即可（本地单用户，自选基金通常个位数到几十只）。
- 若担心 AkShare 被打太快，可在每只之间加小 sleep 或用有界线程池；v1 先串行 + 单只内部已有的 `ThreadPoolExecutor`，不额外并行整批。
- 调度用 `BackgroundScheduler`，`max_instances=1`、`coalesce=True`，避免上一次没跑完又触发导致叠加。

### 5.3 生命周期

- 调度器进程内单例，`app` startup 时 `start()`，shutdown 时 `shutdown(wait=False)`。
- 现有 `app.py` 用的是 `@app.on_event("startup")`（已弃用但仍可用）。本阶段沿用同一风格接入，不顺带迁 lifespan（避免混入无关改动；迁移单独开 issue）。

### 5.4 Docker 影响

- `BackgroundScheduler` 在 backend 容器进程内运行，不需要新容器。
- `TZ` 已由 docker-compose 注入（默认 `Asia/Shanghai`），cron 时间按该时区解释。

## 6. 配置设计

新增 `Settings` 字段（`backend/config/settings.py`），全部可用环境变量覆盖：

- `scheduler_enabled: bool = True` —— 总开关。测试 / CI 里设 false 避免起线程。
- `scheduler_refresh_cron_hour: int = 20` —— 每日触发小时（本地时区）。
- `scheduler_refresh_cron_minute: int = 0` —— 触发分钟。
- `scheduler_timezone: str = "Asia/Shanghai"` —— cron 时区。

对应环境变量：`SCHEDULER_ENABLED` / `SCHEDULER_REFRESH_CRON_HOUR` / `SCHEDULER_REFRESH_CRON_MINUTE` / `SCHEDULER_TIMEZONE`。

## 7. 后端接口

```http
GET  /api/admin/refresh-status
POST /api/admin/refresh-all
```

`GET /api/admin/refresh-status` 返回内存里最近一次批量刷新快照：

```json
{
  "last_run_at": "2026-07-06T20:00:03",
  "trigger": "scheduled",
  "total": 8,
  "succeeded": 7,
  "failed": 1,
  "already_up_to_date": 5,
  "failures": [
    {"fund_code": "000001", "error": "fetch_fund_nav_history failed: ..."}
  ]
}
```

未跑过时返回 `{"last_run_at": null, ...}` 全零快照。

`POST /api/admin/refresh-all` 在后台线程触发一次全量刷新（不阻塞请求线程），
立即返回 `{"status": "started", "total": <自选数>}`；结果稍后可在 status 接口查看。

> 安全说明：这两个接口没有鉴权，与项目现有 API 一致，信任模型依赖 Tailscale 网络边界。
> `/api/admin/*` 前缀便于将来统一加保护。此点写入 DOCKER.md 的信任模型说明。

## 8. 批量刷新服务契约

新增 `backend/services/scheduled_refresh.py`：

```python
def refresh_all_watchlist(*, trigger: str = "scheduled") -> dict:
    """遍历自选池全部基金，逐只 refresh_fund + refresh_profile，汇总结果快照。

    单只失败不中断整批；返回并同时写入内存 last-run 快照。
    """

def get_last_run() -> dict:
    """返回最近一次批量刷新快照；未跑过返回全零快照。"""

def start_refresh_all_async(*, trigger: str) -> dict:
    """在后台线程触发一次全量刷新，立即返回 {status, total}。单飞：已有任务在跑时复用。"""
```

- 内存快照用模块级 dict + `Lock` 保护（参照 `watchlist_preload_jobs` 写法）。
- 调度任务和手动接口都调 `refresh_all_watchlist` / `start_refresh_all_async`，逻辑单一来源。

## 9. 测试计划

后端：

- `scheduled_refresh.refresh_all_watchlist`：monkeypatch `refresh_fund` / `refresh_profile`，验证遍历全部自选、成功/失败分类、快照字段正确。
- 单只抛异常时不中断整批，记入 `failures`。
- `get_last_run` 未跑过返回全零快照。
- `start_refresh_all_async` 单飞：连续两次调用复用同一批。
- 调度注册：`scheduler_enabled=false` 时不注册 job；true 时注册一个 cron job（用假 scheduler 断言 `add_job` 被调用、trigger 参数正确）。
- API：`GET /refresh-status` 返回快照结构；`POST /refresh-all` 返回 `started`。

验证命令：

```bash
.venv/bin/python -m pytest backend/tests -q
```

## 10. 验收标准

- 后端进程启动时，`SCHEDULER_ENABLED=true` 注册每日 cron 任务，日志可见。
- 到点（或手动 `POST /api/admin/refresh-all`）能遍历自选池刷新 NAV + 画像。
- 单只基金失败不影响其余基金刷新，失败记入 `failures`。
- `GET /api/admin/refresh-status` 能查到上次刷新的成功/失败统计。
- `SCHEDULER_ENABLED=false` 时不起调度线程（测试环境默认关闭）。
- 全部后端测试通过。

## 11. 假设与边界

- 本地单用户 / 单进程；不需要持久化调度状态，进程重启丢失 "上次结果" 可接受。
- 自选基金数量在个位数到几十只量级，串行刷新耗时可接受（每只几秒）。
- 周末 / 节假日照跑，无新数据时是无害 no-op。
- 不代操作、不自动交易；定时任务只刷新公开数据缓存。
