# syntax=docker/dockerfile:1
# Root Dockerfile, but the code is cloned from git (deploy.conf) instead of COPY. Built by scripts/rebuild.sh -b.
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# git + ssh for the clone below.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git openssh-client \
    && rm -rf /var/lib/apt/lists/*

# Pinned to the uv version used for the project .venv and uv.lock.
COPY --from=ghcr.io/astral-sh/uv:0.9.17 /uv /usr/local/bin/uv

RUN useradd --create-home --uid 10001 kibernikto \
    && mkdir -p /data \
    && chown kibernikto:kibernikto /data

# REPO and BRANCH come from tg_bots/<bot>/deploy.conf; CACHE_DATE changes on every rebuild so the clone is never cached.
ARG REPO
ARG BRANCH=main
ARG CACHE_DATE=reset_cache

# Instead of COPY: clone with the deploy key, record the commit for update.sh, drop .git.
RUN --mount=type=secret,id=deploy_key,mode=0400 \
    --mount=type=secret,id=known_hosts \
    GIT_SSH_COMMAND="ssh -i /run/secrets/deploy_key -o IdentitiesOnly=yes -o UserKnownHostsFile=/run/secrets/known_hosts -o StrictHostKeyChecking=yes" \
    git clone --depth=1 --single-branch --branch "$BRANCH" "$REPO" /app \
    && git -C /app rev-parse HEAD > /app/REVISION \
    && rm -rf /app/.git

WORKDIR /app
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

# Durable state lives in /data: file history/chat_data/media and the SQLite fallback.
ENV APP_STORAGE_FILESTORE_LOCATION=/data \
    APP_STORAGE_SQLITE_PATH=/data/kibernikto.db

USER kibernikto
WORKDIR /data
VOLUME ["/data"]

ENTRYPOINT ["kibernikto"]
