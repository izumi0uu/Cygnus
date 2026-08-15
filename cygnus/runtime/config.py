"""
Application configuration loaded from environment variables.
"""

import ipaddress
import json
from functools import lru_cache
from typing import ClassVar
from urllib.parse import unquote, urlsplit

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Infrastructure settings loaded from .env or environment.

    AI provider settings (embedding, LLM, vision) are NOT here —
    they are stored in the database and managed via Admin Portal.
    See: cygnus/runtime/services/config_service.py and cygnus/runtime/ai/registry.py
    """

    # --- Database ---
    database_url: str = Field(
        default="postgresql+asyncpg://cygnus:cygnus_secret@localhost:5432/cygnus",
        description="PostgreSQL connection string (async)",
    )

    # --- Auth ---
    secret_key: str = Field(
        default="change-me-to-a-random-secret-string",
        description="Secret key for signing JWT tokens and encrypting config values",
    )
    default_admin_email: str = Field(
        default="admin@cygnus.local",
        description="Email for the initial admin account (created on first startup)",
    )
    default_admin_password: str = Field(
        default="admin123",
        description="Password for the initial admin account",
    )
    mcp_token_pepper: str = Field(
        default="change-me-to-a-random-pepper",
        description=(
            "HMAC pepper used to hash MCP bearer tokens at rest. "
            "Rotating this invalidates every existing token — set once and keep stable."
        ),
    )

    # --- MinIO ---
    minio_endpoint: str = Field(default="localhost:9000")
    minio_public_endpoint: str = Field(
        default="",
        description="Public-facing MinIO address used in presigned URLs (browser-accessible). "
        "Defaults to minio_endpoint if not set. "
        "In Docker: set to 'localhost:9000' so presigned URLs work from the browser.",
    )
    minio_access_key: str = Field(default="minioadmin")
    minio_secret_key: str = Field(default="minioadmin123")
    minio_bucket: str = Field(default="cygnus-files")
    minio_secure: bool = Field(default=False)
    minio_presign_expiry_hours: int = Field(default=24)

    # --- CORS ---
    cors_origins: str = Field(default="*")

    # --- Portal ---
    portal_base_url: str = Field(
        default="",
        description="Public base URL of the admin/portal frontend (e.g. "
        "'https://kb.acme.local'). Used to build clickable links to "
        "source documents in MCP search results. Empty → relative "
        "'/wiki/source/<id>' paths.",
    )

    # --- Redis (arq worker queue) ---
    redis_host: str = Field(default="localhost")
    redis_port: int = Field(default=6379)
    redis_password: str = Field(default="")
    redis_db: int = Field(default=0)
    worker_max_jobs: int = Field(default=3, description="Max concurrent ingestion jobs")
    worker_job_timeout: int = Field(default=1800, description="Job timeout in seconds")

    # --- Runtime health / worker heartbeat ---
    health_probe_timeout_seconds: float = Field(
        default=5.0,
        description="Per-dependency timeout for readiness probes (livez never probes).",
    )
    worker_heartbeat_interval_seconds: int = Field(
        default=10,
        description="Seconds between worker heartbeat refreshes.",
    )
    worker_heartbeat_timeout_seconds: int = Field(
        default=30,
        description="Seconds after which a stale worker heartbeat fails readiness. "
        "Must be greater than worker_heartbeat_interval_seconds.",
    )
    worker_drain_grace_seconds: int = Field(
        default=30,
        description="Grace period for in-flight jobs after a worker receives SIGTERM; "
        "arq stops claiming new jobs and waits up to this window.",
    )

    # --- Source ingestion safety ---
    max_source_upload_bytes: int = Field(
        default=25 * 1024 * 1024,
        description="Maximum accepted source upload size in bytes.",
    )
    max_source_url_bytes: int = Field(
        default=25 * 1024 * 1024,
        description="Maximum downloaded URL source size in bytes.",
    )
    max_source_archive_bytes: int = Field(
        default=100 * 1024 * 1024,
        description="Maximum individual and aggregate uncompressed archive size in bytes.",
    )
    max_source_archive_members: int = Field(
        default=1_000,
        description="Maximum number of members allowed in a source archive.",
    )
    max_source_archive_ratio: int = Field(
        default=100,
        description=(
            "Maximum allowed uncompressed/compressed size ratio per archive "
            "member (zip bomb guard)."
        ),
    )
    max_source_xml_depth: int = Field(
        default=64,
        description="Maximum element nesting depth for XML parsed from source archives.",
    )
    max_source_url_fetch_seconds: float = Field(
        default=30.0,
        description="Per-hop timeout (seconds) for public source URL fetches.",
    )

    # --- MRP Pipeline ---
    mrp_auto_approve_plan: bool = Field(
        default=False,
        description="If True, compilation plans are auto-approved without human review",
    )
    mrp_multipass_writer_enabled: bool = Field(
        default=True,
        description="If True, REFINE uses multi-pass writer when source > budget; if False, falls back to single-pass with tiered selection",
    )
    auto_approve_extraction_threshold_tokens: int = Field(
        default=200_000,
        description="Doc <= this many tokens after extraction auto-proceeds. Larger docs pause at status='awaiting_approval' for human review.",
    )
    extraction_approval_ttl_hours: int = Field(
        default=24,
        description="Orphan sources stuck in 'awaiting_approval' longer than this are auto-deleted by cleanup cron.",
    )
    max_auto_recover_attempts: int = Field(
        default=3,
        description="Max times a source may be auto-flipped from stuck 'processing' back to 'error' before the retry API refuses further attempts. Prevents token-burning loops when the failure is deterministic (bad provider key, malformed file).",
    )

    # --- Propagation delivery (internal-channel adapter) ---
    delivery_targets_json: str = Field(
        default="{}",
        description=(
            "JSON map of propagation surface id -> allowed internal delivery "
            "base URL. This is the destination allowlist: only surfaces listed "
            "here receive outbound delivery attempts, and every outbound hop "
            "(including redirects) must stay inside the configured origins."
        ),
    )
    delivery_hmac_secret: str = Field(
        default="",
        description=(
            "HMAC-SHA256 secret shared with internal delivery targets. Signs "
            "outbound delivery bodies and verifies signed acknowledgements. "
            "Never log this value. Empty disables signed acknowledgement "
            "acceptance (fail closed)."
        ),
    )
    delivery_timeout_seconds: float = Field(
        default=10.0,
        description="Outbound delivery HTTP timeout in seconds (bounded retries).",
    )
    delivery_max_attempts: int = Field(
        default=5,
        ge=1,
        description=(
            "Maximum bounded delivery attempts before a propagation delivery "
            "is dead-lettered with durable attempt evidence."
        ),
    )

    # --- Environment / fail-closed gate ---
    environment: str = Field(
        default="local",
        description=(
            "Deployment environment: 'local', 'test', 'staging', or "
            "'production'. Outside local/test the runtime refuses to start "
            "while any default secret, default credential, or wide-open CORS "
            "remains."
        ),
    )

    # --- Login abuse budget (shared Redis) ---
    login_rate_limit_attempts: int = Field(
        default=5,
        ge=1,
        description=(
            "Max failed login attempts per (email, client IP) inside the "
            "window before the shared Redis budget blocks further tries."
        ),
    )
    login_rate_limit_window_seconds: int = Field(
        default=300,
        ge=1,
        description="Time window (seconds) for the login-attempt budget.",
    )

    # --- Reverse proxy trust (forwarded headers) ---
    trusted_proxy_ips: str = Field(
        default="127.0.0.1,::1",
        description=(
            "Comma-separated IPs or CIDRs whose X-Forwarded-For header is "
            "trusted when resolving the client IP for abuse budgets. "
            "Outside local/test this must be an explicit, narrow deployment "
            "input; forwarded headers from every other peer are ignored."
        ),
    )

    # --- Observability / telemetry (CYG-142) ---
    telemetry_enabled: bool = Field(
        default=True,
        description=(
            "Master switch for the bounded observability surface "
            "(correlation context, RED metrics, spans). False keeps the "
            "context API functional but disables metric/span recording."
        ),
    )
    prometheus_metrics_enabled: bool = Field(
        default=True,
        description="Serve the bounded metric registry at the /metrics endpoint.",
    )
    otlp_endpoint: str = Field(
        default="",
        description=(
            "Optional OTLP/HTTP endpoint for span export "
            "(e.g. http://otel-collector:4318/v1/traces). Empty disables OTel "
            "export; the in-process span fallback still applies."
        ),
    )
    otlp_service_name: str = Field(
        default="cygnus",
        description="OTel service.name attribute for exported spans.",
    )
    telemetry_max_label_length: int = Field(
        default=64,
        ge=16,
        le=128,
        description="Maximum length of sanitized metric/span label values.",
    )
    telemetry_max_series_per_metric: int = Field(
        default=200,
        ge=16,
        le=10000,
        description=(
            "Bounded distinct label combinations per metric; overflow samples "
            "are dropped and counted as telemetry failures."
        ),
    )

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    # Known default secrets/credentials the runtime refuses to run with
    # outside local/test. Kept as module constants so tests can reuse them.
    DEFAULT_SECRET_KEY: ClassVar[str] = "change-me-to-a-random-secret-string"
    DEFAULT_MCP_TOKEN_PEPPER: ClassVar[str] = "change-me-to-a-random-pepper"
    DEFAULT_ADMIN_EMAIL: ClassVar[str] = "admin@cygnus.local"
    DEFAULT_ADMIN_PASSWORD: ClassVar[str] = "admin123"
    DEFAULT_REDIS_PASSWORD: ClassVar[str] = ""
    DEFAULT_TRUSTED_PROXY_IPS: ClassVar[frozenset[str]] = frozenset(
        {"127.0.0.1", "::1"}
    )
    DEFAULT_MINIO_ACCESS_KEY: ClassVar[str] = "minioadmin"
    DEFAULT_MINIO_SECRET_KEY: ClassVar[str] = "minioadmin123"
    DEFAULT_DATABASE_URL: ClassVar[str] = (
        "postgresql+asyncpg://cygnus:cygnus_secret@localhost:5432/cygnus"
    )
    MIN_SECRET_LENGTH: ClassVar[int] = 32
    MIN_SECRET_DISTINCT_CHARACTERS: ClassVar[int] = 8
    MIN_ADMIN_PASSWORD_LENGTH: ClassVar[int] = 14
    WEAK_SECRET_VALUES: ClassVar[frozenset[str]] = frozenset(
        {
            "admin",
            "changeme",
            "change-me",
            "default",
            "example",
            "password",
            "secret",
            "test",
        }
    )
    LOCAL_TEST_ENVIRONMENTS: ClassVar[frozenset[str]] = frozenset({"local", "test"})
    VALID_ENVIRONMENTS: ClassVar[frozenset[str]] = frozenset(
        {"local", "test", "staging", "production"}
    )

    @property
    def cors_origin_list(self) -> list[str]:
        """Parse CORS_ORIGINS into a list."""
        value = self.cors_origins.strip()
        if value == "*":
            return ["*"]
        return [o.strip() for o in value.split(",") if o.strip()]

    @property
    def delivery_targets(self) -> dict[str, str]:
        """Parse DELIVERY_TARGETS_JSON into {surface_id: base_url}.

        Raises ValueError on malformed JSON so misconfiguration fails loudly
        at the adapter boundary instead of silently skipping delivery.
        """
        try:
            parsed = json.loads(self.delivery_targets_json or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError(f"delivery_targets_json is not valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("delivery_targets_json must be a JSON object")
        targets: dict[str, str] = {}
        for surface_id, raw_url in parsed.items():
            normalized_surface = str(surface_id).strip()
            if not normalized_surface:
                raise ValueError("delivery_targets_json keys must not be blank")
            if not isinstance(raw_url, str) or not raw_url.strip():
                raise ValueError(
                    f"delivery target for {normalized_surface} must be a non-empty URL string"
                )
            targets[normalized_surface] = raw_url.strip()
        return targets

    @classmethod
    def _secret_is_weak(cls, value: object) -> bool:
        """Return whether a production secret is absent, known, or trivially weak."""
        if not isinstance(value, str):
            return True
        normalized = value.strip()
        if not normalized:
            return True
        if normalized.casefold() in cls.WEAK_SECRET_VALUES:
            return True
        return (
            len(normalized) < cls.MIN_SECRET_LENGTH
            or len(set(normalized)) < cls.MIN_SECRET_DISTINCT_CHARACTERS
        )

    @classmethod
    def _admin_password_is_weak(cls, value: object) -> bool:
        """Apply an explicit production bootstrap-password policy."""
        if not isinstance(value, str):
            return True
        normalized = value.strip()
        if (
            not normalized
            or normalized.casefold() in cls.WEAK_SECRET_VALUES
            or len(normalized) < cls.MIN_ADMIN_PASSWORD_LENGTH
            or len(set(normalized)) < cls.MIN_SECRET_DISTINCT_CHARACTERS
        ):
            return True
        character_classes = sum(
            (
                any(character.islower() for character in normalized),
                any(character.isupper() for character in normalized),
                any(character.isdigit() for character in normalized),
                any(not character.isalnum() for character in normalized),
            )
        )
        return character_classes < 3

    @classmethod
    def _object_store_access_key_is_unsafe(cls, value: object) -> bool:
        if not isinstance(value, str):
            return True
        normalized = value.strip()
        return not normalized or normalized.casefold() in {
            cls.DEFAULT_MINIO_ACCESS_KEY.casefold(),
            *cls.WEAK_SECRET_VALUES,
        }

    def _database_credentials_are_secure(self) -> bool:
        """Require a PostgreSQL URL with an explicit non-weak password."""
        if self.database_url == self.DEFAULT_DATABASE_URL:
            return False
        try:
            parsed = urlsplit(self.database_url)
            password = unquote(parsed.password or "")
        except (TypeError, ValueError):
            return False
        return bool(
            parsed.scheme.startswith("postgresql")
            and parsed.hostname
            and parsed.username
            and not self._secret_is_weak(password)
        )

    def _cors_origins_are_safe(self) -> bool:
        origins = self.cors_origin_list
        if not origins or "*" in origins:
            return False
        for origin in origins:
            try:
                parsed = urlsplit(origin)
            except ValueError:
                return False
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
                or parsed.path not in ("", "/")
            ):
                return False
        return True

    @classmethod
    def _trusted_proxy_configuration_is_safe(cls, value: object) -> bool:
        """Validate explicit, non-global proxy peers before honoring XFF."""
        if not isinstance(value, str):
            return False
        entries = tuple(entry.strip() for entry in value.split(",") if entry.strip())
        if not entries or set(entries) == cls.DEFAULT_TRUSTED_PROXY_IPS:
            return False
        for entry in entries:
            try:
                network = ipaddress.ip_network(entry, strict=False)
            except ValueError:
                return False
            if network.prefixlen == 0:
                return False
        return True

    def validate_runtime_security(self) -> None:
        """Refuse insecure deployment credentials and browser policy outside local/test.

        This runs during settings resolution and app assembly. It validates the
        actual values consumed by the API and workers, so production cannot
        silently inherit local defaults, placeholders, short secrets, or an
        unauthenticated Redis queue.
        """
        if self.environment in self.LOCAL_TEST_ENVIRONMENTS:
            return
        problems: list[str] = []
        if self.environment not in self.VALID_ENVIRONMENTS:
            problems.append(
                f"ENVIRONMENT={self.environment!r} is not one of "
                f"{sorted(self.VALID_ENVIRONMENTS)}"
            )
        if self.secret_key == self.DEFAULT_SECRET_KEY or self._secret_is_weak(
            self.secret_key
        ):
            problems.append(
                "SECRET_KEY is missing, default, or too weak for production"
            )
        if (
            self.mcp_token_pepper == self.DEFAULT_MCP_TOKEN_PEPPER
            or self._secret_is_weak(self.mcp_token_pepper)
        ):
            problems.append(
                "MCP_TOKEN_PEPPER is missing, default, or too weak for production"
            )
        if (
            not self.default_admin_email.strip()
            or self.default_admin_email.casefold()
            == self.DEFAULT_ADMIN_EMAIL.casefold()
        ):
            problems.append("DEFAULT_ADMIN_EMAIL is empty or the known default")
        if (
            self.default_admin_password == self.DEFAULT_ADMIN_PASSWORD
            or self._admin_password_is_weak(self.default_admin_password)
        ):
            problems.append(
                "DEFAULT_ADMIN_PASSWORD is missing, default, or too weak for production"
            )
        if self._object_store_access_key_is_unsafe(self.minio_access_key):
            problems.append("MINIO_ACCESS_KEY is empty, default, or unsafe")
        if (
            self.minio_secret_key == self.DEFAULT_MINIO_SECRET_KEY
            or self._secret_is_weak(self.minio_secret_key)
        ):
            problems.append("MINIO_SECRET_KEY is missing, default, or too weak")
        if not self.minio_endpoint.strip() or not self.minio_bucket.strip():
            problems.append("MINIO_ENDPOINT and MINIO_BUCKET are required")
        if not self._database_credentials_are_secure():
            problems.append(
                "DATABASE_URL must contain an explicit PostgreSQL host, user, and strong password"
            )
        if self.redis_password == self.DEFAULT_REDIS_PASSWORD or self._secret_is_weak(
            self.redis_password
        ):
            problems.append(
                "REDIS_PASSWORD is missing, default, or too weak for production"
            )
        if not self._trusted_proxy_configuration_is_safe(self.trusted_proxy_ips):
            problems.append(
                "TRUSTED_PROXY_IPS must contain explicit non-global production proxy peers"
            )
        if not self._cors_origins_are_safe():
            problems.append(
                "CORS_ORIGINS must be one or more explicit HTTPS origins outside local/test"
            )
        if problems:
            raise RuntimeError(
                "Refusing to start Cygnus: insecure configuration detected "
                "for ENVIRONMENT="
                + self.environment
                + " — "
                + "; ".join(problems)
                + ". Supply real deployment secrets and host inputs; do not use local defaults."
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached backend settings instance for app assembly and workers.

    Fails closed: refuses to return settings that carry default secrets or
    wide-open CORS outside local/test, so API and worker processes refuse
    startup on misconfiguration instead of booting insecure.
    """
    resolved = Settings()
    resolved.validate_runtime_security()
    return resolved


settings = get_settings()
