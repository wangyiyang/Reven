# Reven — 多 target Dockerfile
# app / worker 共享同一镜像（仅 CMD 不同）
# bot 为独立轻量镜像

# ============================================================
# Stage 0: base — 安装 uv 与系统依赖
# ============================================================
FROM python:3.12-slim AS base

ENV \
    UV_SYSTEM_PYTHON=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.6 /uv /uvx /bin/

WORKDIR /app

# ============================================================
# Stage 1: server-deps — 安装 server + bot 共有依赖
# ============================================================
FROM base AS server-deps

COPY pyproject.toml uv.lock /app/
COPY server/pyproject.toml /app/server/
COPY packages/ /app/packages/

RUN uv sync --frozen --no-dev --group server

COPY server/src/ /app/server/src/

# ============================================================
# Stage 2: app — FastAPI 入口
# ============================================================
FROM server-deps AS app

EXPOSE 8000
CMD ["uvicorn", "reven.entrypoints.api:create_app", "--host", "0.0.0.0", "--port", "8000"]

# ============================================================
# Stage 3: worker — 队列消费入口
# ============================================================
FROM server-deps AS worker

CMD ["python", "-m", "reven.entrypoints.worker"]

# ============================================================
# Stage 4: bot — 独立轻量镜像
# ============================================================
FROM base AS bot

COPY pyproject.toml uv.lock /app/
COPY bot/pyproject.toml /app/bot/
COPY packages/ /app/packages/

RUN uv sync --frozen --no-dev --group bot

COPY bot/src/ /app/bot/src/

CMD ["python", "-m", "reven_bot"]
