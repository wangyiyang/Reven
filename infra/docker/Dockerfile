# syntax=docker/dockerfile:1.7
FROM node:22.22.2-bookworm-slim AS node-build
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY renderer/package.json renderer/package.json
COPY web/package.json web/package.json
COPY vendor/doocs-md/config/package.json vendor/doocs-md/config/package.json
COPY vendor/doocs-md/packages/core/package.json vendor/doocs-md/packages/core/package.json
COPY vendor/doocs-md/shared/package.json vendor/doocs-md/shared/package.json
COPY vendor/doocs-md/patches/ vendor/doocs-md/patches/
RUN pnpm install --frozen-lockfile
COPY renderer/ renderer/
COPY web/ web/
COPY vendor/doocs-md/config/ vendor/doocs-md/config/
COPY vendor/doocs-md/packages/core/ vendor/doocs-md/packages/core/
COPY vendor/doocs-md/shared/ vendor/doocs-md/shared/
RUN pnpm --filter @reven/renderer build \
    && pnpm --filter @reven/web build

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS python-build
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY server/pyproject.toml server/pyproject.toml
COPY server/src/ server/src/
RUN uv sync --frozen --no-dev --all-packages

FROM python:3.12-slim-bookworm AS runtime
ARG BUNDLER_VERSION=2.5.22
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       bubblewrap build-essential ca-certificates git ruby-full tini \
    && gem install bundler -v "${BUNDLER_VERSION}" --no-document \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 10001 reven \
    && mkdir -p /app /data/jobs /srv/reven \
    && chown -R reven:reven /app /data /srv/reven
WORKDIR /app
COPY --from=python-build --chown=reven:reven /app/.venv /app/.venv
# Copy the complete Node runtime prefix so node keeps its matching shared libraries
# and runtime files instead of relying on an incompatible standalone binary.
COPY --from=node-build /usr/local/ /usr/local/
COPY --from=node-build --chown=reven:reven /app/renderer/dist /app/renderer/dist
COPY --from=node-build --chown=reven:reven /app/web/dist /app/web-dist
RUN find /app/web-dist -type f -print0 \
    | sort -z \
    | xargs -0 sha256sum \
    | sha256sum \
    | cut -d ' ' -f 1 > /app/web-dist/.release
COPY --chown=reven:reven server/migrations/ /app/server/migrations/
COPY --chown=reven:reven server/src/ /app/server/src/
COPY --chown=reven:reven infra/docker/entrypoint.sh /app/entrypoint.sh
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH="/app/server/src" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
USER reven
EXPOSE 8000
ENTRYPOINT ["/usr/bin/tini", "--", "/app/entrypoint.sh"]
