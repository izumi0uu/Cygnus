"""Focused security baseline tests (CYG security slice).

Covers the fail-closed configuration gate, forwarded-header client IP
resolution, OAuth exact-redirect + required-state + one-time-code semantics,
redirect-URI registration validation, PKCE verification, and admin/mutating
route guards. These tests must not require a live database or Redis.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.sql.elements import ClauseElement
from sqlalchemy.sql.expression import Select, Update

from cygnus.integrations.oauth_service import (
    MAX_REDIRECT_URIS_PER_CLIENT,
    OAuthService,
    validate_redirect_uris,
)
from cygnus.runtime.config import Settings
from cygnus.runtime.database.oauth_models import OAuthAuthCode
from cygnus.runtime.services.auth_service import (
    LoginAttemptLimiter,
    LoginRateLimitExceeded,
    LoginRateLimitUnavailable,
    _peer_is_trusted_proxy,
    authenticate_employee_with_rate_limit,
    get_client_ip,
)


# ---------------------------------------------------------------------------
# Fail-closed configuration gate
# ---------------------------------------------------------------------------


def _secure_production_kwargs(**overrides: str) -> dict[str, Any]:
    kwargs = {
        "environment": "production",
        "secret_key": "CygnusJwt!Q3v9nL2x7Kp5Wm8Rz4Tq6Yh1",
        "mcp_token_pepper": "CygnusMcp!V7n2L9x4Qp6Rz8Tq5Yh1Aa",
        "default_admin_email": "bootstrap-admin@kb.example.com",
        "default_admin_password": "Bootstrap!Admin2026#Strong",
        "minio_access_key": "cygnus-production-app",
        "minio_secret_key": "Minio!Q3v9nL2x7Kp5Wm8Rz4Tq6Yh1Aa",
        "database_url": (
            "postgresql+asyncpg://prod:Database%21Password-For-Production-2026@"
            "db.internal:5432/cygnus"
        ),
        "redis_password": "Redis!Q3v9nL2x7Kp5Wm8Rz4Tq6Yh1Aa",
        "cors_origins": "https://kb.example.com",
        "trusted_proxy_ips": "172.28.0.10",
        "delivery_targets_json": (
            '{"internal-copilot":"https://delivery.example.com/v1"}'
        ),
        "delivery_hmac_secret": "CygnusDelivery!Q3v9nL2x7Kp5Wm8Rz4Tq6Yh1",
    }
    kwargs.update(overrides)
    return kwargs


def test_settings_production_refuses_default_secret_key() -> None:
    settings = Settings(
        **_secure_production_kwargs(secret_key=Settings.DEFAULT_SECRET_KEY)
    )
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        settings.validate_runtime_security()


def test_settings_production_refuses_default_admin_password() -> None:
    settings = Settings(**_secure_production_kwargs(default_admin_password="admin123"))
    with pytest.raises(RuntimeError, match="DEFAULT_ADMIN_PASSWORD"):
        settings.validate_runtime_security()


def test_settings_production_refuses_default_minio_credentials() -> None:
    settings = Settings(
        **_secure_production_kwargs(
            minio_access_key=Settings.DEFAULT_MINIO_ACCESS_KEY,
            minio_secret_key=Settings.DEFAULT_MINIO_SECRET_KEY,
        )
    )
    with pytest.raises(RuntimeError, match="MINIO"):
        settings.validate_runtime_security()


@pytest.mark.parametrize(
    ("field", "value", "label"),
    (
        ("secret_key", "short", "SECRET_KEY"),
        ("mcp_token_pepper", "password", "MCP_TOKEN_PEPPER"),
        ("default_admin_password", "bootstrap-password-only", "DEFAULT_ADMIN_PASSWORD"),
        ("redis_password", "redis", "REDIS_PASSWORD"),
        ("minio_secret_key", "short", "MINIO_SECRET_KEY"),
        ("delivery_hmac_secret", "short", "DELIVERY_HMAC_SECRET"),
    ),
)
def test_settings_production_refuses_weak_runtime_secrets(
    field: str, value: str, label: str
) -> None:
    settings = Settings(**_secure_production_kwargs(**{field: value}))
    with pytest.raises(RuntimeError, match=label):
        settings.validate_runtime_security()


def test_settings_production_refuses_partial_default_object_store_credentials() -> None:
    settings = Settings(
        **_secure_production_kwargs(minio_access_key=Settings.DEFAULT_MINIO_ACCESS_KEY)
    )
    with pytest.raises(RuntimeError, match="MINIO_ACCESS_KEY"):
        settings.validate_runtime_security()


def test_settings_production_refuses_default_bootstrap_identity() -> None:
    settings = Settings(
        **_secure_production_kwargs(default_admin_email=Settings.DEFAULT_ADMIN_EMAIL)
    )
    with pytest.raises(RuntimeError, match="DEFAULT_ADMIN_EMAIL"):
        settings.validate_runtime_security()


def test_settings_production_refuses_database_url_without_strong_password() -> None:
    settings = Settings(
        **_secure_production_kwargs(
            database_url="postgresql+asyncpg://prod:short@db.internal:5432/cygnus"
        )
    )
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        settings.validate_runtime_security()


def test_settings_production_refuses_cors_wildcard() -> None:
    settings = Settings(**_secure_production_kwargs(cors_origins="*"))
    with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
        settings.validate_runtime_security()


def test_settings_production_refuses_insecure_cors_origin() -> None:
    settings = Settings(
        **_secure_production_kwargs(cors_origins="http://kb.example.com")
    )
    with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
        settings.validate_runtime_security()


@pytest.mark.parametrize(
    "delivery_targets_json",
    (
        "{}",
        '{"internal-copilot":"http://delivery.example.com"}',
        '{"internal-copilot":"https://user:pass@delivery.example.com"}',
        '{"internal-copilot":"https://delivery.example.com/path?token=secret"}',
    ),
)
def test_settings_production_requires_safe_delivery_targets(
    delivery_targets_json: str,
) -> None:
    settings = Settings(
        **_secure_production_kwargs(delivery_targets_json=delivery_targets_json)
    )
    with pytest.raises(RuntimeError, match="DELIVERY_TARGETS_JSON"):
        settings.validate_runtime_security()


@pytest.mark.parametrize(
    "trusted_proxy_ips",
    ("127.0.0.1,::1", "0.0.0.0/0", "::/0", "not-an-address"),
)
def test_settings_production_requires_explicit_narrow_proxy_trust(
    trusted_proxy_ips: str,
) -> None:
    settings = Settings(
        **_secure_production_kwargs(trusted_proxy_ips=trusted_proxy_ips)
    )
    with pytest.raises(RuntimeError, match="TRUSTED_PROXY_IPS"):
        settings.validate_runtime_security()


def test_settings_unknown_environment_fails_closed() -> None:
    settings = Settings(**_secure_production_kwargs(environment="sandbox"))
    with pytest.raises(RuntimeError, match="ENVIRONMENT"):
        settings.validate_runtime_security()


def test_settings_staging_refuses_default_secrets() -> None:
    settings = Settings(environment="staging")
    with pytest.raises(RuntimeError) as exc_info:
        settings.validate_runtime_security()
    message = str(exc_info.value)
    assert "ENVIRONMENT=staging" in message
    assert "SECRET_KEY" in message


def test_settings_staging_with_explicit_secure_inputs_passes() -> None:
    settings = Settings(**_secure_production_kwargs(environment="staging"))
    settings.validate_runtime_security()  # must not raise


def test_settings_local_allows_defaults_for_development() -> None:
    settings = Settings()
    assert settings.environment == "local"
    settings.validate_runtime_security()  # must not raise


def test_settings_production_with_explicit_secrets_passes() -> None:
    settings = Settings(**_secure_production_kwargs())
    settings.validate_runtime_security()  # must not raise


def test_login_rate_limit_settings_parse() -> None:
    settings = Settings(
        login_rate_limit_attempts=7,
        login_rate_limit_window_seconds=600,
    )
    assert settings.login_rate_limit_attempts == 7
    assert settings.login_rate_limit_window_seconds == 600


# ---------------------------------------------------------------------------
# Shared Redis login abuse protection (fail-closed)
# ---------------------------------------------------------------------------


class _InMemoryLoginRedis:
    """Redis eval double that tracks login counters and their original TTLs."""

    def __init__(self, *, fail_on_eval_calls: set[int] | None = None) -> None:
        self.values: dict[str, int] = {}
        self.ttls: dict[str, int] = {}
        self.eval_calls: list[tuple[int, tuple[Any, ...]]] = []
        self._fail_on_eval_calls = set(fail_on_eval_calls or ())

    async def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            if key in self.values:
                removed += 1
            self.values.pop(key, None)
            self.ttls.pop(key, None)
        return removed

    async def eval(self, _script: str, number_of_keys: int, *args: Any) -> int:
        self.eval_calls.append((number_of_keys, args))
        if len(self.eval_calls) in self._fail_on_eval_calls:
            raise ConnectionError("redis unavailable")

        if number_of_keys == 1:
            assert len(args) == 3
            key = str(args[0])
            count = self.values.get(key, 0) + 1
            self.values[key] = count
            if count == 1:
                self.ttls[key] = int(args[1])
            return int(count <= int(args[2]))

        if number_of_keys == 2:
            assert len(args) == 2
            email_key = str(args[0])
            ip_key = str(args[1])
            self.values.pop(email_key, None)
            self.ttls.pop(email_key, None)
            ip_count = self.values.get(ip_key)
            if ip_count is None:
                return 0
            if ip_count <= 1:
                self.values.pop(ip_key, None)
                self.ttls.pop(ip_key, None)
                return 0
            self.values[ip_key] = ip_count - 1
            return ip_count - 1

        raise AssertionError(f"unexpected Redis eval key count: {number_of_keys}")


def test_low_privilege_login_preserves_prior_ip_spray_pressure() -> None:
    redis = _InMemoryLoginRedis()
    limiter = LoginAttemptLimiter(redis=redis, max_attempts=3, window_seconds=300)
    client_ip = "203.0.113.17"
    successful_email = "viewer@example.test"
    viewer = SimpleNamespace(role="employee", global_role="viewer", is_admin=False)
    authenticate = AsyncMock(side_effect=[None, None, viewer, None])
    db: Any = object()

    with (
        patch(
            "cygnus.runtime.services.auth_service.get_login_attempt_limiter",
            new=AsyncMock(return_value=limiter),
        ),
        patch(
            "cygnus.runtime.services.auth_service.authenticate_employee",
            new=authenticate,
        ),
    ):
        assert (
            _run(
                authenticate_employee_with_rate_limit(
                    db,
                    "sprayed-one@example.test",
                    "wrong-password",
                    client_ip=client_ip,
                )
            )
            is None
        )
        assert (
            _run(
                authenticate_employee_with_rate_limit(
                    db,
                    "sprayed-two@example.test",
                    "wrong-password",
                    client_ip=client_ip,
                )
            )
            is None
        )

        authenticated = _run(
            authenticate_employee_with_rate_limit(
                db,
                successful_email,
                "correct-password",
                client_ip=client_ip,
            )
        )
        assert authenticated is viewer
        successful_email_key, ip_key = limiter._keys(successful_email, client_ip)
        assert successful_email_key not in redis.values
        assert redis.values[ip_key] == 2
        assert redis.eval_calls[-1][0] == 2

        assert (
            _run(
                authenticate_employee_with_rate_limit(
                    db,
                    "sprayed-three@example.test",
                    "wrong-password",
                    client_ip=client_ip,
                )
            )
            is None
        )
        with pytest.raises(LoginRateLimitExceeded):
            _run(
                authenticate_employee_with_rate_limit(
                    db,
                    "sprayed-four@example.test",
                    "wrong-password",
                    client_ip=client_ip,
                )
            )

    assert authenticate.await_count == 4


def test_success_reconciliation_removes_one_ip_attempt_without_ttl_extension() -> None:
    redis = _InMemoryLoginRedis()
    limiter = LoginAttemptLimiter(redis=redis, max_attempts=5, window_seconds=300)
    client_ip = "198.51.100.42"

    assert _run(limiter.consume(email="failed@example.test", client_ip=client_ip))
    _, ip_key = limiter._keys("failed@example.test", client_ip)
    redis.ttls[ip_key] = 91

    successful_email = "success@example.test"
    assert _run(limiter.consume(email=successful_email, client_ip=client_ip))
    successful_email_key, _ = limiter._keys(successful_email, client_ip)
    assert redis.values[ip_key] == 2

    _run(limiter.reconcile_success(email=successful_email, client_ip=client_ip))

    assert successful_email_key not in redis.values
    assert redis.values[ip_key] == 1
    assert redis.ttls[ip_key] == 91
    assert redis.eval_calls[-1][0] == 2

    # A counter that expires during credential verification must not underflow.
    later_email = "later-success@example.test"
    later_email_key, _ = limiter._keys(later_email, client_ip)
    redis.values[later_email_key] = 1
    redis.ttls[later_email_key] = 91
    redis.values.pop(ip_key)
    redis.ttls.pop(ip_key)

    _run(limiter.reconcile_success(email=later_email, client_ip=client_ip))

    assert later_email_key not in redis.values
    assert ip_key not in redis.values


@pytest.mark.parametrize(
    ("failed_eval_call", "expected_auth_calls"),
    ((1, 0), (3, 1)),
)
def test_login_rate_limit_redis_errors_fail_closed(
    failed_eval_call: int, expected_auth_calls: int
) -> None:
    redis = _InMemoryLoginRedis(fail_on_eval_calls={failed_eval_call})
    limiter = LoginAttemptLimiter(redis=redis, max_attempts=5, window_seconds=300)
    viewer = SimpleNamespace(role="employee", global_role="viewer", is_admin=False)
    authenticate = AsyncMock(return_value=viewer)
    db: Any = object()

    with (
        patch(
            "cygnus.runtime.services.auth_service.get_login_attempt_limiter",
            new=AsyncMock(return_value=limiter),
        ),
        patch(
            "cygnus.runtime.services.auth_service.authenticate_employee",
            new=authenticate,
        ),
        pytest.raises(LoginRateLimitUnavailable),
    ):
        _run(
            authenticate_employee_with_rate_limit(
                db,
                "viewer@example.test",
                "correct-password",
                client_ip="192.0.2.24",
            )
        )

    assert authenticate.await_count == expected_auth_calls


# ---------------------------------------------------------------------------
# Forwarded-header client IP resolution (fail-closed)
# ---------------------------------------------------------------------------


def _make_request(peer: str, x_forwarded_for: str | None = None):
    from starlette.requests import Request

    headers = []
    if x_forwarded_for is not None:
        headers.append((b"x-forwarded-for", x_forwarded_for.encode()))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": headers,
        "query_string": b"",
        "client": (peer, 12345),
        "server": ("testserver", 80),
        "scheme": "http",
    }
    return Request(scope)


def test_get_client_ip_uses_rightmost_entry_from_trusted_proxy() -> None:
    request = _make_request("127.0.0.1", "203.0.113.5, 198.51.100.7")
    assert get_client_ip(request) == "198.51.100.7"


def test_get_client_ip_ignores_forwarded_headers_from_untrusted_peer() -> None:
    request = _make_request("203.0.113.9", "6.6.6.6")
    assert get_client_ip(request) == "203.0.113.9"


def test_get_client_ip_returns_peer_without_forwarded_header() -> None:
    request = _make_request("127.0.0.1")
    assert get_client_ip(request) == "127.0.0.1"


def test_peer_is_trusted_proxy_supports_cidr() -> None:
    trusted = ["127.0.0.1", "172.16.0.0/12", "::1"]
    assert _peer_is_trusted_proxy("172.17.0.3", trusted)
    assert _peer_is_trusted_proxy("10.0.0.3", trusted) is False
    assert _peer_is_trusted_proxy("not-an-ip", trusted) is False


# ---------------------------------------------------------------------------
# OAuth redirect-URI registration validation
# ---------------------------------------------------------------------------


def test_validate_redirect_uris_accepts_https_and_loopback() -> None:
    validate_redirect_uris(
        ["https://kb.example.com/callback", "http://127.0.0.1:4321/callback"]
    )  # must not raise


@pytest.mark.parametrize(
    "redirect_uris",
    [
        [],  # empty
        ["javascript:alert(1)"],  # non-http scheme
        ["https://kb.example.com/cb#fragment"],  # fragment breaks exact match
        ["https://user:pass@kb.example.com/cb"],  # userinfo
        ["not a url"],
        ["https://"],  # no host
        ["https://kb.example.com/cb", "https://kb.example.com/cb2"] * 20,  # too many
        [None],  # non-string
    ],
)
def test_validate_redirect_uris_rejects_unsafe_entries(redirect_uris) -> None:
    with pytest.raises(HTTPException) as exc_info:
        validate_redirect_uris(redirect_uris)
    assert exc_info.value.status_code == 400


def test_validate_redirect_uris_bounds_count() -> None:
    uris = [
        f"https://cb.example.com/{i}" for i in range(MAX_REDIRECT_URIS_PER_CLIENT + 1)
    ]
    with pytest.raises(HTTPException) as exc_info:
        validate_redirect_uris(uris)
    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# OAuth one-time code + exact redirect (service level, mocked session)
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _FakeUpdateResult:
    rowcount = 1


class _FakeSession:
    """Minimal AsyncSession double: select returns the row, update marks used."""

    def __init__(self, auth_code: OAuthAuthCode | None):
        self.auth_code = auth_code
        self.added: list[object] = []
        self.update_executed = False

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        return None

    async def commit(self):
        return None

    async def execute(self, statement: ClauseElement):
        if isinstance(statement, Select):
            if self.auth_code is not None and self.auth_code.used:
                return _FakeResult(None)
            return _FakeResult(self.auth_code)
        if isinstance(statement, Update):
            self.update_executed = True
            if self.auth_code is not None:
                self.auth_code.used = True
            return _FakeUpdateResult()
        raise AssertionError(f"unexpected statement type: {statement!r}")


# RFC 7636 §A.1/§A.2 example PKCE pair — verifier and its S256 challenge.
_PKCE_VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
_PKCE_CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def _unused_auth_code() -> OAuthAuthCode:
    import datetime

    return OAuthAuthCode(
        code="code-123",
        client_id="client_xyz",
        employee_id=uuid.uuid4(),
        redirect_uri="https://cb.example.com/callback",
        code_challenge=_PKCE_CHALLENGE,
        code_challenge_method="S256",
        expires_at=datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(minutes=5),
        used=False,
    )


async def _exchange(
    session: Any,
    *,
    redirect_uri: str = "https://cb.example.com/callback",
) -> str:
    with patch("cygnus.integrations.oauth_service.MCPAuthService") as fake_mcp_cls:
        fake_mcp = fake_mcp_cls.return_value
        fake_mcp.generate_token = AsyncMock(return_value="ark_token_123")
        svc = OAuthService(session)
        return await svc.exchange_code(
            code="code-123",
            client_id="client_xyz",
            redirect_uri=redirect_uri,
            code_verifier=_PKCE_VERIFIER,
        )


def test_oauth_exchange_succeeds_and_marks_code_used() -> None:
    code = _unused_auth_code()
    session = _FakeSession(code)
    token = _run(_exchange(session))
    assert token == "ark_token_123"
    assert session.update_executed  # code marked used
    assert code.used


def test_oauth_exchange_is_one_time() -> None:
    code = _unused_auth_code()
    session = _FakeSession(code)
    assert _run(_exchange(session)) == "ark_token_123"
    with pytest.raises(HTTPException) as exc_info:
        _run(_exchange(session))
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "invalid_grant"


def test_oauth_exchange_rejects_mismatched_redirect_uri() -> None:
    code = _unused_auth_code()
    session = _FakeSession(code)
    with pytest.raises(HTTPException) as exc_info:
        _run(_exchange(session, redirect_uri="https://evil.example.com/cb"))
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "invalid_grant"


# ---------------------------------------------------------------------------
# PKCE S256 verification
# ---------------------------------------------------------------------------


def test_pkce_s256_verification_accepts_correct_verifier() -> None:
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    challenge = (
        "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"  # RFC 7636 §A.1/§A.2 example
    )
    assert OAuthService._verify_pkce(verifier, challenge, "S256") is True


def test_pkce_s256_verification_rejects_wrong_verifier_and_method() -> None:
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    challenge = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    assert OAuthService._verify_pkce("wrong-verifier", challenge, "S256") is False
    assert OAuthService._verify_pkce(verifier, challenge, "plain") is False


# ---------------------------------------------------------------------------
# OAuth authorize endpoint: required state + exact redirect (router level)
# ---------------------------------------------------------------------------


@pytest.fixture()
def oauth_client_app():
    from cygnus.runtime.main import create_app

    app = create_app(app_settings=Settings())
    return TestClient(app)


def test_authorize_requires_state_before_any_lookup(oauth_client_app) -> None:
    resp = oauth_client_app.get(
        "/oauth/authorize",
        params={
            "client_id": "client_xyz",
            "redirect_uri": "https://cb.example.com/callback",
            "response_type": "code",
            "code_challenge": "challenge",
        },
    )
    assert resp.status_code == 400
    assert "state" in resp.text.lower() or resp.json()["detail"] == "invalid_state"


def test_authorize_rejects_redirect_uri_prefix_attack(oauth_client_app) -> None:
    from cygnus.runtime.database.oauth_models import OAuthClient

    client = OAuthClient(
        client_id="client_xyz",
        name="Test",
        redirect_uris=["https://cb.example.com/callback"],
    )

    class _FakeSvc:
        def __init__(self, db):
            self.db = db

        async def get_client(self, client_id: str):
            return client if client_id == "client_xyz" else None

    with patch("cygnus.runtime.routers.oauth.OAuthService", _FakeSvc):
        # Substring/prefix look-alike must be rejected (exact match only).
        resp = oauth_client_app.get(
            "/oauth/authorize",
            params={
                "client_id": "client_xyz",
                "redirect_uri": "https://cb.example.com.evil.com/callback",
                "response_type": "code",
                "code_challenge": "challenge",
                "state": "state-abc",
            },
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == "invalid_redirect_uri"

        # Exact registered redirect_uri renders the login form.
        resp = oauth_client_app.get(
            "/oauth/authorize",
            params={
                "client_id": "client_xyz",
                "redirect_uri": "https://cb.example.com/callback",
                "response_type": "code",
                "code_challenge": "challenge",
                "state": "state-abc",
            },
        )
        assert resp.status_code == 200
        assert "Sign in" in resp.text


def test_login_form_escapes_redirect_uri_and_state(oauth_client_app) -> None:
    from cygnus.runtime.database.oauth_models import OAuthClient

    client = OAuthClient(
        client_id="client_xyz",
        name="Test",
        redirect_uris=["https://cb.example.com/callback"],
    )

    class _FakeSvc:
        def __init__(self, db):
            self.db = db

        async def get_client(self, client_id: str):
            return client

    with patch("cygnus.runtime.routers.oauth.OAuthService", _FakeSvc):
        resp = oauth_client_app.get(
            "/oauth/authorize",
            params={
                "client_id": "client_xyz",
                "redirect_uri": "https://cb.example.com/callback",
                "response_type": "code",
                "code_challenge": "challenge",
                "state": '"><script>alert(1)</script>',
            },
        )
        assert resp.status_code == 200
        assert "<script>alert(1)</script>" not in resp.text
        assert "&lt;script&gt;" in resp.text


def test_production_dynamic_oauth_registration_is_disabled() -> None:
    from cygnus.runtime.main import create_app

    app = create_app(app_settings=Settings(**_secure_production_kwargs()))
    client = TestClient(app)
    try:
        response = client.post(
            "/oauth/register",
            json={
                "client_name": "untrusted",
                "redirect_uris": ["https://attacker.example/callback"],
            },
        )
    finally:
        client.close()
    assert response.status_code == 403
    assert response.json()["detail"] == "dynamic_client_registration_disabled"


def test_production_oauth_metadata_does_not_advertise_dynamic_registration() -> None:
    from cygnus.runtime.main import create_app

    app = create_app(app_settings=Settings(**_secure_production_kwargs()))
    client = TestClient(app)
    try:
        response = client.get("/.well-known/oauth-authorization-server")
    finally:
        client.close()
    assert response.status_code == 200
    assert "registration_endpoint" not in response.json()


def test_production_compose_sets_runtime_environment_gate() -> None:
    from pathlib import Path

    compose = Path("deploy/docker-compose.prod.yml").read_text(encoding="utf-8")
    env_example = Path("deploy/.env.prod.example").read_text(encoding="utf-8")
    assert 'ENVIRONMENT: "production"' in compose
    assert "ENVIRONMENT=production" in env_example


# ---------------------------------------------------------------------------
# Admin / mutating route guards
# ---------------------------------------------------------------------------


def test_admin_settings_endpoints_require_authentication(oauth_client_app) -> None:
    checks = [
        ("get", "/api/dashboard/stats", None),
        ("get", "/api/settings/providers", None),
        ("get", "/api/settings", None),
        ("post", "/api/settings/test-llm", None),
        ("post", "/api/settings/test-providers", None),
        ("put", "/api/settings", {"settings": {"llm_api_key": "secret"}}),
    ]
    for method, path, json_body in checks:
        resp = oauth_client_app.request(method, path, json=json_body)
        assert resp.status_code == 401, f"{method.upper()} {path} -> {resp.status_code}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(awaitable):
    import asyncio

    return asyncio.run(awaitable)
