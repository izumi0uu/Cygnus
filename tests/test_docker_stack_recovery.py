from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import re
import tempfile
import subprocess
import sys
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

    def test_production_operator_compose_helpers_are_fail_closed(self) -> None:
        helper = Path("scripts/prod/lib.sh").read_text(encoding="utf-8")

        def function_body(name: str) -> str:
            match = re.search(rf"(?ms)^{re.escape(name)}\(\) \{{\n(.*?)^\}}$", helper)
            if match is None:
                raise AssertionError(f"missing production shell helper: {name}")
            return match.group(1)

        validate_body = function_body("validate_compose")
        self.assertEqual(
            [line.strip() for line in validate_body.strip().splitlines()],
            [
                'command -v docker >/dev/null 2>&1 || die "docker is required for production operations"',
                '"${COMPOSE[@]}" version >/dev/null 2>&1 || die "Docker Compose v2 is required for production operations"',
                '"${COMPOSE[@]}" config --quiet || die "production Compose manifest failed to resolve: $COMPOSE_FILE"',
            ],
        )

        pull_body = function_body("compose_pull")
        self.assertEqual(pull_body.strip(), '"${COMPOSE[@]}" pull')
        self.assertIn(
            'COMPOSE=(docker compose --project-name "$COMPOSE_PROJECT_NAME" '
            '--project-directory "$DEPLOY_DIR" -f "$COMPOSE_FILE" '
            '--env-file "$PROD_ENV_FILE")',
            helper,
        )
        self.assertIn(
            'PROD_ENV_FILE="${CYGNUS_PRODUCTION_ENV_FILE:-$DEPLOY_DIR/.env.prod}"',
            helper,
        )

        quiesce_body = function_body("compose_quiesce_backend")
        resume_body = function_body("compose_resume_quiesced_backend")
        self.assertIn(
            '"${COMPOSE[@]}" ps --services --filter status=running '
            '"${PRODUCTION_BACKEND_SERVICES[@]}"',
            quiesce_body,
        )
        self.assertIn(
            '"${COMPOSE[@]}" stop "${QUIESCED_BACKEND_SERVICES[@]}"',
            quiesce_body,
        )
        quiesced_resume_order = (
            '"${COMPOSE[@]}" start "${ingress_services[@]}"',
            "compose_wait_for_delivery_consumer",
            'verify_delivery_ingress "$CYGNUS_DOMAIN"',
            '"${COMPOSE[@]}" start "${worker_services[@]}"',
            'verify_ingress "$CYGNUS_DOMAIN"',
        )
        resume_positions = [
            resume_body.index(fragment) for fragment in quiesced_resume_order
        ]
        self.assertEqual(resume_positions, sorted(resume_positions))
        self.assertIn(
            "PRODUCTION_BACKEND_SERVICES=(api worker worker-skills delivery-consumer)",
            helper,
        )
        for stateful_service in ("postgres", "redis", "minio", "frontend"):
            self.assertNotIn(stateful_service, quiesce_body)
            self.assertNotIn(stateful_service, resume_body)

        recovery_body = function_body("resume_backend_on_failure")
        self.assertIn("compose_resume_quiesced_backend", recovery_body)
        self.assertIn(
            "trap 'resume_backend_on_failure \"$?\"' EXIT",
            function_body("arm_backend_recovery_trap"),
        )
        self.assertIn("trap - EXIT", function_body("clear_backend_recovery_trap"))
        self.assertIn(
            "PRODUCTION_INGRESS_BACKEND_SERVICES=(api delivery-consumer)",
            helper,
        )
        self.assertIn(
            "PRODUCTION_WORKER_SERVICES=(worker worker-skills)",
            helper,
        )
        self.assertIn(
            'compose_up_ingress_backend() { "${COMPOSE[@]}" up -d --no-deps '
            '--force-recreate "${PRODUCTION_INGRESS_BACKEND_SERVICES[@]}"; }',
            helper,
        )
        self.assertIn(
            'compose_up_workers() { "${COMPOSE[@]}" up -d --no-deps '
            '--force-recreate --wait "${PRODUCTION_WORKER_SERVICES[@]}"; }',
            helper,
        )
        ordered_resume_body = function_body("compose_resume_backend")
        ordered_resume = (
            '"${COMPOSE[@]}" start "${PRODUCTION_INGRESS_BACKEND_SERVICES[@]}"',
            "compose_wait_for_delivery_consumer",
            'verify_delivery_ingress "$CYGNUS_DOMAIN"',
            '"${COMPOSE[@]}" start "${PRODUCTION_WORKER_SERVICES[@]}"',
            'verify_ingress "$CYGNUS_DOMAIN"',
        )
        ordered_positions = [
            ordered_resume_body.index(fragment) for fragment in ordered_resume
        ]
        self.assertEqual(ordered_positions, sorted(ordered_positions))

        wait_body = function_body("compose_wait_for_delivery_consumer")
        self.assertEqual(
            wait_body.strip(),
            '"${COMPOSE[@]}" up -d --no-deps --wait delivery-consumer',
        )
        frontend_body = function_body("compose_up_frontend")
        self.assertLess(
            frontend_body.index("compose_wait_for_delivery_consumer"),
            frontend_body.index(
                '"${COMPOSE[@]}" up -d --no-deps --force-recreate frontend'
            ),
        )

        entrypoints = {
            path: Path(path).read_text(encoding="utf-8")
            for path in (
                "scripts/prod/deploy.sh",
                "scripts/prod/rollback.sh",
                "scripts/prod/compose-control.sh",
            )
        }
        for path, script in entrypoints.items():
            self.assertIn("\nvalidate_compose\n", script, path)
        self.assertIn("\ncompose_pull\n", entrypoints["scripts/prod/deploy.sh"])
        compose_control = entrypoints["scripts/prod/compose-control.sh"]
        self.assertLess(
            compose_control.index("\nvalidate_compose\n"),
            compose_control.index('\nexec "${COMPOSE[@]}" "$@"'),
        )

    def test_production_delivery_consumer_uses_shared_private_runtime(self) -> None:
        compose = Path("deploy/docker-compose.prod.yml").read_text(encoding="utf-8")
        backend_runtime = compose.partition("x-backend-app: &backend-app\n")[
            2
        ].partition("\nservices:\n")[0]
        consumer_match = re.search(
            r"(?ms)^  delivery-consumer:\n(.*?)(?=^  [a-z][a-z0-9-]*:\n|^secrets:|\Z)",
            compose,
        )
        self.assertIsNotNone(consumer_match)
        consumer = consumer_match.group(1) if consumer_match else ""
        frontend = compose.partition("\n  frontend:\n")[2].partition("\nsecrets:\n")[0]

        for fragment in (
            "image: ${CYGNUS_API_IMAGE:",
            "env_file:",
            "${CYGNUS_PRODUCTION_ENV_FILE:-.env.prod}",
            "read_only: true",
            'user: "65534:65534"',
            "cap_drop: [ALL]",
            "no-new-privileges:true",
            "tmpfs:",
            "resources:",
        ):
            self.assertIn(fragment, backend_runtime)
        for fragment in (
            "<<: *backend-app",
            'command: ["uvicorn", "cygnus.integrations.delivery_consumer:app", '
            '"--host", "0.0.0.0", "--port", "8090"]',
            "migrator:\n        condition: service_completed_successfully",
            "http://localhost:8090/health",
        ):
            self.assertIn(fragment, consumer)
        self.assertNotIn("image:", consumer)
        self.assertNotIn("ports:", consumer)
        self.assertNotIn("volumes:", consumer)
        self.assertIn(
            "delivery-consumer:\n        condition: service_healthy",
            frontend,
        )

    def test_production_delivery_targets_are_base_origins(self) -> None:
        env_template = Path("deploy/.env.prod.example").read_text(encoding="utf-8")
        inputs_template = Path("deploy/production-inputs.example.json").read_text(
            encoding="utf-8"
        )
        delivery_config_gate = Path(
            "scripts/production_delivery_config_gate.py"
        ).read_text(encoding="utf-8")
        production_inputs_gate = Path("scripts/production_inputs_gate.py").read_text(
            encoding="utf-8"
        )
        delivery_sender = Path("cygnus/publish/delivery.py").read_text(encoding="utf-8")
        delivery_target_origin = "https://REPLACE_WITH_INTERNAL_DELIVERY_HOST"

        expected_env_target = (
            'DELIVERY_TARGETS_JSON={"REPLACE_WITH_CHANNEL_ID":"'
            f'{delivery_target_origin}"}}'
        )
        self.assertIn(expected_env_target, env_template)
        self.assertIn(
            f'"endpoint": "{delivery_target_origin}"',
            inputs_template,
        )
        self.assertNotIn("/v1/delivery", env_template)
        self.assertNotIn("/v1/delivery", inputs_template)
        self.assertIn('parsed.path not in ("", "/")', delivery_config_gate)
        self.assertGreaterEqual(
            production_inputs_gate.count('parsed.path not in ("", "/")'),
            2,
        )
        self.assertIn(
            '_DELIVERY_PATH = "api/internal/propagation-delivery"',
            delivery_sender,
        )
        self.assertIn(
            'return urljoin(normalized + "/", _DELIVERY_PATH)',
            delivery_sender,
        )

    def test_delivery_consumer_nginx_route_is_exact_and_certification_reuses_it(
        self,
    ) -> None:
        nginx = Path("deploy/nginx/nginx.prod.conf.template").read_text(
            encoding="utf-8"
        )
        route_marker = "location = /api/internal/propagation-delivery"
        route_start = nginx.index(route_marker)
        route_end = nginx.index("\n    }", route_start)
        route = nginx[route_start:route_end]

        self.assertLess(route_start, nginx.index("location ^~ /api/"))
        self.assertIn("proxy_pass http://delivery-consumer:8090;", route)
        self.assertIn("client_max_body_size 1m;", route)
        self.assertIn('add_header Cache-Control "no-store" always;', route)
        self.assertIn("include /etc/nginx/security-headers.conf;", route)
        self.assertNotIn("proxy_pass_request_headers off;", nginx)
        self.assertNotIn("proxy_hide_header X-Cygnus-Ack-Signature;", nginx)
        readiness_marker = "location = /readyz"
        readiness_start = nginx.index(readiness_marker)
        readiness_end = nginx.index("\n    }", readiness_start)
        readiness_route = nginx[readiness_start:readiness_end]
        self.assertIn("auth_request /_delivery-consumer-health;", readiness_route)
        self.assertIn(
            "error_page 500 =503 /_delivery-consumer-not-ready;", readiness_route
        )
        self.assertIn("proxy_pass http://api:8077/readyz;", readiness_route)
        self.assertIn("proxy_pass http://delivery-consumer:8090/health;", nginx)
        self.assertIn("proxy_connect_timeout 1s;", nginx)
        self.assertIn("proxy_read_timeout 2s;", nginx)
        self.assertIn("proxy_send_timeout 2s;", nginx)
        self.assertIn(
            'return 503 \'{"status":"not_ready","checks":{"delivery_consumer":{"status":"failed"}}}\';',
            nginx,
        )

        certification = Path("deploy/docker-compose.certification.yml").read_text(
            encoding="utf-8"
        )
        certification_stack = Path("scripts/prod/certification-stack.sh").read_text(
            encoding="utf-8"
        )
        resume_section = certification_stack.partition("  resume)\n")[2].partition(
            "  restart)\n"
        )[0]
        restart_section = certification_stack.partition("  restart)\n")[2].partition(
            "  recover)\n"
        )[0]
        recover_section = certification_stack.partition("  recover)\n")[2].partition(
            "  smoke-exercise)\n"
        )[0]
        rollout_section = certification_stack.partition("  up|redeploy)\n")[
            2
        ].partition("esac")[0]
        production_policy_validation = 'validate_production_inputs "$RELEASE"'
        certification_network_override = "export CYGNUS_NETWORK_SUBNET="
        self.assertLess(
            certification_stack.index(production_policy_validation),
            certification_stack.index(certification_network_override),
        )
        self.assertNotIn(production_policy_validation, rollout_section)
        self.assertNotIn("\n  delivery-consumer:", certification)
        self.assertNotIn("\n  frontend:", certification)
        self.assertEqual(
            certification.count("CYGNUS_CERTIFICATION_DELIVERY_TARGETS_JSON"),
            2,
        )
        self.assertEqual(
            certification.count('CYGNUS_DELIVERY_ALLOWED_HOSTS: "frontend"'),
            2,
        )
        self.assertEqual(
            certification.count("SSL_CERT_FILE: /run/secrets/cygnus_tls_cert"),
            2,
        )
        self.assertIn(
            'CERTIFICATION_DELIVERY_ORIGIN="https://frontend:8443"',
            certification_stack,
        )
        self.assertIn("DNS:frontend", certification_stack)
        self.assertIn(
            '-f "$COMPOSE_FILE" -f "$CERTIFICATION_COMPOSE_FILE"',
            certification_stack,
        )
        self.assertIn(
            'CERTIFICATION_ORIGIN="https://127.0.0.1:$CYGNUS_HTTPS_BIND_PORT"',
            certification_stack,
        )
        self.assertIn(
            'curl -fsS --cacert "$CYGNUS_TLS_CERT_FILE"',
            certification_stack,
        )
        self.assertIn(
            '{"detail": "delivery signature is invalid"}',
            certification_stack,
        )
        self.assertIn(
            "X-Cygnus-Signature: sha256=$delivery_signature",
            certification_stack,
        )
        self.assertIn(
            'readiness_status" = 204',
            certification_stack,
        )
        self.assertIn(
            '"${COMPOSE[@]}" stop api worker worker-skills delivery-consumer',
            certification_stack,
        )
        resume_order = (
            '"${COMPOSE[@]}" start "${PRODUCTION_INGRESS_BACKEND_SERVICES[@]}"',
            "compose_wait_for_delivery_consumer",
            "verify_certification_delivery_ingress",
            '"${COMPOSE[@]}" start "${PRODUCTION_WORKER_SERVICES[@]}"',
            "verify_certification_ingress",
        )
        resume_positions = [resume_section.index(fragment) for fragment in resume_order]
        self.assertEqual(resume_positions, sorted(resume_positions))
        restart_order = (
            '"${COMPOSE[@]}" restart "${PRODUCTION_INGRESS_BACKEND_SERVICES[@]}"',
            "compose_wait_for_delivery_consumer",
            '"${COMPOSE[@]}" restart frontend',
            "verify_certification_delivery_ingress",
            '"${COMPOSE[@]}" restart "${PRODUCTION_WORKER_SERVICES[@]}"',
            "verify_certification_ingress",
        )
        restart_positions = [
            restart_section.index(fragment) for fragment in restart_order
        ]
        self.assertEqual(restart_positions, sorted(restart_positions))
        gated_order = (
            "compose_up_ingress_backend",
            "compose_up_frontend",
            "verify_certification_delivery_ingress",
            "compose_up_workers",
            "verify_certification_ingress",
        )
        for section in (recover_section, rollout_section):
            positions = [section.index(fragment) for fragment in gated_order]
            self.assertEqual(positions, sorted(positions))

    def test_production_network_gate_accepts_bound_nonstandard_tls_origin(
        self,
    ) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "scripts/production_network_config_gate.py",
                "--domain",
                "vm-0-7-ubuntu.tailc9ec74.ts.net",
                "--public-origin",
                "https://vm-0-7-ubuntu.tailc9ec74.ts.net:8443",
                "--metrics-cidr",
                "172.30.0.1/32",
                "--expected-proxy-cidr",
                "172.30.0.0/24",
                "--quiet",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_production_network_gate_rejects_reserved_or_mismatched_origins(
        self,
    ) -> None:
        base = [
            sys.executable,
            "scripts/production_network_config_gate.py",
            "--metrics-cidr",
            "172.30.0.1/32",
            "--expected-proxy-cidr",
            "172.30.0.0/24",
            "--quiet",
        ]
        cases = (
            (
                "cygnus-certification.local",
                "https://cygnus-certification.local",
            ),
            (
                "vm-0-7-ubuntu.tailc9ec74.ts.net",
                "https://other.tailc9ec74.ts.net:8443",
            ),
        )
        for domain, origin in cases:
            with self.subTest(domain=domain, origin=origin):
                result = subprocess.run(
                    [*base, "--domain", domain, "--public-origin", origin],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotEqual(result.returncode, 0)

    def test_production_operator_state_survives_transient_runner_checkouts(
        self,
    ) -> None:
        helper = Path("scripts/prod/lib.sh").read_text(encoding="utf-8")
        deploy = Path("scripts/prod/deploy.sh").read_text(encoding="utf-8")
        rollback = Path("scripts/prod/rollback.sh").read_text(encoding="utf-8")
        env_example = Path("deploy/.env.prod.example").read_text(encoding="utf-8")

        self.assertIn(
            'RELEASES_DIR="${releases_override:-${CYGNUS_RELEASES_DIR:-$DEPLOY_DIR/releases}}"',
            helper,
        )
        self.assertIn(
            'STATE_FILE="${state_override:-${CYGNUS_DEPLOY_STATE_FILE:-$DEPLOY_DIR/.state}}"',
            helper,
        )
        self.assertIn('release_file="$RELEASES_DIR/$release.env"', helper)
        self.assertIn('cmp -s "$LOADED_RELEASE_FILE" "$target"', helper)
        self.assertIn('load_state() { load_env_file "$STATE_FILE"; }', helper)
        self.assertIn('if [ -f "$STATE_FILE" ]; then', deploy)
        self.assertIn(
            'CHECKOUTS_DIR="${checkouts_override:-${CYGNUS_CHECKOUTS_DIR:-}}"', helper
        )
        self.assertIn(
            'ACTIVE_CHECKOUT_LINK="${active_link_override:-${CYGNUS_ACTIVE_CHECKOUT_LINK:-}}"',
            helper,
        )
        self.assertIn('validate_operator_state_paths "$RELEASE"', deploy)
        self.assertIn(
            '"$TARGET_CHECKOUT/scripts/prod/rollback.sh" --release "$RELEASE" --yes',
            rollback,
        )
        self.assertNotIn('exec "$TARGET_CHECKOUT/scripts/prod/rollback.sh"', rollback)
        self.assertIn(
            '"$SCRIPT_DIR/rollback.sh" --release "$PREVIOUS" --downgrade target --yes',
            deploy,
        )
        self.assertNotIn(
            '"$CHECKOUTS_DIR/$PREVIOUS/scripts/prod/rollback.sh" --release', deploy
        )
        self.assertIn(
            'CYGNUS_ROLLBACK_SOURCE_METADATA_FILE="$LOADED_RELEASE_FILE"', deploy
        )
        self.assertIn(
            'CYGNUS_ROLLBACK_SOURCE_INPUTS_FILE="$LOADED_RELEASE_INPUTS_FILE"', deploy
        )
        deploy_state_steps = (
            'persist_release_metadata "$RELEASE"',
            'activate_release_checkout "$RELEASE"',
            'save_state "$PREVIOUS" "$RELEASE"',
        )
        self.assertEqual(
            [deploy.index(fragment) for fragment in deploy_state_steps],
            sorted(deploy.index(fragment) for fragment in deploy_state_steps),
        )
        self.assertIn("CYGNUS_RELEASES_DIR=/var/lib/cygnus/releases", env_example)
        self.assertIn(
            "CYGNUS_DEPLOY_STATE_FILE=/var/lib/cygnus/deploy-state.env", env_example
        )
        self.assertIn("CYGNUS_CHECKOUTS_DIR=/var/lib/cygnus/checkouts", env_example)
        self.assertIn("CYGNUS_ACTIVE_CHECKOUT_LINK=/srv/cygnus/current", env_example)

    def test_production_proxy_and_datastores_do_not_receive_unneeded_app_secrets(
        self,
    ) -> None:
        compose = Path("deploy/docker-compose.prod.yml").read_text(encoding="utf-8")
        frontend = compose.partition("\n  frontend:\n")[2].partition("\nsecrets:\n")[0]
        postgres = compose.partition("\n  postgres:\n")[2].partition("\n  redis:\n")[0]
        redis = compose.partition("\n  redis:\n")[2].partition("\n  minio:\n")[0]
        minio = compose.partition("\n  minio:\n")[2].partition("\n  migrator:\n")[0]

        self.assertIn("${CYGNUS_PRODUCTION_ENV_FILE:-.env.prod}", compose)
        for service in (frontend, postgres, redis, minio):
            self.assertNotIn("env_file:", service)
            self.assertNotIn("SECRET_KEY", service)
            self.assertNotIn("DEFAULT_ADMIN_PASSWORD", service)
            self.assertNotIn("MCP_TOKEN_PEPPER", service)
        self.assertIn("POSTGRES_PASSWORD:", postgres)
        self.assertNotIn("REDIS_PASSWORD:", postgres)
        self.assertIn("REDIS_PASSWORD:", redis)
        self.assertNotIn("POSTGRES_PASSWORD:", redis)
        self.assertIn("MINIO_ROOT_PASSWORD:", minio)
        self.assertNotIn("POSTGRES_PASSWORD:", minio)
        self.assertIn("CYGNUS_DOMAIN:", frontend)
        self.assertIn("CYGNUS_METRICS_ALLOWED_CIDR:", frontend)
        self.assertIn("MINIO_BUCKET:", frontend)

    def test_deploy_validates_then_quiesces_before_schema_mutation(self) -> None:
        deploy = Path("scripts/prod/deploy.sh").read_text(encoding="utf-8")
        ordered_fragments = (
            "load_prod_env\n",
            'load_release "$RELEASE"\n',
            'validate_identity "$RELEASE"\n',
            "validate_secrets\n",
            "validate_resources\n",
            'validate_production_inputs "$RELEASE"\n',
            "validate_compose\n",
            'if [ "$DRY_RUN" = 1 ]; then',
            "\ncompose_pull\n",
            "\ncompose_up_stateful\n",
            "\narm_backend_recovery_trap\n",
            "\ncompose_quiesce_backend\n",
            "\nrun_migrations\n",
            "\nclear_backend_recovery_trap\n",
            "\ncompose_up_ingress_backend\n",
            "\ncompose_up_frontend\n",
            '\nverify_delivery_ingress "$CYGNUS_DOMAIN"\n',
            "\ncompose_up_workers\n",
            '\nverify_ingress "$CYGNUS_DOMAIN"\n',
        )
        positions = [deploy.index(fragment) for fragment in ordered_fragments]
        self.assertEqual(positions, sorted(positions))

    def test_rollback_uses_source_image_before_target_checkout_handoff(self) -> None:
        rollback = Path("scripts/prod/rollback.sh").read_text(encoding="utf-8")
        source_first = (
            "target_contract=$(preflight_target_checkout)",
            'load_release "$SOURCE_RELEASE"',
            "SOURCE_EXPECTED_ALEMBIC_HEAD=$EXPECTED_ALEMBIC_HEAD",
            'if [ "$SOURCE_EXPECTED_ALEMBIC_HEAD" != "$TARGET_EXPECTED_ALEMBIC_HEAD" ]',
            "arm_backend_recovery_trap",
            "compose_quiesce_backend",
            '"${COMPOSE[@]}" run --rm --no-deps api alembic downgrade "$DOWNGRADE_REV"',
            "clear_backend_recovery_trap",
            '"${COMPOSE[@]}" rm --stop --force delivery-consumer',
            '"$TARGET_CHECKOUT/scripts/prod/rollback.sh" --release "$RELEASE" --yes',
        )
        positions = [rollback.index(fragment) for fragment in source_first]
        self.assertEqual(positions, sorted(positions))
        self.assertIn(
            "preflight_target_checkout() (\n  exec 3>&1\n  exec 1>&2", rollback
        )
        self.assertIn(
            'printf \'%s|%s\' "$EXPECTED_ALEMBIC_HEAD" "$target_has_consumer" >&3',
            rollback,
        )
        certification_stack = Path("scripts/prod/certification-stack.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "fault-off|consumer-stop|consumer-restart) ;;", certification_stack
        )
        self.assertIn(
            'if [ -n "$DOWNGRADE_REV" ] && [ "$DOWNGRADE_REV" != "$TARGET_EXPECTED_ALEMBIC_HEAD" ]',
            rollback,
        )
        handoff = rollback.partition(
            '"$TARGET_CHECKOUT/scripts/prod/rollback.sh" --release "$RELEASE" --yes'
        )[0].rsplit("\n", 1)[-1]
        self.assertNotIn("--downgrade", handoff)

        target_reload = rollback.rindex('load_release "$RELEASE"')
        target_rollout = (
            "arm_backend_recovery_trap",
            "compose_up_ingress_backend",
            "compose_up_frontend",
            'verify_delivery_ingress "$CYGNUS_DOMAIN"',
            "compose_up_workers",
            'verify_ingress "$CYGNUS_DOMAIN"',
            "clear_backend_recovery_trap",
        )
        target_positions = [
            rollback.index(fragment, target_reload) for fragment in target_rollout
        ]
        self.assertEqual(target_positions, sorted(target_positions))

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
        self.assertIn("return 301 ${CYGNUS_PUBLIC_ORIGIN}$request_uri;", text)
        self.assertIn(
            "CYGNUS_PUBLIC_ORIGIN=https://REPLACE_WITH_PUBLIC_FQDN",
            Path("deploy/.env.prod.example").read_text(encoding="utf-8"),
        )
        helper = Path("scripts/prod/lib.sh").read_text(encoding="utf-8")
        self.assertIn(
            "TRUSTED_PROXY_IPS must be the deterministic narrow prodnet CIDR", helper
        )

    def test_frontend_container_ports_require_no_linux_capabilities(self) -> None:
        frontend_dockerfile = Path("frontend/Dockerfile").read_text(encoding="utf-8")
        local_nginx = Path("frontend/nginx.conf").read_text(encoding="utf-8")
        production_nginx = Path("deploy/nginx/nginx.prod.conf.template").read_text(
            encoding="utf-8"
        )
        local_compose = Path("docker-compose.yml").read_text(encoding="utf-8")
        production_compose = Path("deploy/docker-compose.prod.yml").read_text(
            encoding="utf-8"
        )
        release_gate = Path("scripts/release_contract_gate.py").read_text(
            encoding="utf-8"
        )

        def listener_ports(text: str) -> list[int]:
            ports: list[int] = []
            for directive in re.findall(r"^\s*listen\s+([^;]+);", text, re.MULTILINE):
                match = re.search(r"(?:^|:)(\d+)(?:\s|$)", directive)
                if match is None:
                    self.fail(f"unrecognized nginx listen directive: {directive}")
                ports.append(int(match.group(1)))
            return ports

        self.assertEqual(listener_ports(local_nginx), [8080])
        self.assertEqual(listener_ports(production_nginx), [8080, 8443])
        self.assertIn("USER nginx", frontend_dockerfile)
        self.assertIn("EXPOSE 8080 8443", frontend_dockerfile)
        self.assertIn("http://127.0.0.1:8080/health", frontend_dockerfile)
        for capability_setup in ("setcap", "libcap", "cap_net_bind_service"):
            self.assertNotIn(capability_setup, frontend_dockerfile.lower())

        local_frontend = local_compose.partition("\n  frontend:\n")[2].partition(
            "\nvolumes:\n"
        )[0]
        self.assertIn(
            '"${CYGNUS_DOCKER_FRONTEND_HOST_PORT:-5173}:8080"', local_frontend
        )
        self.assertIn("cap_drop: [ALL]", local_frontend)
        self.assertIn("no-new-privileges:true", local_frontend)
        self.assertNotIn("cap_add", local_frontend)

        production_frontend = production_compose.partition("\n  frontend:\n")[
            2
        ].partition("\nsecrets:\n")[0]
        self.assertIn('"${CYGNUS_HTTP_BIND_PORT:-80}:8080"', production_frontend)
        self.assertIn('"${CYGNUS_HTTPS_BIND_PORT:-443}:8443"', production_frontend)
        self.assertNotIn('"80:80"', production_frontend)
        self.assertNotIn('"443:443"', production_frontend)
        self.assertIn("cap_drop: [ALL]", production_frontend)
        self.assertIn("no-new-privileges:true", production_frontend)
        self.assertIn("CYGNUS_PUBLIC_ORIGIN:", production_frontend)
        self.assertNotIn("cap_add", production_frontend)
        self.assertIn("https://127.0.0.1:8443/readyz", production_frontend)

        self.assertIn("listen 8443 ssl;", production_nginx)
        self.assertIn(
            "ssl_certificate     /run/secrets/cygnus_tls_cert;", production_nginx
        )
        self.assertIn("ssl_protocols TLSv1.2 TLSv1.3;", production_nginx)
        self.assertIn("CYGNUS_HTTP_BIND_PORT:-80", release_gate)
        self.assertIn("CYGNUS_HTTPS_BIND_PORT:-443", release_gate)
        self.assertIn("must not use privileged proxy container ports", release_gate)

    def test_production_policy_binder_injects_exact_release_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            template = root / "policy.json"
            metadata = root / "release.env"
            output = root / "bound.json"
            policy = json.loads(
                Path("deploy/production-inputs.example.json").read_text(
                    encoding="utf-8"
                )
            )
            policy["status"] = "approved"
            policy["release"] = {}
            template.write_text(json.dumps(policy), encoding="utf-8")
            metadata.write_text(
                "APP_RELEASE=0.1.0\n"
                f"APP_COMMIT_SHA={'a' * 40}\n"
                f"CYGNUS_API_IMAGE=ghcr.io/owner/api:rc-a1b2c3@sha256:{'b' * 64}\n"
                f"CYGNUS_FRONTEND_IMAGE=ghcr.io/owner/frontend:rc-a1b2c3@sha256:{'c' * 64}\n"
                "EXPECTED_ALEMBIC_HEAD=20260815_02_employee_session_version\n",
                encoding="utf-8",
            )
            command = [
                sys.executable,
                "scripts/prod/bind-production-inputs.py",
                "--template",
                str(template),
                "--release-metadata",
                str(metadata),
                "--out",
                str(output),
            ]

            first = subprocess.run(command, capture_output=True, text=True, check=False)
            second = subprocess.run(
                command, capture_output=True, text=True, check=False
            )

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertNotEqual(second.returncode, 0)
            bound = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(bound["bound_release"], "0.1.0")
            self.assertEqual(bound["release"]["git_sha"], "a" * 40)
            self.assertEqual(
                bound["release"]["backend_image"],
                f"ghcr.io/owner/api:rc-a1b2c3@sha256:{'b' * 64}",
            )

            shell = subprocess.run(
                [
                    "bash",
                    "-c",
                    "source scripts/prod/lib.sh; "
                    f"CYGNUS_API_IMAGE=ghcr.io/owner/api:rc-a1b2c3@sha256:{'b' * 64}; "
                    f"CYGNUS_FRONTEND_IMAGE=ghcr.io/owner/frontend:rc-a1b2c3@sha256:{'c' * 64}; "
                    "validate_digests 0.1.0",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(shell.returncode, 0, shell.stderr)

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
        self.assertIn("nginx:1.30.4-alpine3.24@sha256:", frontend_text)
        self.assertIn("package-lock.json", frontend_text)
        self.assertIn("npm ci --no-audit --no-fund", frontend_text)
        self.assertIn("AS prod", frontend_text)
        self.assertIn("USER nginx", frontend_text)
        self.assertIn("EXPOSE 8080 8443", frontend_text)
        self.assertIn("pid        /tmp/nginx.pid;", frontend_text)
        self.assertIn('CMD ["nginx", "-g", "daemon off;"]', frontend_text)
        self.assertNotIn("daemon off; pid /tmp/nginx.pid;", frontend_text)
        self.assertIn('io.cygnus.image.immutable="true"', frontend_text)

    def test_policy_only_materializer_needs_no_production_secret(self) -> None:
        payloads = {
            "CYGNUS_ALERT_THRESHOLDS_B64": {"approval": "alert"},
            "CYGNUS_CAPACITY_THRESHOLDS_B64": {"approval": "capacity"},
            "CYGNUS_CAPACITY_TARGETS_B64": {"routes": {}},
        }
        environment = os.environ.copy()
        environment.update(
            {
                name: base64.b64encode(json.dumps(payload).encode()).decode()
                for name, payload in payloads.items()
            }
        )
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "policy"
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/prod/materialize-certification-inputs.py",
                    "--policy-only",
                    "--output-dir",
                    str(output),
                ],
                capture_output=True,
                text=True,
                env=environment,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((output / "production.env").exists())
            self.assertFalse((output / "production-inputs.json").exists())
            for name in (
                "alert-thresholds.json",
                "capacity-thresholds.json",
                "capacity-targets.json",
            ):
                path = output / name
                self.assertTrue(path.is_file())
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_docker_local_override_file_is_gitignored(self) -> None:
        text = Path(".gitignore").read_text(encoding="utf-8")
        self.assertIn(".env.docker.local", text)


if __name__ == "__main__":
    unittest.main()
