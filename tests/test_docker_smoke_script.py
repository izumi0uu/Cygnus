from __future__ import annotations

from pathlib import Path
import unittest


class DockerSmokeScriptTests(unittest.TestCase):
    def test_docker_smoke_script_exists_and_checks_core_runtime(self) -> None:
        path = Path("scripts/docker_smoke.sh")
        self.assertTrue(path.is_file(), "expected docker smoke script to exist")

        text = path.read_text(encoding="utf-8")
        required_fragments = [
            "docker compose up -d",
            "docker compose down -v --remove-orphans",
            "CYGNUS_DOCKER_REDIS_HOST_PORT",
            "CYGNUS_DOCKER_API_HOST_PORT",
            "CYGNUS_DOCKER_FRONTEND_HOST_PORT",
            "__CYGNUS_DEFAULT_BUILD__",
            'wait_for_url "api health" "$BASE_URL/health"',
            'wait_for_url "api detailed health" "$BASE_URL/api/health"',
            'wait_for_url "frontend" "$FRONTEND_URL"',
            "/api/auth/login",
            "/api/auth/me",
            'assert data["status"]=="healthy"',
            'assert data["database"]=="healthy"',
            'assert data["worker"]=="healthy"',
            'echo "[docker-smoke] smoke gate passed"',
        ]
        for fragment in required_fragments:
            self.assertIn(fragment, text)

    def test_repo_check_documents_shell_syntax_validation_for_smoke_script(
        self,
    ) -> None:
        text = Path("scripts/repo_check.sh").read_text(encoding="utf-8")
        self.assertIn("sh -n scripts/docker_smoke.sh", text)


if __name__ == "__main__":
    unittest.main()
