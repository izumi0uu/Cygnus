#!/usr/bin/env python3
"""Static fail-closed contract for production delivery artifacts.

This gate deliberately does not claim that a host, registry, DNS name, TLS
certificate, or secret exists. It checks that the repository cannot silently
fall back to an unpinned image, a development compose profile, or a release
workflow that skips a required evidence gate. Live registry verification is
performed separately by ``image_reference_gate.py``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import TypedDict, cast

REPO_ROOT = Path(__file__).resolve().parents[1]
DIGEST_REF_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._/-]*:[A-Za-z0-9._-]+@sha256:[0-9a-f]{64}$"
)
ARG_IMAGE_RE = re.compile(
    r"^ARG\s+[A-Z][A-Z0-9_]*=(\S+@sha256:[0-9a-f]{64})\s*$", re.MULTILINE
)
DIRECT_IMAGE_RE = re.compile(
    r"^\s*image:\s+(\S+@sha256:[0-9a-f]{64})\s*$", re.MULTILINE
)
WORKFLOW_IMAGE_RE = re.compile(
    r"\b([A-Za-z0-9][A-Za-z0-9._/-]*:[A-Za-z0-9._-]+@sha256:[0-9a-f]{64})\b"
)
ACTION_SHA_RE = re.compile(
    r"^\s*uses:\s+[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}\s*$", re.MULTILINE
)


class GateResult(TypedDict):
    ok: bool
    failures: list[str]
    checks: dict[str, object]


def _read(root: Path, relative: str) -> str:
    return (root / relative).read_text(encoding="utf-8")


def _image_refs(root: Path) -> set[str]:
    refs: set[str] = set()
    for relative in ("Dockerfile", "frontend/Dockerfile"):
        refs.update(ARG_IMAGE_RE.findall(_read(root, relative)))
    for relative in ("docker-compose.yml", "deploy/docker-compose.prod.yml"):
        refs.update(DIRECT_IMAGE_RE.findall(_read(root, relative)))
    refs.update(WORKFLOW_IMAGE_RE.findall(_read(root, ".github/workflows/release.yml")))
    return refs


def validate_repository(root: Path = REPO_ROOT) -> GateResult:
    failures: list[str] = []
    checks: dict[str, object] = {}
    required_files = (
        "Dockerfile",
        "frontend/Dockerfile",
        "frontend/package-lock.json",
        "frontend/scripts/run-browser-certification.mjs",
        "docker-compose.yml",
        "deploy/docker-compose.prod.yml",
        "deploy/docker-compose.certification.yml",
        "deploy/nginx/nginx.prod.conf.template",
        "deploy/image-lock.json",
        "config/observability/alert_rules.yml",
        "config/observability/alert_thresholds.schema.json",
        "cygnus/observability/alert_rules.py",
        "cygnus/publish/delivery.py",
        "cygnus/integrations/delivery_consumer.py",
        "migrations/versions/20260816_01_delivery_consumer_receipts.py",
        "deploy/production-inputs.example.json",
        "deploy/.env.prod.example",
        ".github/workflows/release.yml",
        ".github/workflows/repo-guard.yml",
        ".github/workflows/backup-restore-drill.yml",
        "scripts/prod/deploy.sh",
        "scripts/prod/rollback.sh",
        "scripts/prod/compose-control.sh",
        "scripts/prod/backup_restore_drill.sh",
        "scripts/prod/certification-stack.sh",
        "scripts/prod/security-certification.py",
        "scripts/run_live_production_certification.sh",
        "scripts/prod/materialize-certification-inputs.py",
        "scripts/prod/write-release-env.py",
        "scripts/prod/rotate-secrets.sh",
        "scripts/prod/incident.sh",
        "scripts/prod/lib.sh",
        "scripts/production_inputs_gate.py",
        "scripts/production_delivery_config_gate.py",
        "scripts/collect_image_attestations.py",
        "scripts/render_alert_rules.py",
        "scripts/release_gate.py",
    )
    missing = [path for path in required_files if not (root / path).is_file()]
    checks["required_files"] = {"count": len(required_files), "missing": missing}
    failures.extend(f"required file missing: {path}" for path in missing)
    if missing:
        return {"ok": False, "failures": failures, "checks": checks}
    browser_runner = root / "frontend/scripts/run-browser-certification.mjs"
    browser_runner_executable = os.access(browser_runner, os.X_OK)
    checks["browser_certification_runner_executable"] = browser_runner_executable
    if not browser_runner_executable:
        failures.append("browser certification runner must be executable")

    try:
        lock = json.loads(_read(root, "deploy/image-lock.json"))
    except (OSError, json.JSONDecodeError) as exc:
        lock = {}
        failures.append(f"deploy/image-lock.json is invalid JSON: {exc}")
    lock_refs = {
        str(entry.get("reference"))
        for entry in cast(list[object], lock.get("images", []))
        if isinstance(entry, dict) and entry.get("reference")
    }
    refs = _image_refs(root)
    checks["digest_image_references"] = sorted(refs)
    checks["lock_coverage"] = sorted(refs & lock_refs)
    uncovered = sorted(refs - lock_refs)
    if uncovered:
        failures.append(
            "image references missing from deploy/image-lock.json: "
            + ", ".join(uncovered)
        )
    for ref in refs:
        if not DIGEST_REF_RE.fullmatch(ref):
            failures.append(f"image reference is not an exact digest pin: {ref}")

    local_compose = _read(root, "docker-compose.yml")
    production_compose = _read(root, "deploy/docker-compose.prod.yml")
    certification_compose = _read(root, "deploy/docker-compose.certification.yml")
    nginx_template = _read(root, "deploy/nginx/nginx.prod.conf.template")
    certification_stack = _read(root, "scripts/prod/certification-stack.sh")
    production_env_example = _read(root, "deploy/.env.prod.example")
    security_certification = _read(root, "scripts/prod/security-certification.py")
    production_inputs_example = _read(root, "deploy/production-inputs.example.json")
    delivery_config_gate = _read(root, "scripts/production_delivery_config_gate.py")
    production_inputs_gate = _read(root, "scripts/production_inputs_gate.py")
    delivery_sender = _read(root, "cygnus/publish/delivery.py")
    delivery_consumer_source = _read(root, "cygnus/integrations/delivery_consumer.py")
    production_worker = _read(root, "cygnus/runtime/worker.py")
    production_helpers = _read(root, "scripts/prod/lib.sh")
    backup_restore_drill = _read(root, "scripts/prod/backup_restore_drill.sh")
    production_deploy = _read(root, "scripts/prod/deploy.sh")
    production_rollback = _read(root, "scripts/prod/rollback.sh")
    production_compose_control = _read(root, "scripts/prod/compose-control.sh")
    workflow = _read(root, ".github/workflows/release.yml")
    repo_guard_workflow = _read(root, ".github/workflows/repo-guard.yml")
    checks["local_profile_marked_development"] = "DEVELOPMENT ONLY" in local_compose
    if "DEVELOPMENT ONLY" not in local_compose:
        failures.append(
            "local docker-compose.yml is not explicitly marked DEVELOPMENT ONLY"
        )
    delivery_target_origin = "https://REPLACE_WITH_INTERNAL_DELIVERY_HOST"
    delivery_origin_checks = {
        "env_template_uses_base_origin": (
            f'DELIVERY_TARGETS_JSON={{"REPLACE_WITH_CHANNEL_ID":"{delivery_target_origin}"}}'
            in production_env_example
        ),
        "manifest_template_uses_base_origin": (
            f'"endpoint": "{delivery_target_origin}"' in production_inputs_example
        ),
        "legacy_delivery_suffix_absent": (
            "/v1/delivery" not in production_env_example
            and "/v1/delivery" not in production_inputs_example
        ),
        "env_gate_rejects_nonroot_paths": (
            'parsed.path not in ("", "/")' in delivery_config_gate
        ),
        "input_gate_rejects_nonroot_paths": (
            production_inputs_gate.count('parsed.path not in ("", "/")') >= 2
        ),
        "sender_appends_fixed_delivery_path": (
            '_DELIVERY_PATH = "api/internal/propagation-delivery"' in delivery_sender
            and 'return urljoin(normalized + "/", _DELIVERY_PATH)' in delivery_sender
        ),
    }
    checks["delivery_target_origin_contract"] = delivery_origin_checks
    failures.extend(
        f"delivery target origin contract failed: {name}"
        for name, passed in delivery_origin_checks.items()
        if not passed
    )
    if re.search(r"^\s*build:\s*", production_compose, re.MULTILINE):
        failures.append("production compose must not contain build instructions")
    for fragment in (
        "read_only: true",
        "cap_drop:",
        "no-new-privileges:true",
        "tmpfs:",
        "deploy:",
        "resources:",
        "CYGNUS_TLS_CERT_FILE",
        "CYGNUS_TLS_KEY_FILE",
    ):
        if fragment not in production_compose:
            failures.append(
                f"production compose missing required hardening/config fragment: {fragment}"
            )
    checks["production_hardening_fragments"] = True
    required_proxy_port_mappings = (
        '"${CYGNUS_HTTP_BIND_PORT:-80}:8080"',
        '"${CYGNUS_HTTPS_BIND_PORT:-443}:8443"',
    )
    if "ports:" not in production_compose or any(
        mapping not in production_compose for mapping in required_proxy_port_mappings
    ):
        failures.append(
            "production compose must map public :80/:443 to unprivileged "
            "proxy :8080/:8443"
        )
    if any(mapping in production_compose for mapping in ('"80:80"', '"443:443"')):
        failures.append(
            "production compose must not use privileged proxy container ports"
        )
    if any(
        token in production_compose
        for token in ("8077:", "8090:", "5432:", "6379:", "9000:", "9001:")
    ):
        failures.append("production compose exposes a non-proxy service port")
    service_sections = {
        "postgres": production_compose.partition("\n  postgres:\n")[2].partition(
            "\n  redis:\n"
        )[0],
        "redis": production_compose.partition("\n  redis:\n")[2].partition(
            "\n  minio:\n"
        )[0],
        "minio": production_compose.partition("\n  minio:\n")[2].partition(
            "\n  migrator:\n"
        )[0],
        "frontend": production_compose.partition("\n  frontend:\n")[2].partition(
            "\nsecrets:\n"
        )[0],
    }
    for service, section in service_sections.items():
        if not section:
            failures.append(f"production compose service section is missing: {service}")
            continue
        if "env_file:" in section:
            failures.append(
                f"production {service} service must not receive the shared app env file"
            )
        for secret_name in ("SECRET_KEY", "DEFAULT_ADMIN_PASSWORD", "MCP_TOKEN_PEPPER"):
            if secret_name in section:
                failures.append(
                    f"production {service} service receives unrelated app secret {secret_name}"
                )
    checks["production_service_secret_scoping"] = not any(
        "env_file:" in section for section in service_sections.values()
    )
    delivery_consumer_match = re.search(
        r"(?ms)^  delivery-consumer:\n(.*?)(?=^  [a-z][a-z0-9-]*:\n|^secrets:|\Z)",
        production_compose,
    )
    delivery_consumer = (
        delivery_consumer_match.group(1) if delivery_consumer_match else ""
    )
    backend_app = production_compose.partition("x-backend-app: &backend-app\n")[
        2
    ].partition("\nservices:\n")[0]
    required_backend_runtime_fragments = (
        "image: ${CYGNUS_API_IMAGE:",
        "env_file:",
        "${CYGNUS_PRODUCTION_ENV_FILE:-.env.prod}",
        "read_only: true",
        'user: "65534:65534"',
        "cap_drop: [ALL]",
        "no-new-privileges:true",
        "tmpfs:",
        "resources:",
    )
    missing_backend_runtime = [
        fragment
        for fragment in required_backend_runtime_fragments
        if fragment not in backend_app
    ]
    if missing_backend_runtime:
        failures.append(
            "shared backend runtime is missing delivery-consumer hardening/config: "
            + ", ".join(missing_backend_runtime)
        )
    required_delivery_consumer_fragments = (
        "<<: *backend-app",
        'command: ["uvicorn", "cygnus.integrations.delivery_consumer:app", '
        '"--host", "0.0.0.0", "--port", "8090"]',
        "migrator:\n        condition: service_completed_successfully",
        "http://localhost:8090/health",
    )
    missing_delivery_consumer = [
        fragment
        for fragment in required_delivery_consumer_fragments
        if fragment not in delivery_consumer
    ]
    delivery_consumer_has_port = bool(
        re.search(r"^    ports:\s*$", delivery_consumer, re.MULTILINE)
    )
    delivery_consumer_has_volume = "volumes:" in delivery_consumer
    delivery_consumer_has_direct_image = bool(
        re.search(r"^    image:", delivery_consumer, re.MULTILINE)
    )
    frontend_section = service_sections["frontend"]
    frontend_waits_for_delivery_consumer = (
        "delivery-consumer:\n        condition: service_healthy" in frontend_section
    )
    published_services = [
        name
        for name, section in re.findall(
            r"(?ms)^  ([a-z][a-z0-9-]*):\n(.*?)(?=^  [a-z][a-z0-9-]*:\n|^secrets:|\Z)",
            production_compose,
        )
        if re.search(r"^    ports:\s*$", section, re.MULTILINE)
    ]
    delivery_consumer_checks = {
        "missing": missing_delivery_consumer,
        "host_port": delivery_consumer_has_port,
        "persistent_volume": delivery_consumer_has_volume,
        "direct_image_override": delivery_consumer_has_direct_image,
        "frontend_waits_for_healthy_consumer": frontend_waits_for_delivery_consumer,
        "published_services": published_services,
    }
    checks["delivery_consumer_compose_contract"] = delivery_consumer_checks
    failures.extend(
        f"delivery-consumer compose contract missing: {fragment}"
        for fragment in missing_delivery_consumer
    )
    if delivery_consumer_has_port:
        failures.append("delivery-consumer must not publish a host port")
    if delivery_consumer_has_volume:
        failures.append("delivery-consumer receipts must not use a persistent volume")
    if delivery_consumer_has_direct_image:
        failures.append("delivery-consumer must inherit the immutable backend image")
    if not frontend_waits_for_delivery_consumer:
        failures.append("frontend must wait for a healthy delivery-consumer")
    if published_services != ["frontend"]:
        failures.append(
            "production compose must keep frontend as the sole host-published ingress"
        )
    delivery_wait_match = re.search(
        r"(?ms)^compose_wait_for_delivery_consumer\(\) \{\n(.*?)^\}",
        production_helpers,
    )
    frontend_rollout_match = re.search(
        r"(?ms)^compose_up_frontend\(\) \{\n(.*?)^\}",
        production_helpers,
    )
    deploy_delivery_order = (
        "compose_up_ingress_backend",
        "compose_up_frontend",
        'verify_delivery_ingress "$CYGNUS_DOMAIN"',
        "compose_up_workers",
        'verify_ingress "$CYGNUS_DOMAIN"',
    )
    rollback_delivery_order = deploy_delivery_order
    worker_startup = production_worker.partition(
        "async def on_startup(ctx: WorkerContext):"
    )[2].partition("await heartbeat.mark_ready()")[0]
    delivery_rollout_checks = {
        "backend_rollout_includes_consumer": (
            "PRODUCTION_BACKEND_SERVICES=(api worker worker-skills delivery-consumer)"
            in production_helpers
        ),
        "backend_roles_are_split": (
            "PRODUCTION_INGRESS_BACKEND_SERVICES=(api delivery-consumer)"
            in production_helpers
            and "PRODUCTION_WORKER_SERVICES=(worker worker-skills)"
            in production_helpers
        ),
        "deploy_workers_follow_route_proof": (
            all(fragment in production_deploy for fragment in deploy_delivery_order)
            and [
                production_deploy.index(fragment) for fragment in deploy_delivery_order
            ]
            == sorted(
                production_deploy.index(fragment) for fragment in deploy_delivery_order
            )
        ),
        "rollback_workers_follow_route_proof": (
            all(fragment in production_rollback for fragment in rollback_delivery_order)
            and [
                production_rollback.index(fragment)
                for fragment in rollback_delivery_order
            ]
            == sorted(
                production_rollback.index(fragment)
                for fragment in rollback_delivery_order
            )
        ),
        "route_probe_requires_consumer_signature_error": (
            "/api/internal/propagation-delivery" in production_helpers
            and '{"detail": "delivery signature is invalid"}' in production_helpers
        ),
        "consumer_waits_for_health": (
            delivery_wait_match is not None
            and '"${COMPOSE[@]}" up -d --no-deps --wait delivery-consumer'
            in delivery_wait_match.group(1)
        ),
        "frontend_waits_before_no_deps_rollout": (
            frontend_rollout_match is not None
            and "compose_wait_for_delivery_consumer" in frontend_rollout_match.group(1)
            and '"${COMPOSE[@]}" up -d --no-deps --force-recreate frontend'
            in frontend_rollout_match.group(1)
            and frontend_rollout_match.group(1).index(
                "compose_wait_for_delivery_consumer"
            )
            < frontend_rollout_match.group(1).index(
                '"${COMPOSE[@]}" up -d --no-deps --force-recreate frontend'
            )
        ),
        "worker_restart_probe_precedes_delivery_claim": (
            "async def delivery_targets_ready(" in delivery_sender
            and '"HEAD",' in delivery_sender
            and "X-Cygnus-Signature" in delivery_sender
            and '@app.head("/api/internal/propagation-delivery")'
            in delivery_consumer_source
            and "if not await _receipt_store_ready():" in delivery_consumer_source
            and "delivery_route_ready = await delivery_targets_ready()"
            in worker_startup
            and "if not delivery_route_ready:" in worker_startup
            and "count = await drain_propagation_deliveries()" in worker_startup
            and worker_startup.index(
                "delivery_route_ready = await delivery_targets_ready()"
            )
            < worker_startup.index("count = await drain_propagation_deliveries()")
        ),
        "certification_proves_signed_receipt_store_readiness": (
            "X-Cygnus-Signature: sha256=$delivery_signature" in certification_stack
            and 'readiness_status" = 204' in certification_stack
        ),
        "backup_drill_quiesces_consumer": (
            "compose-control.sh --release $CYGNUS_RELEASE -- quiesce-backend"
            in backup_restore_drill
            and "quiesce-backend" in production_compose_control
        ),
        "backup_drill_resumes_consumer_after_route_proof": (
            "compose-control.sh --release $CYGNUS_RELEASE -- resume-backend"
            in backup_restore_drill
            and "compose_resume_backend" in production_compose_control
        ),
        "rollback_downgrades_with_source_before_legacy_handoff": all(
            fragment in production_rollback
            for fragment in (
                'load_release "$SOURCE_RELEASE"',
                '"${COMPOSE[@]}" run --rm --no-deps api alembic downgrade "$DOWNGRADE_REV"',
                '"${COMPOSE[@]}" rm --stop --force delivery-consumer',
                '"$TARGET_CHECKOUT/scripts/prod/rollback.sh" --release "$RELEASE" --yes',
            )
        )
        and [
            production_rollback.index(fragment)
            for fragment in (
                'load_release "$SOURCE_RELEASE"',
                '"${COMPOSE[@]}" run --rm --no-deps api alembic downgrade "$DOWNGRADE_REV"',
                '"${COMPOSE[@]}" rm --stop --force delivery-consumer',
                '"$TARGET_CHECKOUT/scripts/prod/rollback.sh" --release "$RELEASE" --yes',
            )
        ]
        == sorted(
            production_rollback.index(fragment)
            for fragment in (
                'load_release "$SOURCE_RELEASE"',
                '"${COMPOSE[@]}" run --rm --no-deps api alembic downgrade "$DOWNGRADE_REV"',
                '"${COMPOSE[@]}" rm --stop --force delivery-consumer',
                '"$TARGET_CHECKOUT/scripts/prod/rollback.sh" --release "$RELEASE" --yes',
            )
        ),
        "rollback_requires_target_schema_head": (
            '"$SOURCE_EXPECTED_ALEMBIC_HEAD" != "$TARGET_EXPECTED_ALEMBIC_HEAD"'
            in production_rollback
            and '"$DOWNGRADE_REV" != "$TARGET_EXPECTED_ALEMBIC_HEAD"'
            in production_rollback
        ),
        "rollback_preflight_stdout_is_contract_only": (
            "preflight_target_checkout() (\n  exec 3>&1\n  exec 1>&2"
            in production_rollback
            and 'printf \'%s|%s\' "$EXPECTED_ALEMBIC_HEAD" "$target_has_consumer" >&3'
            in production_rollback
        ),
        "failed_deploy_uses_current_source_rollback": (
            '"$SCRIPT_DIR/rollback.sh" --release "$PREVIOUS" --downgrade target --yes'
            in production_deploy
            and 'CYGNUS_ROLLBACK_SOURCE_METADATA_FILE="$LOADED_RELEASE_FILE"'
            in production_deploy
            and 'CYGNUS_ROLLBACK_SOURCE_INPUTS_FILE="$LOADED_RELEASE_INPUTS_FILE"'
            in production_deploy
            and '"$CHECKOUTS_DIR/$PREVIOUS/scripts/prod/rollback.sh" --release'
            not in production_deploy
        ),
    }
    checks["delivery_consumer_rollout_contract"] = delivery_rollout_checks
    failures.extend(
        f"delivery-consumer rollout contract failed: {name}"
        for name, passed in delivery_rollout_checks.items()
        if not passed
    )

    delivery_route_match = re.search(
        r"(?ms)^    location = /api/internal/propagation-delivery \{\n(.*?)^    \}",
        nginx_template,
    )
    delivery_route = delivery_route_match.group(1) if delivery_route_match else ""
    delivery_route_index = nginx_template.find(
        "location = /api/internal/propagation-delivery"
    )
    generic_api_route_index = nginx_template.find("location ^~ /api/")
    nginx_delivery_checks = {
        "exact_route": bool(delivery_route_match),
        "route_precedes_generic_api": 0
        <= delivery_route_index
        < generic_api_route_index,
        "consumer_proxy": "proxy_pass http://delivery-consumer:8090;" in delivery_route,
        "body_size_bound": "client_max_body_size 1m;" in delivery_route,
        "no_store": 'add_header Cache-Control "no-store" always;' in delivery_route,
        "security_headers": "include /etc/nginx/security-headers.conf;"
        in delivery_route,
        "request_headers_preserved": "proxy_pass_request_headers off;"
        not in nginx_template,
        "ack_header_preserved": (
            "proxy_hide_header X-Cygnus-Ack-Signature;" not in nginx_template
        ),
        "public_readiness_gates_on_consumer": (
            "auth_request /_delivery-consumer-health;" in nginx_template
            and "proxy_pass http://delivery-consumer:8090/health;" in nginx_template
            and "proxy_connect_timeout 1s;" in nginx_template
            and "proxy_read_timeout 2s;" in nginx_template
            and "proxy_send_timeout 2s;" in nginx_template
            and "error_page 500 =503 /_delivery-consumer-not-ready;" in nginx_template
            and '"delivery_consumer":{"status":"failed"}' in nginx_template
            and "https://127.0.0.1:8443/readyz" in production_compose
        ),
    }
    checks["delivery_consumer_nginx_contract"] = nginx_delivery_checks
    failures.extend(
        f"delivery-consumer Nginx contract failed: {name}"
        for name, passed in nginx_delivery_checks.items()
        if not passed
    )

    certification_resume_match = re.search(
        r"(?ms)^  resume\)\n(.*?)^    ;;",
        certification_stack,
    )
    certification_resume = (
        certification_resume_match.group(1) if certification_resume_match else ""
    )
    certification_restart_match = re.search(
        r"(?ms)^  restart\)\n(.*?)^    ;;",
        certification_stack,
    )
    certification_restart = (
        certification_restart_match.group(1) if certification_restart_match else ""
    )
    certification_gated_order = (
        "compose_up_ingress_backend",
        "compose_up_frontend",
        "verify_certification_delivery_ingress",
        "compose_up_workers",
        "verify_certification_ingress",
    )
    certification_resume_order = (
        '"${COMPOSE[@]}" start "${PRODUCTION_INGRESS_BACKEND_SERVICES[@]}"',
        "compose_wait_for_delivery_consumer",
        "verify_certification_delivery_ingress",
        '"${COMPOSE[@]}" start "${PRODUCTION_WORKER_SERVICES[@]}"',
        "verify_certification_ingress",
    )
    certification_restart_order = (
        '"${COMPOSE[@]}" restart "${PRODUCTION_INGRESS_BACKEND_SERVICES[@]}"',
        "compose_wait_for_delivery_consumer",
        '"${COMPOSE[@]}" restart frontend',
        "verify_certification_delivery_ingress",
        '"${COMPOSE[@]}" restart "${PRODUCTION_WORKER_SERVICES[@]}"',
        "verify_certification_ingress",
    )
    certification_recover = certification_stack.partition("  recover)\n")[2].partition(
        "  smoke-exercise)\n"
    )[0]
    certification_rollout = certification_stack.partition("  up|redeploy)\n")[
        2
    ].partition("esac")[0]
    certification_delivery_checks = {
        "uses_production_compose_first": (
            '-f "$COMPOSE_FILE" -f "$CERTIFICATION_COMPOSE_FILE"' in certification_stack
        ),
        "does_not_override_consumer": not bool(
            re.search(r"(?m)^  delivery-consumer:", certification_compose)
        ),
        "does_not_override_frontend": not bool(
            re.search(r"(?m)^  frontend:", certification_compose)
        ),
        "uses_https_origin": (
            'CERTIFICATION_ORIGIN="https://127.0.0.1:$CYGNUS_HTTPS_BIND_PORT"'
            in certification_stack
        ),
        "targets_isolated_candidate_ingress": (
            'CERTIFICATION_DELIVERY_ORIGIN="https://frontend:8443"'
            in certification_stack
            and certification_compose.count(
                "CYGNUS_CERTIFICATION_DELIVERY_TARGETS_JSON"
            )
            == 2
            and certification_compose.count('CYGNUS_DELIVERY_ALLOWED_HOSTS: "frontend"')
            == 2
        ),
        "candidate_tls_trusted_by_senders": (
            "DNS:frontend" in certification_stack
            and certification_compose.count(
                "SSL_CERT_FILE: /run/secrets/cygnus_tls_cert"
            )
            == 2
            and certification_compose.count("- cygnus_tls_cert") == 2
        ),
        "validates_tls_ingress": (
            'curl -fsS --cacert "$CYGNUS_TLS_CERT_FILE"' in certification_stack
        ),
        "validates_exact_delivery_route": (
            "/api/internal/propagation-delivery" in certification_stack
            and '{"detail": "delivery signature is invalid"}' in certification_stack
        ),
        "workers_follow_candidate_route_proof": all(
            all(fragment in section for fragment in certification_gated_order)
            and [section.index(fragment) for fragment in certification_gated_order]
            == sorted(section.index(fragment) for fragment in certification_gated_order)
            for section in (certification_recover, certification_rollout)
        ),
        "quiesces_consumer": (
            '"${COMPOSE[@]}" stop api worker worker-skills delivery-consumer'
            in certification_stack
        ),
        "resume_starts_workers_after_route_proof": (
            all(
                fragment in certification_resume
                for fragment in certification_resume_order
            )
            and [
                certification_resume.index(fragment)
                for fragment in certification_resume_order
            ]
            == sorted(
                certification_resume.index(fragment)
                for fragment in certification_resume_order
            )
        ),
        "restart_starts_workers_after_route_proof": (
            all(
                fragment in certification_restart
                for fragment in certification_restart_order
            )
            and [
                certification_restart.index(fragment)
                for fragment in certification_restart_order
            ]
            == sorted(
                certification_restart.index(fragment)
                for fragment in certification_restart_order
            )
        ),
        "consumer_failure_flips_public_readiness": (
            '"consumer-stop"' in security_certification
            and '"consumer-restart"' in security_certification
            and "consumer_not_ready.status_code != 503" in security_certification
            and "fault-off|consumer-stop|consumer-restart) ;;" in certification_stack
            and "consumer_recovered.status_code != 200" in security_certification
            and "consumer-stop)" in certification_stack
            and "consumer-restart)" in certification_stack
        ),
    }
    checks["certification_delivery_consumer_contract"] = certification_delivery_checks
    failures.extend(
        f"certification delivery-consumer contract failed: {name}"
        for name, passed in certification_delivery_checks.items()
        if not passed
    )
    if "npm ci --no-audit --no-fund" not in _read(root, "frontend/Dockerfile"):
        failures.append("frontend Dockerfile must install through npm ci")
    if "uv sync --frozen" not in _read(root, "Dockerfile"):
        failures.append("backend Dockerfile must install through uv sync --frozen")

    required_workflow_fragments = (
        "uv sync --frozen",
        "uv run ruff check",
        "uv run mypy",
        "uv run pytest",
        "CYGNUS_GOVERNANCE_TEST_DATABASE_URL",
        "CYGNUS_MIGRATION_TEST_DATABASE_URL",
        "CYGNUS_WIKI_IDENTITY_TEST_DATABASE_URL",
        "Prepare isolated Postgres test databases",
        "createdb -U cygnus cygnus_governance_test",
        "npm ci --no-audit --no-fund",
        "npm --prefix frontend exec -- playwright install chromium",
        "npm audit --omit=dev --audit-level=high",
        "npm run lint",
        "npm test",
        "npm run build",
        "governance_golden_path_gate.py",
        "domain_eval_gate.py",
        "migration_gate.py",
        "docker_smoke.sh",
        "--platform linux/amd64,linux/arm64",
        "--provenance=true",
        "--sbom=true",
        "cosign sign",
        "cosign verify",
        "--signature-backend production/signatures/backend.sig",
        "--certificate-backend production/signatures/backend.crt",
        "--signature-frontend production/signatures/frontend.sig",
        "--certificate-frontend production/signatures/frontend.crt",
        "collect_image_attestations.py",
        "backend.bundle.json",
        "frontend.bundle.json",
        "image_reference_gate.py",
        "image_gate.py",
        "release_gate.py",
        "scripts/run_live_production_certification.sh",
        "CYGNUS_RELEASE: ${{ inputs.version || github.ref_name }}",
        "Bind approved production policy to candidate release",
        'scripts/prod/write-release-env.py "$CYGNUS_RELEASE"',
        "scripts/prod/bind-production-inputs.py",
        "CYGNUS_PRODUCTION_INPUTS_TEMPLATE_FILE",
        "scripts/prod/backup_restore_drill.sh",
        "--severity HIGH,CRITICAL",
        "aquasec/trivy:0.74.0@sha256:",
        "--exit-code 0",
        "Upload image scan diagnostics",
        "deploy-production:",
        "needs: [build-staging-images, live-production-certification, promote-release]",
        "runs-on: [self-hosted, cygnus-production-deploy]",
        "CYGNUS_DEPLOY_IDENTITY",
        "CYGNUS_DEPLOY_HOSTNAME",
        "CYGNUS_DEPLOY_CHECKOUTS_DIR",
        "CYGNUS_OPERATOR_WORK_DIR",
        "name: promoted-release",
        'scripts/prod/deploy.sh --release "$RELEASE_VERSION"',
        "Install approved production policy files",
        "--policy-only --output-dir",
        "install_policy CYGNUS_ALERT_THRESHOLDS_FILE",
        "install_policy CYGNUS_CAPACITY_THRESHOLDS_FILE",
        "install_policy CYGNUS_CAPACITY_TARGETS_FILE",
        "validate_capacity_inputs",
    )
    missing_workflow = [
        fragment for fragment in required_workflow_fragments if fragment not in workflow
    ]
    checks["workflow_required_fragments"] = {"missing": missing_workflow}
    failures.extend(
        f"release workflow missing required step/fragment: {fragment}"
        for fragment in missing_workflow
    )
    collector = _read(root, "scripts/collect_image_attestations.py")
    required_collector_fragments = (
        '"--raw"',
        '"{{ json .SBOM }}"',
        '"{{ json .Provenance }}"',
        '"https://spdx.dev/Document"',
        '"https://slsa.dev/provenance/v1"',
        '"linux/amd64"',
        '"linux/arm64"',
        '"image_index_digest"',
        '"manifest_digest"',
    )
    missing_collector = [
        fragment
        for fragment in required_collector_fragments
        if fragment not in collector
    ]
    checks["platform_attestation_collector"] = {"missing": missing_collector}
    failures.extend(
        f"image attestation collector missing required fragment: {fragment}"
        for fragment in missing_collector
    )
    required_repo_guard_fragments = (
        "pgvector/pgvector:0.8.6-pg16-trixie@sha256:",
        "CYGNUS_GOVERNANCE_TEST_DATABASE_URL",
        "CYGNUS_MIGRATION_TEST_DATABASE_URL",
        "CYGNUS_WIKI_IDENTITY_TEST_DATABASE_URL",
        "Prepare isolated Postgres test databases",
        "createdb -U cygnus cygnus_governance_test",
        "bash scripts/repo_check.sh",
    )
    missing_repo_guard = [
        fragment
        for fragment in required_repo_guard_fragments
        if fragment not in repo_guard_workflow
    ]
    checks["repo_guard_required_fragments"] = {"missing": missing_repo_guard}
    failures.extend(
        f"repo guard workflow missing required step/fragment: {fragment}"
        for fragment in missing_repo_guard
    )
    certification_policy_overrides = (
        (
            "CERTIFICATION_CAPACITY_THRESHOLDS_FILE",
            "CYGNUS_CAPACITY_THRESHOLDS_FILE",
        ),
        ("CERTIFICATION_CAPACITY_TARGETS_FILE", "CYGNUS_CAPACITY_TARGETS_FILE"),
        ("CERTIFICATION_ALERT_THRESHOLDS_FILE", "CYGNUS_ALERT_THRESHOLDS_FILE"),
    )
    certification_env_load = certification_stack.index("load_prod_env")
    missing_certification_policy_overrides = [
        runtime_name
        for override_name, runtime_name in certification_policy_overrides
        if (
            f'{override_name}="${{{runtime_name}:-}}"' not in certification_stack
            or f'export {runtime_name}="${override_name}"' not in certification_stack
            or certification_stack.index(f'{override_name}="${{{runtime_name}:-}}"')
            > certification_env_load
            or certification_stack.index(f'export {runtime_name}="${override_name}"')
            < certification_env_load
        )
    ]
    checks["certification_materialized_policy_overrides"] = {
        "missing_or_misordered": missing_certification_policy_overrides
    }
    failures.extend(
        f"certification stack does not preserve materialized policy path: {name}"
        for name in missing_certification_policy_overrides
    )
    live_certification_script = _read(
        root, "scripts/run_live_production_certification.sh"
    )
    requires_runtime_identity = (
        "--require-runtime-identity" in live_certification_script
    )
    checks["live_certification_runtime_identity"] = requires_runtime_identity
    if not requires_runtime_identity:
        failures.append("live certification script must require exact runtime identity")
    canonical_browser_runner = (
        "frontend/scripts/run-browser-certification.mjs" in live_certification_script
    )
    checks["canonical_browser_certification_runner"] = canonical_browser_runner
    if not canonical_browser_runner:
        failures.append(
            "live certification must default to the repository-owned browser runner"
        )
    workflow_texts = {
        path.name: path.read_text(encoding="utf-8")
        for path in (root / ".github/workflows").glob("*.yml")
    }
    unpinned_actions = [
        f"{filename}: {line.strip()}"
        for filename, text in workflow_texts.items()
        for line in text.splitlines()
        if "uses:" in line and not ACTION_SHA_RE.match(line)
    ]
    checks["unpinned_actions"] = unpinned_actions
    failures.extend(
        f"workflow action is not pinned to a commit SHA: {line}"
        for line in unpinned_actions
    )
    if (root / "frontend/pnpm-lock.yaml").exists():
        failures.append(
            "frontend/pnpm-lock.yaml must stay absent after the npm lockfile cutover"
        )
    return {"ok": not failures, "failures": failures, "checks": checks}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = validate_repository(args.repo_root.resolve())
    report = {"gate": "release_contract_gate", **result}
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    if not result["ok"]:
        if not args.quiet:
            print("[release-contract-gate] FAILED", file=sys.stderr)
        for failure in result["failures"]:
            print(f"- {failure}", file=sys.stderr)
        return 1
    if not args.quiet and not args.json:
        print("[release-contract-gate] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
