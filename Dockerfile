# syntax=docker/dockerfile:1
#
# Cygnus backend image — immutable, locked, non-root.
#
# - Every Python dependency is resolved from uv.lock (`uv sync --frozen`);
#   unconstrained `pip install .` is never used.
# - The runtime stage ships only the pre-built virtualenv: no toolchain, no
#   apt caches, and an unprivileged `cygnus` user (uid 10001).
# - Build identity is injected by .github/workflows/release.yml; local builds
#   fall back to `unknown` so they are never mistaken for release artifacts.

# Build identity (injected by the release workflow; local builds stay traceable).
ARG GIT_SHA=unknown
ARG GIT_REF=unknown
ARG BUILD_DATE=unknown
ARG VERSION=0.1.0

# ---------------------------------------------------------------------------
# deps: resolve the locked dependency graph exactly once.
# ---------------------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:0.9.11@sha256:5aa820129de0a600924f166aec9cb51613b15b68f1dcd2a02f31a500d2ede568 AS uv

FROM python:3.12.14-slim-bookworm@sha256:a116514e19457bcb7af7efe9c3dd0b9b71e85b317694e7882a1c52aa15a78134 AS deps

COPY --from=uv /uv /uvx /bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/cygnus/venv

WORKDIR /build

# Compiler toolchain for any source distribution that lacks a manylinux wheel
# for this platform. Not carried into the runtime image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

# Resolve the full locked graph before the source tree is copied, so source
# changes never re-resolve dependencies.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project

COPY cygnus ./cygnus
COPY alembic.ini ./
COPY migrations ./migrations
# Install the project itself into the same locked environment.
RUN uv sync --frozen --no-editable

# ---------------------------------------------------------------------------
# runtime: slim, non-root, self-describing.
# ---------------------------------------------------------------------------
FROM python:3.12.14-slim-bookworm@sha256:a116514e19457bcb7af7efe9c3dd0b9b71e85b317694e7882a1c52aa15a78134 AS runtime

ARG GIT_SHA
ARG GIT_REF
ARG BUILD_DATE
ARG VERSION

LABEL org.opencontainers.image.title="cygnus-backend" \
      org.opencontainers.image.description="Support-domain core for the Cygnus support knowledge operating system." \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.source="https://github.com/izumi0uu/Cygnus" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.ref.name="${GIT_REF}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.licenses="UNLICENSED" \
      io.cygnus.image.immutable="true"

ENV PATH="/opt/cygnus/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY --from=deps /opt/cygnus/venv /opt/cygnus/venv
COPY --from=deps /build/alembic.ini ./
COPY --from=deps /build/migrations ./migrations
COPY deploy/healthchecks/worker_healthcheck.py /opt/cygnus/worker_healthcheck.py

# Unprivileged runtime identity — created with plain file entries so the
# image never depends on a `useradd`/`passwd` package being present.
RUN echo 'cygnus:x:10001:10001::/app:/usr/sbin/nologin' >> /etc/passwd \
    && echo 'cygnus:x:10001:' >> /etc/group \
    && chown -R 10001:10001 /app

USER 10001:10001

EXPOSE 8077

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8077/health', timeout=3).read()"]

CMD ["uvicorn", "cygnus.runtime.main:app", "--host", "0.0.0.0", "--port", "8077"]
