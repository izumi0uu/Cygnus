# Cygnus

This repository hosts the evolving Cygnus codebase for **Support Brain for SaaS**:
- the product documentation package
- the Arkon-derived substrate/runtime baseline now being internalized into Cygnus
- the emerging support-governance control-plane prototype

Start here:
- [`DESIGN.md`](./DESIGN.md) — canonical design source of truth
- [`docs/README.md`](./docs/README.md) — documentation index
- [`docs/zh/prd.md`](./docs/zh/prd.md) — 中文产品定义
- [`docs/en/prd.md`](./docs/en/prd.md) — English product definition
- [`docs/agent/en/execution-context.md`](./docs/agent/en/execution-context.md) — agent execution context

Current scope:
- product-definition alignment first
- bilingual parallel documentation
- support knowledge operating system positioning
- no GTM/pricing or deep implementation lock-in in this pass

## Docker local stack

Cygnus now ships with an Arkon-shaped local Docker stack:
- `postgres` with `pgvector`
- `redis`
- `minio`
- `migrator` (one-shot schema + MinIO bucket bootstrap job)
- `api` (`uvicorn cygnus.runtime.main:app`; `/livez` side-effect-free liveness, `/readyz` 503-gated readiness)
- `worker` (`python -m cygnus.runtime.worker`; graceful drain runner — SIGTERM publishes a `draining` heartbeat, stops claiming jobs, waits `WORKER_DRAIN_GRACE_SECONDS` for in-flight work; drains durable AI pre-review outbox intents at startup and on its recovery cron)
- `worker-skills` (`python -m cygnus.runtime.worker SkillWorkerSettings`; same drain contract)
- `frontend` (built SPA served by Nginx, reverse-proxying `/api`, `/oauth`, `/mcp`, `/.well-known`)

### Start

```bash
docker compose up --build
```

### Smoke gate

Run the local stack verification gate:

```bash
sh scripts/docker_smoke.sh
```

Useful toggles:

```bash
# keep containers up after the smoke passes
CYGNUS_SMOKE_KEEP_UP=1 sh scripts/docker_smoke.sh

# skip image rebuild if you already built the stack
CYGNUS_SMOKE_BUILD_FLAG="" sh scripts/docker_smoke.sh
```

By default the smoke gate uses isolated host ports so it does not collide with
your own local Redis/Postgres/MinIO:

```bash
# defaults used by the smoke gate
# api=18077 frontend=15173 postgres=15432 redis=16379 minio=19000/19001
sh scripts/docker_smoke.sh
```

Override them if needed:

```bash
CYGNUS_DOCKER_API_HOST_PORT=28077 \
CYGNUS_DOCKER_FRONTEND_HOST_PORT=25173 \
sh scripts/docker_smoke.sh
```

### Local endpoints

- Frontend: `http://localhost:5173` (host `:5173` maps to unprivileged container `:8080`)
- API: `http://localhost:8077`
- API health: `http://localhost:8077/health`
- MinIO API: `http://localhost:9000`
- MinIO console: `http://localhost:9001`

### Default local credentials

- Admin email: `admin@cygnus.local`
- Admin password: `admin123`

These defaults are for local development only. Runtime env keys live in:
- [`./.env.example`](./.env.example) — host-local runs
- [`./.env.docker.example`](./.env.docker.example) — compose/container shape
- `./.env.docker.local` — optional local override file for compose (git-ignored)

Boundary detail:
- the backend settings loader currently reads raw field names from `cygnus/runtime/config.py`
- there is **no** `CYGNUS_` env prefix in the current runtime config contract
- Docker overrides should go in `./.env.docker.local`, not by editing `docker-compose.yml`
- local bucket bootstrap now lives inside `cygnus/runtime/bootstrap/init_local_stack.py`, not in a separate init-sidecar
- compose host-port remapping is a **compose-layer** concern, so smoke-gate host ports are exported from the shell script instead of being read from runtime settings

## Production deployment

Production uses a separate immutable manifest: [`deploy/docker-compose.prod.yml`](./deploy/docker-compose.prod.yml). It differs deliberately from the local stack:

- **Prebuilt, digest-pinned images only** — no `build:`, no application source mounts. `api`/`worker`/`worker-skills`/`migrator` run the backend image and `frontend` runs the nginx image, both referenced as `name@sha256:...` from release metadata. Only read-only config/ops files (nginx template, security headers, worker healthcheck) and TLS secrets are mounted.
- **Only the reverse proxy is exposed** — the `frontend` service maps public host `:80`/`:443` to unprivileged container `:8080`/`:8443` (TLS termination + strict headers + same-origin `/api`, `/oauth`, `/mcp`, `/.well-known` and presigned MinIO bucket paths). Postgres, Redis, MinIO, API and workers publish no host ports.
- **Distinct app services with healthchecks and drain grace** — `api`, `worker` (default queue) and `worker-skills` each have a healthcheck (workers probe the per-role runtime heartbeat in Redis), run under the graceful drain runner (`python -m cygnus.runtime.worker <Settings>`), and get a 120s `stop_grace_period` that exceeds `worker_drain_grace_seconds`.
- **Migration job first** — the one-shot `migrator` runs `alembic upgrade head` (the `20260627_00_pre_governance_baseline` root covers empty databases) followed by `cygnus.runtime.bootstrap.ensure_storage` (settings validation + bucket ensure only — no `create_all`, no stamp, no seeding). Every app service `depends_on` it with `service_completed_successfully`; even a bare `docker compose up -d` upgrades the DB before rollout.
- **Named persistent volumes** — `cygnus-prod-postgres`, `cygnus-prod-redis`, `cygnus-prod-minio`.
- **Fail-closed inputs** — startup fails without secrets (`deploy/.env.prod`, `env_file` `required: true`), without digest-pinned release metadata (`${…:?}` interpolation), and without the TLS cert/key files (compose secrets).

### Layout

| Path | Purpose |
| --- | --- |
| `deploy/docker-compose.prod.yml` | production manifest (immutable, digest-pinned) |
| `deploy/nginx/nginx.prod.conf.template` | TLS reverse-proxy config, rendered by the nginx image entrypoint (envsubst); `CYGNUS_DOMAIN` and `MINIO_BUCKET` are substituted, nginx `$vars` are preserved |
| `deploy/nginx/security-headers.conf` | HSTS, CSP, X-Frame-Options, nosniff, referrer/permissions/COOP/CORP policies |
| `deploy/healthchecks/worker_healthcheck.py` | per-role worker healthcheck (Redis + heartbeat freshness) |
| `deploy/.env.prod.example` | template for `deploy/.env.prod` (git-ignored) — secrets and runtime settings |
| `deploy/releases/<version>.env.example` | template for per-release image digest metadata |
| `cygnus/runtime/bootstrap/ensure_storage.py` | narrow migrator step: validate MinIO settings + ensure bucket (never touches schema) |
| `scripts/prod/write-release-env.py` | generate `deploy/releases/<version>.env` from `production/image-manifest.json` (digest pins) |
| `scripts/prod/deploy.sh` | atomic deploy: validate → pull digests → stateful up → migrate → rollout → health gate |
| `scripts/prod/rollback.sh` | explicit rollback to a previous release (DB downgrade only on request) |

### First-time setup

```bash
# Run only on the protected production host/runner, never against docker-compose.yml.
cd /srv/cygnus

# 1. Runtime/TLS/delivery/capacity/recovery inputs. This file is git-ignored;
# every CHANGE_ME/REPLACE value must be replaced with a real external input.
cp deploy/.env.prod.example deploy/.env.prod
$EDITOR deploy/.env.prod

# 2. Approved non-secret Production V1 decision manifest. It binds public DNS,
# metrics CIDR, capacity and alert-threshold identity/hash, delivery endpoints/
# allowlist, HMAC secret-store reference, recovery objectives, and approvals.
cp deploy/production-inputs.example.json deploy/production-inputs.json
$EDITOR deploy/production-inputs.json

# 3. Generate immutable release metadata only from CI's certified manifest.
# It emits exact name@sha256 image refs plus the recorded commit/Alembic head.
CYGNUS_RELEASE=0.1.0
scripts/prod/write-release-env.py "$CYGNUS_RELEASE" \
  --manifest /srv/cygnus/production/image-manifest.json

# 4. Fail-closed validation before Docker is touched.
scripts/prod/deploy.sh --release "$CYGNUS_RELEASE" --dry-run
```

### Deploy / upgrade

```bash
cd /srv/cygnus
CYGNUS_RELEASE=0.1.0

# Upgrade is the only normal mutation path: validate -> pull exact digests ->
# private stateful services -> current-image migration -> rollout -> TLS JSON gates.
scripts/prod/deploy.sh --release "$CYGNUS_RELEASE"

# Read-only health proof through the actual TLS proxy. No -k is allowed.
curl --fail --resolve "${CYGNUS_DOMAIN}:443:127.0.0.1" "https://${CYGNUS_DOMAIN}/livez"
curl --fail --resolve "${CYGNUS_DOMAIN}:443:127.0.0.1" "https://${CYGNUS_DOMAIN}/readyz"
```

`deploy.sh` verifies a plain-HTTP redirect and JSON `alive`/`ready` responses
from explicit nginx `/livez` and `/readyz` proxy locations; the SPA fallback
can never make an unavailable API look healthy. `--dry-run` is the only flag;
there is intentionally no migration-skip escape hatch.

### Rollback (explicit)

```bash
scripts/prod/rollback.sh                 # to the previous recorded release
scripts/prod/rollback.sh --release 0.0.9 # to a specific older release
scripts/prod/rollback.sh --yes           # skip the confirmation prompt
```

Rollback recreates `api`/`worker`/`worker-skills`/`frontend` from the previous digest-pinned images. **Database rollback is never automatic**; migrations are forward-only in normal operation. To explicitly revert alembic-managed revisions:

```bash
scripts/prod/rollback.sh --release <prev> --downgrade <revision>
```

Caveats: `--downgrade` runs against the target (previous) image's migration chain and only reverts alembic-managed revisions — `create_all`-style table drops are not performed. Prefer a forward fix over a downgrade.

### Certification, backup, recovery, and incident commands

All commands below require the protected production runner inputs named in
[`deploy/.env.prod.example`](./deploy/.env.prod.example). They fail closed when
the host, TLS, secret-store bindings, delivery allowlist, capacity files, or
approved RPO/RTO values are absent. Do not run them from the **DEVELOPMENT ONLY**
[`docker-compose.yml`](./docker-compose.yml).

```bash
# Local development smoke only — never production evidence.
sh scripts/docker_smoke.sh

# Protected live certification: approved production input binding, real staging
# capacity/fault injection, public browser/E2E, security/failure injection, and
# persisted governed-truth reports. The workflow invokes this exact command.
CYGNUS_CERTIFICATION_ARTIFACT_DIR="$PWD/production/evidence" \
  scripts/run_live_production_certification.sh

Browser certification defaults to the locked repository runner at
`frontend/scripts/run-browser-certification.mjs`; `CYGNUS_BROWSER_E2E_RUNNER`
may replace it only with a separately approved executable. The remaining live probes are
operator-supplied. Every runner must return its native `v1` report with the exact
`release_identity` passed on the command line: full Git commit, backend and frontend
`name@sha256:` refs, and Alembic head. Git-only or semantically incomplete browser reports
are rejected.

# The underlying native staging capacity command; every threshold, route target,
# and approval reference is an external deployment input. Missing refs BLOCK.
CYGNUS_CAPACITY_GATE_INJECTION=1 uv run python scripts/load_gate.py \
  --thresholds "$CYGNUS_CAPACITY_THRESHOLDS_FILE" \
  --targets "$CYGNUS_CAPACITY_TARGETS_FILE" \
  --commit-sha "$APP_COMMIT_SHA" --image-tag "$CYGNUS_API_IMAGE" \
  --alembic-revision "$EXPECTED_ALEMBIC_HEAD" \
  --capacity-approval-ref "$CYGNUS_CAPACITY_APPROVAL_REF" \
  --capacity-thresholds-ref "$CYGNUS_CAPACITY_THRESHOLDS_REF" \
  --capacity-targets-ref "$CYGNUS_CAPACITY_TARGETS_REF" \
  --environment staging --require-runtime-identity \
  --report-out production/evidence/cygnus.capacity.report.json \
  --samples-out production/evidence/cygnus.capacity.samples.json

# Alert rules are rendered only after the production-input gate verifies the
# approved external JSON, refs, and exact file hash.
scripts/render_alert_rules.py \
  --thresholds "$CYGNUS_ALERT_THRESHOLDS_FILE" \
  --approval-ref "$CYGNUS_ALERT_APPROVAL_REF" \
  --thresholds-ref "$CYGNUS_ALERT_THRESHOLDS_REF" \
  --thresholds-sha256 "$CYGNUS_ALERT_THRESHOLDS_SHA256" \
  --output deploy/rendered/alert_rules.yml

# Encrypted production backup followed by one destructive restore into a newly
# provisioned isolated database/Redis DB/MinIO bucket. It writes native reports
# under $CYGNUS_CERTIFICATION_ARTIFACT_DIR and tears down the isolated target.
CYGNUS_CERTIFICATION_ARTIFACT_DIR="$PWD/production/evidence" \
  scripts/prod/backup_restore_drill.sh

# Explicit application rollback; schema downgrade is never implicit.
scripts/prod/rollback.sh --release <approved-previous-release>
scripts/prod/rollback.sh --release <approved-previous-release> --downgrade <alembic-revision>

# Secret values remain in the external store. Its approved runner rotates them,
# then this command redeploys the same immutable release and revalidates ingress.
scripts/prod/rotate-secrets.sh --release "$CYGNUS_RELEASE" --dry-run
scripts/prod/rotate-secrets.sh --release "$CYGNUS_RELEASE"

# Incident status is read-only. Containment requires a separately approved
# protected-runner executable; no generic stop/restart command is guessed.
scripts/prod/incident.sh status --release "$CYGNUS_RELEASE"
scripts/prod/incident.sh contain --release "$CYGNUS_RELEASE"
```

The canonical backup/restore/drill contracts are maintained in both language
tracks: [English runbook](./docs/en/backup-restore-runbook.md) and
[中文 Runbook](./docs/zh/backup-restore-runbook.md). The scheduled/manual
protected drill workflow is [`.github/workflows/backup-restore-drill.yml`](./.github/workflows/backup-restore-drill.yml); missing native report, failed check, unmeasured objective, or identity mismatch blocks release promotion.

### Reviewed image update process

Every runtime, infrastructure, and release-scanner image appears as an exact
tag-plus-index-digest in [`deploy/image-lock.json`](./deploy/image-lock.json).
To update one, choose a reviewed upstream tag, resolve its multi-architecture
index with `docker buildx imagetools inspect <reference>`, record the exact
digest/platforms in the lock, update every Dockerfile/Compose/workflow reference,
then run `scripts/image_reference_gate.py`, locked dependency gates, scans, and
the relevant smoke/certification gate. A registry lookup failure, digest drift,
or missing `linux/amd64`/`linux/arm64` manifest blocks release; never replace a
digest with a mutable tag.

### Security posture

- only public host `:80`/`:443` are published, mapped to the frontend's unprivileged container `:8080`/`:8443`; everything else stays internal to `prodnet`
- backend containers run `read_only: true`, as uid `65534`, `cap_drop: [ALL]`, `no-new-privileges`, with `/tmp` tmpfs
- frontend nginx runs as the image's unprivileged `nginx` user with `read_only: true`, bounded tmpfs for cache/run/conf, `cap_drop: [ALL]`, `no-new-privileges`, and no added or file capabilities
- TLS 1.2/1.3 with modern ciphers, HSTS, strict CSP/headers (see `deploy/nginx/security-headers.conf`)
- credentials live only in `deploy/.env.prod` (git-ignored, `required: true`) and TLS material is referenced by external path (compose secrets → `/run/secrets/`)
- Production pins pgvector `0.8.6-pg16-trixie`, Redis `7.4-alpine3.21`, and MinIO `RELEASE.2025-09-07T16-13-09Z` to reviewed multi-architecture manifest digests. Update each tag and digest together, then rerun migration, compose-smoke, backup/restore, and vulnerability gates before rollout; the local stack pins only MinIO's named release for developer reproducibility.
- MinIO presigned URLs must stay same-origin: set `MINIO_PUBLIC_ENDPOINT` to the same host as `CYGNUS_DOMAIN` (no scheme/path) so the proxy can serve the bucket path
- `TRUSTED_PROXY_IPS` is exactly the deterministic production `prodnet` CIDR (`172.30.0.0/24`); the API honors forwarded client addresses only from that immediate nginx peer, never from arbitrary internet clients.
- The production CSP is self-origin only for scripts/fonts. The SPA uses `/theme-bootstrap.js` and local assets; Google Fonts and inline scripts are intentionally absent so CSP does not silently block the console.

### Production notes

- **Presigned URLs**: with `MINIO_PUBLIC_ENDPOINT` set, the API signs URLs against `https://<domain>/<bucket>/<key>` and the nginx template routes `/<bucket>/` to MinIO. Do not point `MINIO_PUBLIC_ENDPOINT` at a different origin unless you extend the CSP (`img-src`/`connect-src`) in `deploy/nginx/security-headers.conf`.
- **Drain contract**: worker `stop_grace_period` (120s) must stay above `WORKER_DRAIN_GRACE_SECONDS` (default 30s) plus the heartbeat stop window; raise both together.
- **Migration model**: schema is owned exclusively by alembic — `20260627_00_pre_governance_baseline` is the empty-DB root that froze the pre-governance runtime schema, and later governance revisions chain from it. The production migrator runs `alembic upgrade head` then the narrow `ensure_storage` step; nothing in deploy/rollback/compose calls `create_all`, `stamp`, or admin seeding (those remain local-stack-only conveniences in `init_local_stack`).
- **No `CYGNUS_` env prefix**: `deploy/.env.prod` uses the raw runtime setting names (case-insensitive), same contract as `.env.docker.example`.
- **Release metadata**: `scripts/prod/write-release-env.py` consumes the certified `production/image-manifest.json` (schema_version 2) and refuses anything except released exact digests, the manifest's recorded Git commit, and its recorded Alembic head. It will not overwrite a release file without explicit `--force`; deployment itself accepts only `name@sha256:` references.
- **Runtime identity**: `api` and both workers receive identical observability identity (`APP_ENVIRONMENT=production`, `APP_RELEASE`, `APP_COMMIT_SHA`, `APP_IMAGE_REF`, `APP_DEPLOYMENT_ID`, optional `EXPECTED_ALEMBIC_HEAD`) per the contract in `cygnus/observability/_identity.py`; `APP_DEPLOYMENT_ID` defaults to a per-deploy timestamp when unset. Canonical names only — no `APP_VERSION`/`RELEASE_SHA` aliases (telemetry does not read them).
