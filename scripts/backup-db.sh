#!/usr/bin/env bash
# Fund Agent — Postgres 备份 (Linux / macOS)
# 用法: ./scripts/backup-db.sh [keep_days]
set -euo pipefail

KEEP_DAYS="${1:-30}"
CONTAINER_NAME="${CONTAINER_NAME:-fund-postgres}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

# 从 .env 读配置(如果存在)
if [ -f .env ]; then
    POSTGRES_DB="$(grep '^POSTGRES_DB=' .env | cut -d'=' -f2-)"
    POSTGRES_USER="$(grep '^POSTGRES_USER=' .env | cut -d'=' -f2-)"
    POSTGRES_PASSWORD="$(grep '^POSTGRES_PASSWORD=' .env | cut -d'=' -f2-)"
fi
: "${POSTGRES_USER:?need POSTGRES_USER in .env or env}"
: "${POSTGRES_DB:?need POSTGRES_DB in .env or env}"

mkdir -p backups
TS="$(date +%Y%m%d_%H%M%S)"
OUT="backups/fund_${TS}.sql"

echo "[INFO] 备份 $POSTGRES_DB → $OUT"
docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" "$CONTAINER_NAME" \
    pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-privileges \
    > "$OUT"

# 校验
SIZE=$(wc -c < "$OUT")
if [ "$SIZE" -lt 100 ]; then
    echo "[FAIL] 备份异常小($SIZE 字节),内容:"
    head -n 20 "$OUT"
    exit 1
fi

echo "[OK] 备份完成: $OUT ($SIZE 字节)"

# 清理过期
find backups -maxdepth 1 -type f -name "fund_*.sql" -mtime +"$KEEP_DAYS" -print -delete
echo "[INFO] 已清理 $KEEP_DAYS 天前的备份"
