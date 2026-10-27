# syntax=docker/dockerfile:1.7

# Development-ready image for the Kizuna Django API.
#
# Build:
#   docker build -t kizuna:dev .
#
# Run the Django development server:
#   docker run --rm -p 8000:8000 --env-file .env kizuna:dev
#
# Apply migrations (Postgres must be reachable):
#   docker run --rm --env-file .env kizuna:dev python manage.py migrate
#
# Run the production WSGI server instead of the dev server:
#   docker run --rm -p 8000:8000 --env-file .env kizuna:dev \
#     gunicorn kizuna.wsgi:application --bind 0.0.0.0:8000 --workers 3
#
# The image is intentionally environment-agnostic: secrets and provider
# credentials are supplied at runtime, never baked into the image.

ARG PYTHON_VERSION=3.12
ARG BUILDKIT_INLINE_CACHE=1

# ─────────────────────────────────────────────────────────────
# Build stage: compile/install Python dependencies into a venv
# ─────────────────────────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:${PATH}"

# build-essential and libpq-dev are only needed while installing packages;
# they stay in this discarded stage. psycopg2-binary ships wheels, but source
# builds (and any future source-only dependency) still work.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv "${VIRTUAL_ENV}"

WORKDIR /build
COPY requirements.txt ./

# Cache mounts keep rebuilds fast without bloating the final image.
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install -r requirements.txt \
    && python -m pip check

# ─────────────────────────────────────────────────────────────
# Runtime stage
# ─────────────────────────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim-bookworm AS development

ARG UID=1000
ARG GID=1000

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_SETTINGS_MODULE=kizuna.settings \
    PYTHONPATH=/app \
    HOME=/home/app \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:${PATH}"

# libpq5 for psycopg2; passwd guarantees useradd/groupadd exist on slim images.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpq5 \
        passwd \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid "${GID}" app \
    && useradd --uid "${UID}" --gid app --create-home --shell /bin/bash app \
    && mkdir -p /app/static /app/media \
    && chown -R app:app /app

COPY --from=builder --chown=app:app /opt/venv /opt/venv

WORKDIR /app

# Source is copied for a self-contained dev image. For live-editing, mount the
# repository over /app (the copied source then acts as a fallback).
COPY --chown=app:app . .

USER app

EXPOSE 8000
STOPSIGNAL SIGTERM

LABEL org.opencontainers.image.title="kizuna" \
      org.opencontainers.image.description="Kizuna mobile-money collection API (development image)"

# The default command targets development (auto-reload, static files served by
# runserver). Override it with the gunicorn command above for production-like
# runs. Migrations are intentionally not run automatically: when using an
# external database, run `python manage.py migrate` explicitly so startup does
# not fail or race when Postgres is not ready yet.
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
