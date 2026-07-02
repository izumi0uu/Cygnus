from __future__ import annotations

from pathlib import Path
import unittest


class DockerStackRecoveryTests(unittest.TestCase):
    def test_skill_contributions_status_index_declared_once(self) -> None:
        text = Path("cygnus/runtime/database/models.py").read_text(encoding="utf-8")
        self.assertEqual(text.count('Index("ix_skill_contributions_status", "status")'), 1)
        self.assertNotIn("default=SkillContributionStatus.DRAFT.value,\n        index=True", text)

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
            "pgvector/pgvector:pg16",
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
            "cygnus.runtime.worker.WorkerSettings",
            "cygnus.runtime.worker.SkillWorkerSettings",
            "target: prod",
        ]
        for fragment in required_fragments:
            self.assertIn(fragment, text)

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

    def test_backend_and_frontend_dockerfiles_exist(self) -> None:
        backend_text = Path("Dockerfile").read_text(encoding="utf-8")
        frontend_text = Path("frontend/Dockerfile").read_text(encoding="utf-8")

        self.assertIn("python:3.12-slim", backend_text)
        self.assertIn("pip install .", backend_text)
        self.assertIn("uvicorn", backend_text)

        self.assertIn("node:22-bookworm-slim", frontend_text)
        self.assertIn("pnpm install --frozen-lockfile", frontend_text)
        self.assertIn("AS prod", frontend_text)
        self.assertIn("nginx:1.27-alpine", frontend_text)

    def test_docker_local_override_file_is_gitignored(self) -> None:
        text = Path(".gitignore").read_text(encoding="utf-8")
        self.assertIn(".env.docker.local", text)


if __name__ == "__main__":
    unittest.main()
