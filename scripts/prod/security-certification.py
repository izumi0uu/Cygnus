#!/usr/bin/env python3
"""Exercise Production V1 security boundaries against the isolated candidate stack."""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import cast
import uuid
from urllib.parse import parse_qs, urlsplit

import httpx


class Args(argparse.Namespace):
    def __init__(self) -> None:
        super().__init__()
        self.report: Path = Path()
        self.git_sha: str = ""
        self.backend_image: str = ""
        self.frontend_image: str = ""
        self.alembic_head: str = ""


def command(
    *args: str, expect_success: bool = True
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, capture_output=True, check=False, text=True)
    if expect_success and result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(args)}\n{result.stderr[-2000:]}"
        )
    return result


def response_json(response: httpx.Response) -> dict[str, object]:
    payload = cast(object, response.json())
    if not isinstance(payload, dict):
        raise RuntimeError(
            f"{response.request.method} {response.request.url} returned non-object JSON"
        )
    return cast(dict[str, object], payload)


def scan_summary(path: Path) -> dict[str, object]:
    raw_payload = cast(object, json.loads(path.read_text(encoding="utf-8")))
    if not isinstance(raw_payload, dict):
        raise RuntimeError(f"scan report is not an object: {path}")
    payload = cast(dict[str, object], raw_payload)
    results = payload.get("Results", [])
    vulnerabilities: list[dict[str, object]] = []
    if isinstance(results, list):
        for raw_result in cast(list[object], results):
            if not isinstance(raw_result, dict):
                continue
            result = cast(dict[str, object], raw_result)
            raw_vulnerabilities = result.get("Vulnerabilities")
            if isinstance(raw_vulnerabilities, list):
                vulnerabilities.extend(
                    cast(dict[str, object], item)
                    for item in cast(list[object], raw_vulnerabilities)
                    if isinstance(item, dict)
                )
    blocking = [
        item for item in vulnerabilities if item.get("Severity") in {"HIGH", "CRITICAL"}
    ]
    if blocking:
        raise RuntimeError(
            f"{path} contains {len(blocking)} HIGH/CRITICAL vulnerabilities"
        )
    return {"report": path.name, "blocking_vulnerabilities": 0}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for option in (
        "report",
        "git-sha",
        "backend-image",
        "frontend-image",
        "alembic-head",
    ):
        _ = parser.add_argument(
            f"--{option}", required=True, type=Path if option == "report" else str
        )
    args = parser.parse_args(argv, namespace=Args())
    base_url = os.environ.get("CYGNUS_CERTIFICATION_TARGET_ORIGIN", "").rstrip("/")
    release = os.environ.get("CYGNUS_RELEASE", "")
    admin_email = os.environ.get("DEFAULT_ADMIN_EMAIL", "")
    admin_password = os.environ.get("DEFAULT_ADMIN_PASSWORD", "")
    oauth_client_id = os.environ.get("CYGNUS_SECURITY_OAUTH_CLIENT_ID", "")
    if not all((base_url, release, admin_email, admin_password, oauth_client_id)):
        raise RuntimeError(
            "candidate origin, release, admin credentials, and OAuth client are required"
        )

    timeout = httpx.Timeout(30.0)
    with httpx.Client(
        base_url=base_url, timeout=timeout, follow_redirects=False
    ) as client:
        unauthenticated = client.get("/api/auth/me")
        if unauthenticated.status_code != 401:
            raise RuntimeError("unauthenticated profile read was not denied")

        login = client.post(
            "/api/auth/login", json={"email": admin_email, "password": admin_password}
        )
        if login.status_code != 200:
            raise RuntimeError(f"admin login failed: {login.status_code}")
        token = response_json(login).get("access_token")
        if not isinstance(token, str) or not token:
            raise RuntimeError("admin login returned no access token")
        admin_headers = {"Authorization": f"Bearer {token}"}

        suffix = uuid.uuid4().hex[:12]
        employee_email = f"security-{suffix}@cygnus.invalid"
        employee_password = f"Cygnus-Security-{suffix}!"
        created = client.post(
            "/api/employees",
            headers=admin_headers,
            json={
                "name": "Security Boundary Probe",
                "email": employee_email,
                "password": employee_password,
                "role": "employee",
                "global_role": "viewer",
                "department_ids": [],
            },
        )
        if created.status_code != 201:
            raise RuntimeError(
                f"security employee creation failed: {created.status_code} {created.text}"
            )
        employee_login = client.post(
            "/api/auth/login",
            json={"email": employee_email, "password": employee_password},
        )
        employee_token = response_json(employee_login).get("access_token")
        if employee_login.status_code != 200 or not isinstance(employee_token, str):
            raise RuntimeError("security employee login failed")
        forbidden = client.get(
            "/api/employees", headers={"Authorization": f"Bearer {employee_token}"}
        )
        if forbidden.status_code != 403:
            raise RuntimeError(
                "viewer employee crossed the employee-management boundary"
            )

        registration = client.post(
            "/oauth/register",
            json={
                "client_name": "Untrusted dynamic client",
                "redirect_uris": [f"{base_url}/oauth/callback"],
            },
        )
        if registration.status_code != 403:
            raise RuntimeError("production dynamic OAuth registration was not disabled")

        redirect_uri = f"{base_url}/oauth/callback"
        verifier = uuid.uuid4().hex + uuid.uuid4().hex
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
            .rstrip(b"=")
            .decode("ascii")
        )
        oauth_state = f"security-{uuid.uuid4().hex}"
        authorization = client.get(
            "/oauth/authorize",
            params={
                "client_id": oauth_client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "state": oauth_state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )
        if (
            authorization.status_code != 200
            or '<form method="post">' not in authorization.text
        ):
            raise RuntimeError("operator-provisioned OAuth client was not authorized")
        authorization_result = client.post(
            "/oauth/authorize",
            data={
                "client_id": oauth_client_id,
                "redirect_uri": redirect_uri,
                "state": oauth_state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "email": admin_email,
                "password": admin_password,
            },
        )
        if authorization_result.status_code != 302:
            raise RuntimeError(
                f"OAuth authorization failed: {authorization_result.status_code}"
            )
        raw_location = cast(object, authorization_result.headers.get("location"))
        if not isinstance(raw_location, str):
            raise RuntimeError("OAuth authorization returned no callback location")
        callback = urlsplit(raw_location)
        callback_query = parse_qs(callback.query)
        code_values = callback_query.get("code", [])
        if (
            f"{callback.scheme}://{callback.netloc}{callback.path}" != redirect_uri
            or callback_query.get("state") != [oauth_state]
            or len(code_values) != 1
        ):
            raise RuntimeError(
                "OAuth callback was not exactly bound to redirect and state"
            )
        exchange_form = {
            "grant_type": "authorization_code",
            "code": code_values[0],
            "redirect_uri": redirect_uri,
            "client_id": oauth_client_id,
            "code_verifier": verifier,
        }
        exchange = client.post("/oauth/token", data=exchange_form)
        oauth_access_token = response_json(exchange).get("access_token")
        if exchange.status_code != 200 or not isinstance(oauth_access_token, str):
            raise RuntimeError("OAuth PKCE code exchange failed")
        replay = client.post("/oauth/token", data=exchange_form)
        if replay.status_code != 400 or "invalid_grant" not in replay.text:
            raise RuntimeError("OAuth authorization code replay was not rejected")

        oauth_output = client.get(
            "/oauth/authorize",
            params={
                "client_id": "<script>alert(1)</script>",
                "redirect_uri": "https://client.invalid/callback",
                "response_type": "code",
                "state": "bounded-state",
                "code_challenge": "a" * 43,
                "code_challenge_method": "S256",
            },
        )
        if oauth_output.status_code != 400 or "<script>" in oauth_output.text:
            raise RuntimeError("OAuth invalid-client output reflected unsafe input")
        invalid_state = client.get(
            "/oauth/authorize",
            params={
                "client_id": "invalid",
                "redirect_uri": "https://client.invalid/callback",
                "response_type": "code",
                "state": "",
                "code_challenge": "a" * 43,
                "code_challenge_method": "S256",
            },
        )
        if (
            invalid_state.status_code != 400
            or "invalid_state" not in invalid_state.text
        ):
            raise RuntimeError("OAuth missing state was not rejected")
        invalid_pkce = client.get(
            "/oauth/authorize",
            params={
                "client_id": "invalid",
                "redirect_uri": "https://client.invalid/callback",
                "response_type": "code",
                "state": "bounded-state",
                "code_challenge": "a" * 43,
                "code_challenge_method": "plain",
            },
        )
        if (
            invalid_pkce.status_code != 400
            or "unsupported_code_challenge_method" not in invalid_pkce.text
        ):
            raise RuntimeError("OAuth non-S256 PKCE was not rejected")

        abuse_statuses = [
            client.post(
                "/api/auth/login",
                json={"email": employee_email, "password": f"wrong-{attempt}"},
            ).status_code
            for attempt in range(6)
        ]
        if set(abuse_statuses) != {401}:
            raise RuntimeError(f"login abuse responses leaked state: {abuse_statuses}")

        forwarded = client.get(
            "/api/auth/status",
            headers={"X-Forwarded-For": "203.0.113.8, injected.invalid"},
        )
        if forwarded.status_code != 200 or "injected.invalid" in forwarded.text:
            raise RuntimeError(
                "malformed forwarded chain was reflected or rejected unsafely"
            )

        document = client.get("/")
        required_headers: dict[str, str] = {
            "strict-transport-security": "max-age=",
            "content-security-policy": "default-src 'self'",
            "x-frame-options": "DENY",
            "x-content-type-options": "nosniff",
        }
        missing_headers = {
            name: expected
            for name, expected in required_headers.items()
            if expected.lower()
            not in str(cast(object, document.headers.get(name, ""))).lower()
        }
        if document.status_code != 200 or missing_headers:
            raise RuntimeError(
                f"browser security headers are incomplete: {missing_headers}"
            )

    insecure = command(
        "docker",
        "run",
        "--rm",
        "--entrypoint",
        "python",
        "-e",
        "ENVIRONMENT=production",
        "-e",
        "SECRET_KEY=change-me-to-a-random-secret-string",
        args.backend_image,
        "-c",
        "from cygnus.runtime.config import get_settings; get_settings()",
        expect_success=False,
    )
    if insecure.returncode == 0:
        raise RuntimeError("candidate image accepted insecure production configuration")

    repo_root = Path(__file__).resolve().parents[2]
    _ = command("uv", "run", "python", "scripts/release_contract_gate.py")
    scans = [
        scan_summary(repo_root / "production/scans/backend-trivy.json"),
        scan_summary(repo_root / "production/scans/frontend-trivy.json"),
    ]
    stack = repo_root / "scripts/prod/certification-stack.sh"
    _ = command(str(stack), "consumer-stop", "--release", release)
    try:
        consumer_not_ready = httpx.get(f"{base_url}/readyz", timeout=timeout)
        not_ready_body = response_json(consumer_not_ready)
        consumer_check = not_ready_body.get("checks")
        if (
            consumer_not_ready.status_code != 503
            or not_ready_body.get("status") != "not_ready"
            or not isinstance(consumer_check, dict)
            or consumer_check.get("delivery_consumer") != {"status": "failed"}
        ):
            raise RuntimeError(
                "public readiness stayed healthy after delivery-consumer failure"
            )
    finally:
        _ = command(str(stack), "consumer-restart", "--release", release)
    consumer_recovered = httpx.get(f"{base_url}/readyz", timeout=timeout)
    if (
        consumer_recovered.status_code != 200
        or response_json(consumer_recovered).get("status") != "ready"
    ):
        raise RuntimeError("public readiness did not recover with delivery-consumer")

    _ = command(str(stack), "restart", "--release", release)
    ready = httpx.get(f"{base_url}/readyz", timeout=timeout)
    if ready.status_code != 200 or response_json(ready).get("status") != "ready":
        raise RuntimeError("candidate did not recover after actionable restart")

    checks = [
        {
            "name": "production-config-rejection",
            "passed": True,
            "details": {
                "candidate_exit_code": insecure.returncode,
                "default_secret_rejected": True,
            },
        },
        {
            "name": "authentication-boundary",
            "passed": True,
            "details": {"unauthenticated_status": unauthenticated.status_code},
        },
        {
            "name": "authorization-boundary",
            "passed": True,
            "details": {"viewer_admin_route_status": forbidden.status_code},
        },
        {
            "name": "oauth-output-safety",
            "passed": True,
            "details": {
                "invalid_client_status": oauth_output.status_code,
                "unsafe_input_reflected": False,
            },
        },
        {
            "name": "oauth-state-validation",
            "passed": True,
            "details": {"missing_state_status": invalid_state.status_code},
        },
        {
            "name": "oauth-pkce-validation",
            "passed": True,
            "details": {"plain_pkce_status": invalid_pkce.status_code},
        },
        {
            "name": "oauth-production-registration-policy",
            "passed": True,
            "details": {
                "dynamic_registration_status": registration.status_code,
                "operator_client": True,
            },
        },
        {
            "name": "oauth-authorization-code-pkce",
            "passed": True,
            "details": {
                "authorization_status": authorization_result.status_code,
                "exchange_status": exchange.status_code,
                "replay_status": replay.status_code,
                "state_bound": True,
            },
        },
        {
            "name": "login-abuse-protection",
            "passed": True,
            "details": {
                "attempts": len(abuse_statuses),
                "indistinguishable_statuses": abuse_statuses,
            },
        },
        {
            "name": "forwarded-header-trust",
            "passed": True,
            "details": {
                "malformed_chain_reflected": False,
                "status": forwarded.status_code,
            },
        },
        {
            "name": "browser-security-headers",
            "passed": True,
            "details": {"headers": sorted(required_headers)},
        },
        {
            "name": "dependency-security-gate",
            "passed": True,
            "details": {"image_scans": scans},
        },
        {
            "name": "static-security-gate",
            "passed": True,
            "details": {"gate": "scripts/release_contract_gate.py", "status": "passed"},
        },
        {
            "name": "delivery-consumer-readiness",
            "passed": True,
            "details": {
                "failed_status": consumer_not_ready.status_code,
                "recovered_status": consumer_recovered.status_code,
            },
        },
        {
            "name": "actionable-failure-recovery",
            "passed": True,
            "details": {"action": "candidate stack restart", "ready_status": "ready"},
        },
    ]
    report = {
        "report_format": "cygnus-security-failure-injection-report/v1",
        "status": "passed",
        "git_sha": args.git_sha,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "release_identity": {
            "git_commit": args.git_sha,
            "backend_image_ref": args.backend_image,
            "frontend_image_ref": args.frontend_image,
            "alembic_head": args.alembic_head,
        },
        "target": {"origin": base_url, "environment": "isolated-candidate"},
        "checks": checks,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    _ = args.report.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    args.report.chmod(0o600)
    print(f"[security-certification] passed; report={args.report}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        OSError,
        RuntimeError,
        ValueError,
        httpx.HTTPError,
        json.JSONDecodeError,
    ) as exc:
        print(f"[security-certification] ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
