# Fund Agent — frontend (Next.js 14)
#
# 多阶段构建:
#   deps     —— 仅装 node_modules,利用层缓存
#   builder  —— 跑 next build(需要 args 注入的 NEXT_PUBLIC_* 环境变量)
#   runner   —— 只拷 standalone 产物到 node:20-alpine,最终镜像 < 200 MB

# ---------- Stage 1: deps ----------
FROM node:20-alpine AS deps
WORKDIR /app
# 用 package-lock.json 走 npm ci 锁定依赖
COPY package.json package-lock.json* ./
RUN npm config set registry https://registry.npmmirror.com \
    && npm ci --no-audit --no-fund || npm install --no-audit --no-fund

# ---------- Stage 2: builder ----------
FROM node:20-alpine AS builder
WORKDIR /app

# 这些变量是 build-time 注入的,要在 next build 时存在。运行时再覆盖也行,但
# cross-environment 的 NEXT_PUBLIC_* 必须 build-time 赋值才会被静态打包。
ARG NEXT_PUBLIC_API_BASE_URL
ARG NEXT_PUBLIC_LANGGRAPH_URL
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL \
    NEXT_PUBLIC_LANGGRAPH_URL=$NEXT_PUBLIC_LANGGRAPH_URL \
    NEXT_TELEMETRY_DISABLED=1

COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

# ---------- Stage 3: runner ----------
FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# 不需要 next 整个工程,standalone 输出已经是一个自包含的 server.js
COPY --from=builder /app/.next/standalone ./
# 静态资源(Next.js 默认 .next/static,standalone 模式下未包含)
COPY --from=builder /app/.next/static ./.next/static
# public/ 如果存在(可选,没有也不报错)
COPY --from=builder /app/public ./public 2>/dev/null || true

EXPOSE 3000

# 关闭大小写敏感的 Windows 路径兼容,standalone 镜像里 Linux 文件名不受影响
CMD ["node", "server.js"]
