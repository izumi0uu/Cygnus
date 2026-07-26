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
- `api` (`uvicorn cygnus.runtime.main:app`)
- `worker` (`arq cygnus.runtime.worker.WorkerSettings`)
- `worker-skills` (`arq cygnus.runtime.worker.SkillWorkerSettings`)
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

- Frontend: `http://localhost:5173`
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
