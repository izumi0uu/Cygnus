from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock


class DockerStackRecoveryTests(unittest.TestCase):
    def test_skill_contributions_status_index_declared_once(self) -> None:
        text = Path("cygnus/runtime/database/models.py").read_text(encoding="utf-8")
        self.assertEqual(
            text.count('Index("ix_skill_contributions_status", "status")'), 1
        )
        self.assertNotIn(
            "default=SkillContributionStatus.DRAFT.value,\n        index=True", text
        )

    def test_root_env_example_matches_runtime_settings_field_names(self) -> None:
        text = Path(".env.example").read_text(encoding="utf-8")

        required_keys = [
            "database_url=",
            "secret_key=",
            "default_admin_email=",
            "default_admin_password=",
            "mcp_token_pepper=",
            "minio_endpoint=",
            "minio_public_endpoint=",
            "minio_access_key=",
            "minio_secret_key=",
            "minio_bucket=",
            "minio_secure=",
            "cors_origins=",
            "portal_base_url=",
            "redis_host=",
            "redis_port=",
            "redis_db=",
        ]
        for key in required_keys:
            self.assertIn(key, text)

        self.assertNotIn("CYGNUS_APP_ENV", text)
        self.assertNotIn("CYGNUS_SECRET_KEY", text)
        self.assertNotIn("CYGNUS_CORS_ALLOWED_ORIGINS", text)

    def test_compose_stack_covers_runtime_api_worker_and_infra(self) -> None:
        text = Path("docker-compose.yml").read_text(encoding="utf-8")

        required_fragments = [
            "postgres:",
            "pgvector/pgvector:0.8.6-pg16-trixie@sha256:c8483555ce48101872f888c1df8a895ff689d6c7c7a5f7ac266475f9dfe89e0b",
            "CYGNUS_DOCKER_POSTGRES_HOST_PORT",
            "redis:",
            "CYGNUS_DOCKER_REDIS_HOST_PORT",
            "minio:",
            "CYGNUS_DOCKER_MINIO_API_HOST_PORT",
            "migrator:",
            "api:",
            "CYGNUS_DOCKER_API_HOST_PORT",
            "worker:",
            "worker-skills:",
            "frontend:",
            "CYGNUS_DOCKER_FRONTEND_HOST_PORT",
            ".env.docker.example",
            ".env.docker.local",
            "cygnus.runtime.bootstrap.init_local_stack",
            'command: ["python", "-m", "cygnus.runtime.worker"]',
            'command: ["python", "-m", "cygnus.runtime.worker", "SkillWorkerSettings"]',
            "SkillWorkerSettings",
            "target: prod",
        ]
        for fragment in required_fragments:
            self.assertIn(fragment, text)

    def test_production_and_local_infrastructure_images_are_locked(self) -> None:
        production = Path("deploy/docker-compose.prod.yml").read_text(encoding="utf-8")
        local = Path("docker-compose.yml").read_text(encoding="utf-8")
        lock = Path("deploy/image-lock.json").read_text(encoding="utf-8")
        expected_refs = (
            "pgvector/pgvector:0.8.6-pg16-trixie@sha256:c8483555ce48101872f888c1df8a895ff689d6c7c7a5f7ac266475f9dfe89e0b",
            "redis:7.4-alpine3.21@sha256:e7723ff73d963f5cc6d9c4643ea3d989527a402a319239054e9472a7fb9219a2",
            "minio/minio:RELEASE.2025-09-07T16-13-09Z@sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e",
        )
        for reference in expected_refs:
            self.assertIn(f"image: {reference}", production)
            self.assertIn(f"image: {reference}", local)
            self.assertIn(reference, lock)
        self.assertNotIn(":latest", production)

    def test_bootstrap_module_creates_vector_extension_and_tables(self) -> None:
        script = Path("cygnus/runtime/bootstrap/init_local_stack.py")
        self.assertTrue(script.is_file())

        text = script.read_text(encoding="utf-8")
        self.assertIn("CREATE EXTENSION IF NOT EXISTS vector", text)
        self.assertIn("Base.metadata.create_all", text)
        self.assertIn("oauth_models", text)
        self.assertIn("create_engine_from_settings", text)
        self.assertIn("StorageService", text)
        self.assertIn("ensure_bucket", text)

    def test_migration_config_prefers_runtime_working_directory(self) -> None:
        # Installed-package layout: module ancestry points into site-packages,
        # so the migration root must come from the runtime working directory
        # (the image's WORKDIR /app) that ships alembic.ini + migrations/.
        # No source-package duplication is assumed in the runtime image.
        from cygnus.runtime.bootstrap import init_local_stack

        class _Settings:
            database_url = "postgresql+asyncpg://cygnus:cygnus@runtime/cygnus"

        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp) / "app"
            (workdir / "migrations").mkdir(parents=True)
            (workdir / "alembic.ini").write_text(
                "[alembic]\nscript_location = migrations\n", encoding="utf-8"
            )

            with mock.patch.object(init_local_stack.Path, "cwd", return_value=workdir):
                config = init_local_stack._migration_config(_Settings())

        self.assertEqual(config.config_file_name, str(workdir / "alembic.ini"))
        self.assertEqual(
            config.get_main_option("script_location"), str(workdir / "migrations")
        )
        self.assertEqual(config.attributes["database_url"], _Settings.database_url)

    def test_migration_config_falls_back_to_source_checkout_root(self) -> None:
        from cygnus.runtime.bootstrap import init_local_stack

        class _Settings:
            database_url = "postgresql+asyncpg://cygnus:cygnus@source/cygnus"

        empty_workdir = Path("/nonexistent/cygnus-runtime-workdir")
        with mock.patch.object(
            init_local_stack.Path, "cwd", return_value=empty_workdir
        ):
            config = init_local_stack._migration_config(_Settings())

        repository_root = Path(init_local_stack.__file__).resolve().parents[3]
        self.assertEqual(config.config_file_name, str(repository_root / "alembic.ini"))
        self.assertEqual(
            config.get_main_option("script_location"),
            str(repository_root / "migrations"),
        )
        self.assertEqual(config.attributes["database_url"], _Settings.database_url)

    def test_migration_config_raises_without_runtime_or_source_assets(self) -> None:
        from cygnus.runtime.bootstrap import init_local_stack

        empty_workdir = Path("/nonexistent/cygnus-runtime-workdir")
        fake_module = (
            "/nonexistent/site-packages/cygnus/runtime/bootstrap/init_local_stack.py"
        )
        with (
            mock.patch.object(init_local_stack.Path, "cwd", return_value=empty_workdir),
            mock.patch.object(init_local_stack, "__file__", fake_module),
        ):
            with self.assertRaises(RuntimeError) as raised:
                init_local_stack._resolve_migration_root()

        message = str(raised.exception)
        self.assertIn("alembic.ini", message)
        self.assertIn("migrations", message)
        self.assertIn(str(empty_workdir), message)

    def test_readiness_resolves_migration_assets_from_runtime_workdir(self) -> None:
        from cygnus.runtime import readiness

        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp) / "app"
            versions = workdir / "migrations" / "versions"
            versions.mkdir(parents=True)
            (workdir / "alembic.ini").write_text(
                "[alembic]\nscript_location = migrations\n", encoding="utf-8"
            )
            (versions / "head.py").write_text(
                'revision = "runtime_head"\ndown_revision = None\n', encoding="utf-8"
            )

            readiness.expected_alembic_heads.cache_clear()
            with mock.patch.object(readiness.Path, "cwd", return_value=workdir):
                heads = readiness.expected_alembic_heads()
            readiness.expected_alembic_heads.cache_clear()

        self.assertEqual(heads, frozenset({"runtime_head"}))

    def test_backend_image_ships_worker_healthcheck(self) -> None:
        backend_text = Path("Dockerfile").read_text(encoding="utf-8")
        compose_text = Path("docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn(
            "COPY deploy/healthchecks/worker_healthcheck.py /opt/cygnus/worker_healthcheck.py",
            backend_text,
        )
        self.assertIn(
            '["CMD", "python", "/opt/cygnus/worker_healthcheck.py", "default"]',
            compose_text,
        )
        self.assertIn(
            '["CMD", "python", "/opt/cygnus/worker_healthcheck.py", "skills"]',
            compose_text,
        )

    def test_frontend_proxy_can_be_overridden_for_docker_networking(self) -> None:
        text = Path("frontend/vite.config.ts").read_text(encoding="utf-8")

        self.assertIn("process.env.VITE_API_PROXY_TARGET", text)
        self.assertIn("http://127.0.0.1:8077", text)

    def test_frontend_nginx_proxies_runtime_surfaces(self) -> None:
        text = Path("frontend/nginx.conf").read_text(encoding="utf-8")

        required_fragments = [
            "proxy_pass http://api:8077/health;",
            "location ^~ /api/",
            "location ^~ /oauth/",
            "location ^~ /mcp/",
            "location ^~ /.well-known/",
            "try_files $uri $uri/ /index.html;",
        ]
        for fragment in required_fragments:
            self.assertIn(fragment, text)

    def test_production_nginx_health_routes_cannot_fall_back_to_spa(self) -> None:
        text = Path("deploy/nginx/nginx.prod.conf.template").read_text(encoding="utf-8")
        for route in ("/health", "/livez", "/readyz"):
            self.assertIn(f"location = {route}", text)
            self.assertIn(f"proxy_pass http://api:8077{route};", text)
        self.assertIn(
            "TRUSTED_PROXY_IPS=172.30.0.0/24",
            Path("deploy/.env.prod.example").read_text(encoding="utf-8"),
        )
        self.assertIn(
            "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;", text
        )
        helper = Path("scripts/prod/lib.sh").read_text(encoding="utf-8")
        self.assertIn(
            "TRUSTED_PROXY_IPS must be the deterministic narrow prodnet CIDR", helper
        )

    def test_frontend_document_is_compatible_with_production_csp(self) -> None:
        text = Path("frontend/index.html").read_text(encoding="utf-8")
        self.assertNotIn("fonts.googleapis.com", text)
        self.assertNotIn("fonts.gstatic.com", text)
        self.assertNotIn("<script>", text)
        self.assertIn('<script src="/theme-bootstrap.js"></script>', text)
        self.assertIn('<script type="module" src="/src/main.tsx"></script>', text)

    def test_backend_and_frontend_dockerfiles_are_locked_and_nonroot(self) -> None:
        backend_text = Path("Dockerfile").read_text(encoding="utf-8")
        frontend_text = Path("frontend/Dockerfile").read_text(encoding="utf-8")

        self.assertIn("python:3.12.14-slim-bookworm@sha256:", backend_text)
        self.assertIn("ghcr.io/astral-sh/uv:0.9.11@sha256:", backend_text)
        self.assertIn("uv sync --frozen", backend_text)
        self.assertIn("uvicorn", backend_text)
        self.assertIn("USER 10001:10001", backend_text)
        self.assertIn('io.cygnus.image.immutable="true"', backend_text)

        self.assertIn("node:22.15.1-bookworm-slim@sha256:", frontend_text)
        self.assertIn("nginx:1.27.5-alpine@sha256:", frontend_text)
        self.assertIn("package-lock.json", frontend_text)
        self.assertIn("npm ci --no-audit --no-fund", frontend_text)
        self.assertIn("AS prod", frontend_text)
        self.assertIn("USER nginx", frontend_text)
        self.assertIn("setcap cap_net_bind_service=+ep /usr/sbin/nginx", frontend_text)
        self.assertIn("pid        /tmp/nginx.pid;", frontend_text)
        self.assertIn('CMD ["nginx", "-g", "daemon off;"]', frontend_text)
        self.assertNotIn("daemon off; pid /tmp/nginx.pid;", frontend_text)
        self.assertIn('io.cygnus.image.immutable="true"', frontend_text)

    def test_docker_local_override_file_is_gitignored(self) -> None:
        text = Path(".gitignore").read_text(encoding="utf-8")
        self.assertIn(".env.docker.local", text)


if __name__ == "__main__":
    unittest.main()
