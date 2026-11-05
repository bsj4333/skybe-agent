FROM node:22-slim AS web

WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web ./
RUN npm run build

FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.10 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock README.md .python-version ./
COPY src ./src
RUN uv sync --frozen --no-dev

COPY skive ./skive
COPY ui_mockup ./ui_mockup
COPY migrations ./migrations
COPY deploy ./deploy
COPY --from=web /web/out ./web/out

CMD ["sh", "deploy/start.sh"]
