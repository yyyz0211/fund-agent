# Fund Agent — LangGraph QA server
#
# 与 backend 共用 Python 3.11 依赖,但额外需要 `langgraph-cli[inmem]`。
# 与 backend 容器间通过 Docker 网络内的 `backend:8000` 互相访问。

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 复用 backend 的依赖列表(里面有 langgraph-prebuilt 等)
COPY backend/requirements.txt /tmp/req.txt
RUN pip install -r /tmp/req.txt \
    && pip install "langgraph-cli[inmem]" psycopg2-binary

# 复制 backend 源码(graph / tools / config 等模块)和 langgraph 配置。
COPY backend ./backend
COPY langgraph ./langgraph
COPY langgraph.json /app/langgraph.json

EXPOSE 2024

# 开发模式即可(单人访问);如果需要持久化 checkpointer,LANGGRAPH_DATABASE_URL
# 通过 docker-compose 注入,LangGraph 会自动用 Postgres 替换默认内存存储。
CMD ["langgraph", "dev", "--host", "0.0.0.0", "--port", "2024"]
