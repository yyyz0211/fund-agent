# Docker 部署指南

把 Fund Agent 部署到一台闲置电脑上,**通过 Tailscale 让朋友访问**。整套设计:

- **零公网端口**:闲置电脑不开 80/443,所有访问走 Tailscale VPN(加密内网)
- **零域名 / 零证书**:不需要 Cloudflare、Let's Encrypt、TLS 配置
- **Docker 一键拉起**:4 个容器,Postgres / 后端 / LangGraph / 前端
- **数据本地化**:数据库、备份都在家里那台电脑上

```
┌─────────────── 朋友 A (Tailscale 客户端) ──────────────┐
│                                                        │
│  浏览器 http://100.x.x.x:3000                          │
└────────────────────────┬───────────────────────────────┘
                         │ Tailscale WireGuard 加密隧道
                         ▼
┌─────────── 闲置电脑(本机) / Docker ─────────────────────┐
│  fund-frontend  :3000                                   │
│  fund-backend   :8000                                   │
│  fund-langgraph :2024                                   │
│  fund-postgres  :5432 (内网)                            │
└──────────────────────────────────────────────────────────┘
```

---

## 0. 前置清单

| 准备 | 步骤 |
|------|------|
| 闲置电脑 | Windows 10/11 或 Linux/macOS,开着电源,能联网 |
| Docker | 装 Docker Desktop(Win/Mac)或 `docker engine`(Linux) |
| Tailscale | [官网](https://tailscale.com/kb/1017/install) 装客户端,**用同一个账号登录**(可让朋友邀请) |
| DeepSeek Key | https://platform.deepseek.com 申请,充 ¥10 起 |

---

## 1. 部署步骤

### 1.1 安装 Tailscale 并组网

```powershell
# 在闲置电脑上(Win)
winget install Tailscale.Tailscale

# 装完会在系统托盘出现小图标,点 "Log in",用 GitHub / Google 账号登录
# 记录下这台电脑的 Tailscale IP:
tailscale ip -4
# 输出形如: 100.64.0.2   ← 这个就是你朋友要访问的地址
```

**让朋友也加入同一网络**:

1. 你登录 https://login.tailscale.com/admin/invite
2. 生成邀请链接 → 发给朋友
3. 朋友打开链接装客户端 + 登录
4. 朋友就能通过 `100.x.x.x:3000` 访问了

### 1.2 拉代码

```powershell
cd D:\
git clone <your-repo-url> fund-agent
cd fund-agent
```

### 1.3 配置 .env

```powershell
cp .env.example .env
notepad .env
```

需要修改(其余保持默认即可):

```ini
POSTGRES_PASSWORD=<随机 32 字符以上>
DEEPSEEK_API_KEY=sk-真实的key
ALLOWED_ORIGINS=http://100.64.0.2:3000,http://localhost:3000     ← 改成你那台机器的 Tailscale IP
NEXT_PUBLIC_API_BASE_URL=http://100.64.0.2:8000
NEXT_PUBLIC_LANGGRAPH_URL=http://100.64.0.2:2024
```

`100.x.x.x` 全部要换成你 `tailscale ip -4` 的实际结果。

### 1.4 启动

```powershell
.\scripts\start.ps1
```

脚本会自动 build + up + log。**首次构建可能耗时 5-10 分钟**(下 npm 镜像 + pip 镜像)。

### 1.5 验证

```powershell
# 看 4 个容器都 healthy
docker compose ps

# 健康检查
curl http://localhost:8000/api/health
# → {"status":"ok"}

# 浏览器打开
#    http://localhost:3000         ← 本机
#    http://100.64.0.2:3000        ← 朋友的 Tailscale 网络访问
```

---

## 2. 日常运维

### 2.1 更新代码

```powershell
.\scripts\update.ps1
```

内部流程:`git pull` → `docker compose up -d --build` → 清理悬空镜像。

### 2.2 备份数据库

```powershell
.\scripts\backup-db.ps1
```

输出到 `backups/fund_YYYYMMDD_HHMMSS.sql`,保留 30 天。

**自动化每日备份**(Windows 任务计划程序):

1. 打开 "任务计划程序" → "创建任务"
2. 触发器:每天 03:00
3. 操作: `powershell.exe` 起始于 `D:\fund-agent` 参数 `-File "D:\fund-agent\scripts\backup-db.ps1"`
4. 勾选 "不管用户是否登录都要运行"

### 2.3 异地容灾(可选)

把 `backups/` 同步到云盘:

```powershell
# 安装 rclone, 配置 OneDrive / Google Drive / S3
rclone sync D:\fund-agent\backups onedrive:fund-agent-backups --progress
```

加到任务计划每周一次即可。

### 2.4 看日志

```powershell
docker compose logs -f backend     # 跟随后端日志
docker compose logs --tail 100 langgraph
```

### 2.5 重启单个服务

```powershell
docker compose restart backend
docker compose up -d --build backend    # 代码改了要重建
```

---

## 3. 故障排查

### Q:朋友那边 "无法连接 / 超时"

检查清单:
1. **Tailscale 是否都登录到同一个账号?**
   - https://login.tailscale.com/admin/machines 看看节点列表
2. **闲置电脑是否开机?**(关机了自然连不上)
3. **Windows 防火墙是否放行了 3000/8000/2024?**
   ```powershell
   New-NetFirewallRule -DisplayName "FundAgent-3000" -Direction Inbound -LocalPort 3000 -Protocol TCP -Action Allow
   New-NetFirewallRule -DisplayName "FundAgent-8000" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow
   New-NetFirewallRule -DisplayName "FundAgent-2024" -Direction Inbound -LocalPort 2024 -Protocol TCP -Action Allow
   ```
4. **朋友侧能 ping 通你这台?**
   ```powershell
   # 在朋友机器上
   ping 100.64.0.2
   ```
5. **端口确实在监听?**
   ```powershell
   # 在你这台机器上
   netstat -an | findstr :3000
   netstat -an | findstr :8000
   ```

### Q:前端能开,但接口报 CORS 错误

`.env` 里的 `ALLOWED_ORIGINS` 没包含朋友用的地址。补上后:

```powershell
docker compose restart backend
```

### Q:后端 health 通过,但 akshare 取不到数据

国内网络通常没事。如果是海外 VPS / 跨地区网络,可能要到 `backend/Dockerfile` 加代理环境变量。在家用 Windows 闲置电脑通常不需要。

### Q:Postgres 容器起不来

```powershell
docker compose logs postgres | findstr /C:"FATAL" /C:"ERROR"
```

最常见原因:密码改了,旧 volume 还有同名库。要彻底重建:

```powershell
docker compose down -v     # ⚠️ 会删数据,先备份!
.\scripts\start.ps1
```

### Q:磁盘满了

```powershell
docker system df
docker volume prune           # 删未被使用的 volume(不会动 pgdata)
docker image prune -a -f       # 删全部未使用镜像
```

数据库本身占不了多少(几百 MB 级)。

---

## 4. 架构细节

### 网络拓扑

```
                Tailscale 100.64.0.0/10 客户端
   你 ┐                                  ┌ 朋友
   Mac├─ 100.64.0.x ──── WireGuard ──────┤
      │                                  │
      └─→ fund-backend:8000  ←───────────┘  (通过 100.64.0.2:8000)
              │
   ┌──────────┴──────────┐
   │                     │
   │ Docker bridge       │
   │                     │
   ├─ fund-postgres      │     5432 (internal only)
   ├─ fund-frontend      │     3000
   ├─ fund-langgraph     │     2024
```

### 数据持久化

- Postgres 数据存在命名 volume `fund-agent_pgdata`,对应容器路径 `/var/lib/postgresql/data`
- 删除 volume = 删数据(`docker compose down -v`)
- 备份是独立 SQL 文件,跟 volume 解耦

### 为什么用 Postgres 而不是保留 SQLite?

| | SQLite | Postgres |
|---|---|---|
| Docker 容器删除/重建 | 数据跟着删 | 走 volume 持久化 |
| 多进程并发写 | 容易锁库 | OK |
| 备份标准 | 文件拷贝 | `pg_dump` 文本 |
| 性能(本项目规模) | 够用 | 够用,稍有富余 |

迁移成本几乎为 0:你的代码本来走 SQLAlchemy 抽象层,只换连接串就行(已经在 docker-compose 里做了)。

---

## 5. 进阶(后面再说)

- **HTTPS / 自定义域名**:Tailscale Funnel 或 Cloudflare Tunnel,需要时再开
- **CI/CD**:GitHub Actions push 后自动 SSH 到这台机器跑 `update.ps1`,需要再写
- **看板**:Dockge(50MB)/ Portainer(更大),Docker 自带容器视图够用了
- **监控告警**:UptimeRobot 免费版,配合 DeepSeek 余额提醒

---

## 6. 卸载

```powershell
# 停止并删容器(保留 volume)
docker compose down

# 也删数据:
docker compose down -v

# 卸载 Tailscale:
winget uninstall Tailscale.Tailscale
```
