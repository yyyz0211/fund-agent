# Fund Agent — backend (FastAPI + AKShare + LangGraph tools)
# 基于 python:3.11-slim;USTC / 阿里云镜像源已写到容器内以加速 pip 装包。
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/

# akshare 拉天天基金 / 东财数据时可能用到这些系统库(实际只硬需 gcc 编译 psycopg2-binary,
# 但保留 build-essential 与 libpq-dev 能在将来装额外原生扩展时不卡壳)。
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先 COPY requirements 单独成层,利用 docker 缓存:依赖不变就不重装。
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install -r ./backend/requirements.txt psycopg2-binary

# 复制后端源代码。tests/ 不需要进镜像。
COPY backend ./backend
COPY langgraph ./langgraph

EXPOSE 8000

# 启动时先跑一次 init_db(幂等,可重复),再起 uvicorn。
# 健康检查在 docker-compose 里定义为 GET /api/health,这里不重复做。
CMD ["sh", "-c", "python -m backend.db.init_db && uvicorn backend.api.app:app --host 0.0.0.0 --port 8000"]
