# syntax=docker/dockerfile:1.7

ARG PYTHON_VERSION=3.11-slim
ARG NODE_VERSION=24-bookworm-slim

# ---------------------------------------------------------------------------
# nexus-api
# ---------------------------------------------------------------------------
# Runtime image for nexus-api only. PostgreSQL, MinIO, MinerU, LiteLLM and
# embedding services are external runtime dependencies configured by env vars.

FROM python:${PYTHON_VERSION} AS nexus-api

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    PATH="/root/.local/bin:/app/nexus-api/.venv/bin:${PATH}"

WORKDIR /app

COPY docker/bin/uv /usr/local/bin/uv

COPY nexus-app/pyproject.toml nexus-app/uv.lock ./nexus-app/
COPY nexus-api/pyproject.toml nexus-api/uv.lock ./nexus-api/
COPY nexus-app ./nexus-app
COPY nexus-api ./nexus-api
COPY config ./config

WORKDIR /app/nexus-api

RUN uv sync --frozen --no-dev

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "nexus_api.main:app", "--host", "0.0.0.0", "--port", "8000"]


# ---------------------------------------------------------------------------
# nexus-console
# ---------------------------------------------------------------------------

FROM node:${NODE_VERSION} AS nexus-console-builder

WORKDIR /app/nexus-console

COPY nexus-console/package.json nexus-console/package-lock.json ./
RUN npm ci

COPY nexus-console ./
RUN npm run build


FROM node:${NODE_VERSION} AS nexus-console

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000

WORKDIR /app/nexus-console

COPY --from=nexus-console-builder /app/nexus-console/package.json ./package.json
COPY --from=nexus-console-builder /app/nexus-console/package-lock.json ./package-lock.json
COPY --from=nexus-console-builder /app/nexus-console/.next ./.next
COPY --from=nexus-console-builder /app/nexus-console/public ./public
COPY --from=nexus-console-builder /app/nexus-console/node_modules ./node_modules
COPY --from=nexus-console-builder /app/nexus-console/next.config.ts ./next.config.ts

EXPOSE 3000

CMD ["./node_modules/.bin/next", "start", "--hostname", "0.0.0.0", "--port", "3000"]
