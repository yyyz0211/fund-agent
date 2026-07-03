#requires -Version 5.1
<#
.SYNOPSIS
    Fund Agent 一键启动(Windows / PowerShell)。

.DESCRIPTION
    1. 如果 .env 不存在,从 .env.example 复制
    2. 自动 build + up 所有服务
    3. 跟随输出日志

.EXAMPLE
    .\scripts\start.ps1
#>

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

# 0. 检查 docker 是否在跑
$dockerInfo = docker info 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] Docker daemon 没起来。请打开 Docker Desktop,等它完全启动再试。" -ForegroundColor Red
    exit 1
}

# 1. 确保 .env 存在
if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env"
        Write-Host "[INFO] .env 已从 .env.example 复制。请打开编辑,至少填 DEEPSEEK_API_KEY。" -ForegroundColor Yellow
    } else {
        Write-Host "[FAIL] .env.example 不存在,无法生成 .env。" -ForegroundColor Red
        exit 1
    }
}

# 2. 启动
Write-Host "[INFO] 正在 build + 启动所有服务 ..." -ForegroundColor Cyan
docker compose --env-file .env up -d --build
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] docker compose 启动失败,看看上面输出。" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "[OK] 容器已起。状态:" -ForegroundColor Green
docker compose ps

Write-Host ""
Write-Host "查看实时日志:`tdocker compose logs -f`" -ForegroundColor DarkGray
Write-Host "停止:`tdocker compose down`" -ForegroundColor DarkGray
