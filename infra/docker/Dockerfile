# syntax=docker/dockerfile:1.7
FROM node:22.22.2-bookworm-slim@sha256:9f6d5975c7dca860947d3915877f85607946403fc55349f39b4bc3688448bb6e AS node-build
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY web/package.json web/package.json
RUN pnpm install --frozen-lockfile
COPY web/ web/
COPY scripts/licenses/collect-js.mjs /tmp/collect-js.mjs
COPY licenses/supplemental/javascript/ licenses/supplemental/javascript/
RUN pnpm --filter @reven/web build \
    && node /tmp/collect-js.mjs /app /app/third-party-js \
    && mkdir -p /app/web/dist/licenses/javascript \
    && cp -R /app/third-party-js/. /app/web/dist/licenses/javascript/
COPY LICENSE THIRD_PARTY_NOTICES.md /app/web/dist/licenses/

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim@sha256:e5b65587bce7de595f299855d7385fe7fca39b8a74baa261ba1b7147afa78e58 AS python-build
WORKDIR /app
COPY pyproject.toml uv.lock LICENSE ./
COPY server/pyproject.toml server/pyproject.toml
COPY server/src/ server/src/
RUN uv sync --frozen --no-dev --all-packages

FROM python:3.12-slim-bookworm@sha256:d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b AS runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tini util-linux \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*
# /data/dsh is the writable DSH_HOME for the embedded dsh agent (profiles, session logs).
RUN useradd --create-home --uid 10001 reven \
    && mkdir -p /app /data/dsh /srv/reven \
    && chown -R reven:reven /app /data /srv/reven
WORKDIR /app
COPY --from=python-build --chown=reven:reven /app/.venv /app/.venv
COPY LICENSE THIRD_PARTY_NOTICES.md /opt/reven-licenses/
COPY licenses/supplemental/ /opt/reven-licenses/supplemental/
COPY --from=node-build /app/third-party-js/ /opt/reven-licenses/javascript/
COPY scripts/licenses/collect-runtime.py /tmp/collect-runtime.py
RUN /app/.venv/bin/python /tmp/collect-runtime.py python /opt/reven-licenses/python /opt/reven-licenses/supplemental/python \
    && /app/.venv/bin/python /tmp/collect-runtime.py system /opt/reven-licenses/system \
    && rm /tmp/collect-runtime.py
COPY --from=node-build --chown=reven:reven /app/web/dist /app/web-dist
RUN find /app/web-dist -type f -print0 \
    | sort -z \
    | xargs -0 sha256sum \
    | sha256sum \
    | cut -d ' ' -f 1 > /app/web-dist/.release
COPY --chown=reven:reven server/migrations/ /app/server/migrations/
COPY --chown=reven:reven server/src/ /app/server/src/
COPY --chown=reven:reven infra/docker/entrypoint.sh /app/entrypoint.sh
# Immutable deployment data exported by scripts/deploy_reven.sh. Keep this path stable.
COPY infra/ /opt/reven-release/infra/
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH="/app/server/src" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DSH_HOME=/data/dsh
USER reven
EXPOSE 8000
ENTRYPOINT ["/usr/bin/tini", "--", "/app/entrypoint.sh"]
