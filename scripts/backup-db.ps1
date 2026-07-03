#requires -Version 5.1
<#
.SYNOPSIS
    备份 Postgres 到本地 backups/ 目录(纯 SQL 转储)。

.DESCRIPTION
    默认每天跑一次,把容器里的 Postgres 用 pg_dump 导出成 SQL。
    保留最近 30 天。容器名 fund-postgres 见 docker-compose.yml。

    可被 Windows 任务计划程序每日触发:
        任务:  powershell.exe -ExecutionPolicy Bypass -File "D:\fund-agent\scripts\backup-db.ps1"

.EXAMPLE
    .\scripts\backup-db.ps1               # 默认行为
    .\scripts\backup-db.ps1 -KeepDays 7   # 只保留 7 天

.NOTES
    数据库密码是从 .env 的 POSTGRES_PASSWORD 读取的。cron 触发时,
    .env 必须存在于脚本运行的当前目录下(用任务计划程序可以设
    "起始于" 路径解决)。
#>

param(
    [int]$KeepDays = 30,
    [string]$ContainerName = "fund-postgres",
    [string]$DbUser = $env:POSTGRES_USER,
    [string]$DbName = $env:POSTGRES_DB
)

$ErrorActionPreference = "Stop"

# 容器是否存在
$inspect = docker inspect $ContainerName 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] 找不到容器 $ContainerName,先 docker compose up 起来。" -ForegroundColor Red
    exit 1
}

# 如果没传 DB user / name,从 cwd 的 .env 读
if (-not $DbUser -or -not $DbName) {
    $envFile = Join-Path (Get-Location) ".env"
    if (Test-Path $envFile) {
        Get-Content $envFile | ForEach-Object {
            if ($_ -match '^\s*POSTGRES_USER\s*=\s*(.+)\s*$') { $script:DbUser = $Matches[1].Trim() }
            if ($_ -match '^\s*POSTGRES_DB\s*=\s*(.+)\s*$')   { $script:DbName = $Matches[1].Trim() }
        }
    }
}

if (-not $DbUser -or -not $DbName) {
    Write-Host "[FAIL] 缺 POSTGRES_USER / POSTGRES_DB,从 .env 或环境变量传入。" -ForegroundColor Red
    exit 1
}

# 准备输出目录
$backupDir = Join-Path (Get-Location) "backups"
if (-not (Test-Path $backupDir)) { New-Item -ItemType Directory -Path $backupDir | Out-Null }

$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$outFile = Join-Path $backupDir "fund_${ts}.sql"

# pg_dump 通过 env 注入密码,避免命令行明文
Write-Host "[INFO] 备份 $DbName → $outFile ..." -ForegroundColor Cyan
docker exec -e PGPASSWORD=$env:POSTGRES_PASSWORD $ContainerName `
    pg_dump -U $DbUser -d $DbName --no-owner --no-privileges `
    | Out-File -FilePath $outFile -Encoding utf8

if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] pg_dump 失败。" -ForegroundColor Red
    exit 1
}

# 校验文件非空
if ((Get-Item $outFile).Length -lt 100) {
    Write-Host "[WARN] 备份文件异常小,看看里面的内容:" -ForegroundColor Yellow
    Get-Content $outFile | Select-Object -First 20
    exit 1
}

Write-Host "[OK] 备份完成: $outFile" -ForegroundColor Green

# 清理过期备份
$cutoff = (Get-Date).AddDays(-$KeepDays)
Get-ChildItem -Path $backupDir -Filter "fund_*.sql" -ErrorAction SilentlyContinue `
    | Where-Object { $_.LastWriteTime -lt $cutoff } `
    | ForEach-Object {
        Write-Host "[INFO] 删除过期: $($_.Name)"
        Remove-Item $_.FullName -Force
    }

Write-Host ""
Write-Host "提示: 长期容灾建议再加 rclone sync 到云盘(Google Drive / OneDrive / S3)。" -ForegroundColor DarkGray
