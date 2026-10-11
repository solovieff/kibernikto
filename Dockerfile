# syntax=docker/dockerfile:1
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# Pinned to the uv version used for the project .venv and uv.lock.
COPY --from=ghcr.io/astral-sh/uv:0.9.17 /uv /usr/local/bin/uv

RUN useradd --create-home --uid 10001 kibernikto \
    && mkdir -p /data \
    && chown kibernikto:kibernikto /data

WORKDIR /app
# Dependencies from uv.lock first (cached layer), then the project itself.
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --frozen --no-dev --no-install-project
COPY kibernikto ./kibernikto
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

# Durable state lives in /data: file history/chat_data/media and the SQLite fallback.
ENV APP_STORAGE_FILESTORE_LOCATION=/data \
    APP_STORAGE_SQLITE_PATH=/data/kibernikto.db

USER kibernikto
WORKDIR /data
VOLUME ["/data"]

ENTRYPOINT ["kibernikto"]