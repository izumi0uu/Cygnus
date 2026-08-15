# syntax=docker/dockerfile:1
#
# Cygnus frontend image — immutable, locked, non-root.
#
# - Dependencies are installed with `npm ci` against package-lock.json; the
#   prod stage ships only the built SPA.
# - The nginx master runs as the unprivileged `nginx` user on unprivileged
#   container ports; pid/log/cache paths are redirected under nginx-writable
#   directories, so the image needs no Linux capabilities.
# - Build identity is injected by .github/workflows/release.yml; local builds
#   fall back to `unknown` so they are never mistaken for release artifacts.

ARG NODE_IMAGE=node:22.15.1-bookworm-slim@sha256:ec318fe0dc46b56bcc1ca42a202738aeb4f3e347a7b4dd9f9f1df12ea7aa385a
ARG NGINX_IMAGE=nginx:1.30.4-alpine3.24@sha256:97d490c12ba55b4946b01546d1c3ed324e8d41ab1c9fcb2a616aa470620e5b46

# Build identity (injected by the release workflow; local builds stay traceable).
ARG GIT_SHA=unknown
ARG GIT_REF=unknown
ARG BUILD_DATE=unknown
ARG VERSION=0.1.0

# ---------------------------------------------------------------------------
# build: install the locked frontend dependency graph, then build the SPA.
# ---------------------------------------------------------------------------
FROM ${NODE_IMAGE} AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY . .

RUN npm run build

# ---------------------------------------------------------------------------
# prod: non-root nginx serving the built SPA.
# ---------------------------------------------------------------------------
FROM ${NGINX_IMAGE} AS prod

ARG GIT_SHA
ARG GIT_REF
ARG BUILD_DATE
ARG VERSION

LABEL org.opencontainers.image.title="cygnus-frontend" \
      org.opencontainers.image.description="Cygnus operation-console SPA (Vite build served by nginx)." \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.source="https://github.com/izumi0uu/Cygnus" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.ref.name="${GIT_REF}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.licenses="UNLICENSED" \
      io.cygnus.image.immutable="true"

RUN sed -i \
      -e 's#pid        /run/nginx.pid;#pid        /tmp/nginx.pid;#' \
      -e 's#^error_log.*#error_log /dev/stderr warn;#' \
      -e 's#^[[:space:]]*access_log.*#access_log /dev/stdout main;#' \
      /etc/nginx/nginx.conf
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

USER nginx

EXPOSE 8080 8443

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["wget", "-q", "-O", "/dev/null", "http://127.0.0.1:8080/health"]

# The base nginx config redirects its pid under /tmp and logs to stdout/stderr.
# Production mounts only bounded tmpfs cache/config paths before launching this
# unprivileged process.
CMD ["nginx", "-g", "daemon off;"]
