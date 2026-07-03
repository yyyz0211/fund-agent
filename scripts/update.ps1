#requires -Version 5.1
<#
.SYNOPSIS
    拉最新代码 + 重建容器。

.DESCRIPTION
    标准日常更新流程:
        1. git fetch + (rebase / merge / pull)
        2. docker compose up -d --build 重建变了的服务
        3. 清理悬空镜像

.EXAMPLE
    .\scripts\update.ps1
#>

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

# 0. 检查 dirty tree(未提交改动会阻碍 rebase / pull)
$gitStatus = git status --porcelain
if ($gitStatus) {
    Write-Host "[WARN] 当前有未提交的改动:" -ForegroundColor Yellow
    Write-Host $gitStatus
    $ans = Read-Host "是否继续?这里建议 'n' 先处理(y/n)"
    if ($ans -ne "y") { exit 1 }
}

# 1. 拉代码
Write-Host "[INFO] git pull ..." -ForegroundColor Cyan
git pull
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] git pull 失败。" -ForegroundColor Red
    exit 1
}

# 2. 重建容器
Write-Host "[INFO] 重建变更的镜像并重启服务 ..." -ForegroundColor Cyan
docker compose --env-file .env up -d --build
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] docker compose 启动失败。" -ForegroundColor Red
    exit 1
}

# 3. 清理悬空镜像(保留 volume,避免误删数据库)
Write-Host "[INFO] 清理 dangling 镜像 ..." -ForegroundColor Cyan
docker image prune -f | Out-Null

Write-Host ""
Write-Host "[OK] 更新完成。当前状态:" -ForegroundColor Green
docker compose ps
