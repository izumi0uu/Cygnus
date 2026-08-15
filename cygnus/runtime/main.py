"""
Cygnus — Support Knowledge Control Plane.
FastAPI application entry point.
"""

import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from cygnus.integrations.mcp_auth import parse_bearer_token
from cygnus.runtime.governance_router import router as governance_router
from cygnus.runtime.config import Settings, get_settings
from cygnus.runtime.mcp.server import create_mcp_server
from cygnus.substrate.agent_protocol import (
    SESSION_CONTRACT_VERSION,
    SESSION_CONTRACT_VERSION_HEADER,
    SessionContractVersionError,
    negotiate_session_contract_version,
    session_contract_error_envelope,
)


async def seed_default_admin():
    """Create default admin account from .env if no admin exists yet."""
    from sqlalchemy import select

    from cygnus.runtime.database import get_async_session_factory
    from cygnus.runtime.database.models import Department, Employee, EmployeeDepartment
    from cygnus.runtime.services.auth_service import hash_password

    try:
        async_session_factory = get_async_session_factory()
        async with async_session_factory() as session:
            stmt = select(Employee).where(Employee.role == "admin").limit(1)
            result = await session.execute(stmt)
            if result.scalar_one_or_none():
                return

            dept = Department(
                name="Administration", description="System administrators"
            )
            session.add(dept)
            await session.flush()

            admin = Employee(
                name="Admin",
                email=get_settings().default_admin_email,
                password_hash=hash_password(get_settings().default_admin_password),
                role="admin",
            )
            session.add(admin)
            await session.flush()
            session.add(EmployeeDepartment(employee_id=admin.id, department_id=dept.id))
            await session.flush()

            await session.commit()
            logger.success(
                f"Default admin created: {get_settings().default_admin_email}"
            )
    except Exception as e:
        logger.warning(f"Could not seed default admin: {e}")


def create_app(*, app_settings: Settings | None = None) -> FastAPI:
    """Assemble the full-port FastAPI app around explicit backend settings."""
    resolved_settings = app_settings or get_settings()
    resolved_settings.validate_runtime_security()
    from cygnus.runtime.database import get_async_session_factory
    from cygnus.runtime.services.storage_service import storage_service
    from cygnus.runtime.worker import get_arq_pool as get_worker_arq_pool
    from cygnus.runtime.worker import get_redis_settings

    # Create the MCP server and its HTTP app (lifespan must be composed with FastAPI)
    mcp_server = create_mcp_server()
    mcp_http_app = mcp_server.http_app(path="/", stateless_http=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Startup & shutdown logic (composed with FastMCP lifespan)."""
        async with mcp_http_app.lifespan(app):
            logger.info("Starting Cygnus API...")
            app.state.startup_complete = False

            # Ensure MinIO bucket exists
            try:
                from cygnus.runtime.services.storage_service import storage_service

                await storage_service.ensure_bucket()
                logger.success("MinIO bucket ready")
            except Exception as e:
                logger.warning(f"MinIO not available yet: {e}")

            # Seed default admin if no admin exists yet
            await seed_default_admin()

            # Seed built-in skills (idempotent — no-op if already up to date)
            try:
                from cygnus.runtime.bootstrap.seed_builtin_skills import (
                    seed_builtin_skills,
                )

                await seed_builtin_skills()
            except Exception as e:
                logger.warning(f"Could not seed built-in skills: {e}")

            # Warn if sensitive defaults are unchanged
            if resolved_settings.secret_key == "change-me-to-a-random-secret-string":
                logger.warning(
                    "⚠️  SECRET_KEY is set to the default value — change it before deploying to production!"
                )
            if resolved_settings.default_admin_password == "admin123":
                logger.warning(
                    "⚠️  DEFAULT_ADMIN_PASSWORD is 'admin123' — change the admin password after first login!"
                )

            # MCP server ready
            app.state.startup_complete = True
            logger.success("Cygnus MCP Server ready at /mcp")
            logger.success("Cygnus API started successfully")
            yield

            app.state.startup_complete = False
            logger.info("Cygnus API shutdown complete")

    app = FastAPI(
        title="Cygnus API",
        description="Support Knowledge Operating System — Governed Knowledge Control Plane",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.mcp_server = mcp_server
    app.state.mcp_http_app = mcp_http_app
    app.state.session_factory = get_async_session_factory()
    app.state.storage_service = storage_service
    app.state.get_arq_pool = get_worker_arq_pool
    app.state.redis_settings = get_redis_settings()

    # --- CORS ---
    logger.info(f"Allowed CORS origins: {resolved_settings.cors_origin_list}")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Strict security headers (defense in depth behind nginx) ---
    # The only backend-rendered HTML is the OAuth login form, which uses an
    # inline <style> block and Google Fonts; everything else is JSON/SSE and
    # gets the maximally restrictive policy.
    _HTML_CSP = (
        "default-src 'self'; "
        "script-src 'none'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "object-src 'none'; base-uri 'self'; frame-ancestors 'none'; "
        "form-action 'self'"
    )
    _DEFAULT_CSP = (
        "default-src 'none'; object-src 'none'; base-uri 'none'; "
        "frame-ancestors 'none'; form-action 'none'"
    )
    _PRODUCTION_HSTS = "max-age=31536000; includeSubDomains"

    @app.middleware("http")
    async def _security_headers_mw(request, call_next):
        from cygnus.observability import (
            current_traceparent,
            emit_structured_log,
            record_http_request,
            request_correlation,
            resolve_request_id_header,
            start_span,
        )

        # Correlation ID: strict-UUID inbound values are trusted and echoed;
        # anything else is replaced with a fresh ID (never trusted across
        # proxy boundaries).
        raw = request.headers.get("x-request-id")
        request_id = resolve_request_id_header(raw) or str(uuid.uuid4())
        traceparent: str | None = None
        started = time.perf_counter()
        response = None
        failure: BaseException | None = None
        route_hint = getattr(request.scope.get("route"), "path", None) or "unmatched"
        try:
            with request_correlation(request_id):
                traceparent = current_traceparent()
                with start_span(
                    "http.request",
                    {"http.method": request.method, "http.route": route_hint},
                ) as span:
                    span.set_attribute("http.request_id", request_id)
                    response = await call_next(request)
        except BaseException as exc:
            # Preserve application exception semantics; finally below still
            # records a bounded 500 RED sample and a sanitized error envelope.
            failure = exc
            raise
        finally:
            duration_ms = max((time.perf_counter() - started) * 1000.0, 0.0)
            status = getattr(response, "status_code", 500)
            route = getattr(request.scope.get("route"), "path", None) or route_hint
            record_http_request(
                route=route,
                method=request.method,
                status=status,
                duration_ms=duration_ms,
            )
            # Only an actor class is logged; employee IDs, emails, bodies, and
            # authorization headers never enter telemetry.
            actor_class = "anonymous"
            state = getattr(request, "state", None)
            if state is not None and any(
                getattr(state, name, None) is not None
                for name in ("current_user", "user", "identity")
            ):
                actor_class = "authenticated"
            emit_structured_log(
                logger,
                "error" if failure is not None or status >= 500 else "info",
                event="http_request",
                route=route,
                status=status,
                duration_ms=duration_ms,
                actor_class=actor_class,
                correlation_id=request_id,
                traceparent=traceparent,
                error=failure,
                method=request.method,
            )

        # The response path below is reached only when call_next succeeded.
        assert response is not None
        response.headers.setdefault("X-Request-ID", request_id)

        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Referrer-Policy", "strict-origin-when-cross-origin"
        )
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
        )
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        if resolved_settings.environment == "production":
            response.headers.setdefault("Strict-Transport-Security", _PRODUCTION_HSTS)
        content_type = response.headers.get("content-type", "")
        if content_type.startswith("text/html"):
            response.headers.setdefault("Content-Security-Policy", _HTML_CSP)
        else:
            response.headers.setdefault("Content-Security-Policy", _DEFAULT_CSP)
        return response

    # --- Bounded Prometheus metrics surface (CYG-142) ---
    # The handler self-gates (204 when prometheus_metrics_enabled=false) and
    # performs no auth. It is intentionally NOT proxied by the shipped
    # frontend/nginx.conf — operators must keep the API port network-isolated
    # from untrusted clients if /metrics is scraped.
    from cygnus.observability import prometheus_metrics_endpoint

    _metrics_asgi = prometheus_metrics_endpoint()

    async def _metrics_route(request: Request) -> Response:
        """Bridge the raw-ASGI metrics handler onto the FastAPI route.

        Starlette's ``add_route`` wraps plain functions as request/response
        endpoints, so the observability ASGI handler (scope/receive/send) is
        driven here with the live scope and a synthetic receive/send pair;
        its start/body messages are folded into a ``Response``. /metrics
        never consumes a request body, and the handler only emits response
        start/body messages.
        """
        messages: list[dict[str, object]] = []

        async def _receive() -> dict[str, object]:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def _send(message: dict[str, object]) -> None:
            messages.append(message)

        await _metrics_asgi(request.scope, _receive, _send)

        status = 204
        raw_headers: list[tuple[bytes, bytes]] = []
        body = bytearray()
        for message in messages:
            kind = message.get("type")
            if kind == "http.response.start":
                raw_status = message.get("status", 204)
                if isinstance(raw_status, (int, str)):
                    status = int(raw_status)
                raw = message.get("headers", [])
                if isinstance(raw, list):
                    raw_headers = [
                        (name, value)
                        for name, value in raw
                        if isinstance(name, bytes) and isinstance(value, bytes)
                    ]
            elif kind == "http.response.body":
                chunk = message.get("body", b"")
                if isinstance(chunk, bytes):
                    body.extend(chunk)
        return Response(
            status_code=status,
            content=bytes(body),
            headers={
                name.decode("latin-1"): value.decode("latin-1")
                for name, value in raw_headers
            },
        )

    app.add_route("/metrics", _metrics_route)

    # --- MCP OAuth and contract gate ---
    @app.middleware("http")
    async def _mcp_oauth_gate_mw(request, call_next):
        path = request.url.path
        if path != "/mcp" and not path.startswith("/mcp/"):
            return await call_next(request)

        # Shared case-insensitive parser: same credential rules as the MCP
        # tool auth path, so malformed bearer forms get a uniform 401 here
        # instead of a different error inside the tool layer.
        if parse_bearer_token(request.headers.get("authorization")) is None:
            base = str(request.base_url).rstrip("/")
            resource_metadata_url = f"{base}/.well-known/oauth-protected-resource"
            return JSONResponse(
                status_code=401,
                content={
                    "error": "unauthorized",
                    "error_description": (
                        "This MCP endpoint requires OAuth 2.0 or a Bearer token. "
                        "See the WWW-Authenticate header for OAuth discovery."
                    ),
                },
                headers={
                    "WWW-Authenticate": (
                        f'Bearer realm="Cygnus MCP", '
                        f'resource_metadata="{resource_metadata_url}"'
                    ),
                    SESSION_CONTRACT_VERSION_HEADER: SESSION_CONTRACT_VERSION,
                },
            )

        try:
            negotiated_contract_version = negotiate_session_contract_version(
                request.headers.get(SESSION_CONTRACT_VERSION_HEADER)
            )
        except SessionContractVersionError as exc:
            return JSONResponse(
                status_code=400 if exc.code == "missing_contract_version" else 409,
                content=session_contract_error_envelope(exc),
                headers={SESSION_CONTRACT_VERSION_HEADER: SESSION_CONTRACT_VERSION},
            )

        response = await call_next(request)
        response.headers.setdefault(
            SESSION_CONTRACT_VERSION_HEADER, negotiated_contract_version
        )
        return response

    # --- Committed-only notification and durable AI review outbox accelerator ---
    @app.middleware("http")
    async def _notification_dispatch_mw(request, call_next):
        from cygnus.review.pre_review import dispatch as pre_review_dispatch
        from cygnus.runtime.services import notification_service

        notification_service.init_request_dispatch_scope()
        response = await call_next(request)
        try:
            await notification_service.dispatch_pending()
        except (
            Exception
        ) as e:  # pragma: no cover — defensive, dispatcher already catches
            logger.warning(f"Notification dispatch middleware failed: {e}")
        try:
            await pre_review_dispatch.dispatch_pending_ai_pre_reviews()
        except Exception as e:  # pragma: no cover — dispatch must not alter response
            logger.warning(f"AI pre-review dispatch middleware failed: {e}")
        return response

    # --- Mount MCP Server ---
    app.mount("/mcp", mcp_http_app)

    # --- REST API Routers ---
    from cygnus.runtime.routers import (  # noqa: E402
        admin_embeddings,
        admin_models,
        admin_settings,
        admin_stats,
        audit,
        auth,
        knowledge_types,
        notes,
        notifications,
        oauth,
        rbac,
        skill_contributions,
        skills,
        sources,
        wiki,
        wiki_branches,
        wiki_drafts,
        wiki_images,
    )

    app.include_router(oauth.wellknown_router)
    app.include_router(oauth.router, prefix="/oauth", tags=["oauth"])
    app.include_router(auth.router, prefix="/api", tags=["auth"])
    app.include_router(governance_router)
    app.include_router(sources.router, prefix="/api", tags=["sources"])
    app.include_router(notes.router, prefix="/api", tags=["notes"])
    app.include_router(wiki_branches.router, prefix="/api", tags=["wiki-branches"])
    app.include_router(wiki_drafts.router, prefix="/api", tags=["wiki-drafts"])
    app.include_router(wiki.router, prefix="/api", tags=["wiki"])
    app.include_router(wiki_images.router, prefix="/api", tags=["wiki"])
    app.include_router(admin_settings.router, prefix="/api", tags=["settings"])
    app.include_router(admin_embeddings.router, prefix="/api", tags=["settings"])
    app.include_router(admin_models.router, prefix="/api", tags=["settings"])
    app.include_router(admin_stats.router, prefix="/api", tags=["statistics"])
    app.include_router(rbac.router, prefix="/api", tags=["rbac"])
    app.include_router(knowledge_types.router, prefix="/api", tags=["knowledge-types"])
    app.include_router(audit.router, prefix="/api", tags=["audit"])
    app.include_router(skills.router, prefix="/api", tags=["skills"])
    app.include_router(
        skill_contributions.router, prefix="/api", tags=["skill-contributions"]
    )
    app.include_router(notifications.router, prefix="/api", tags=["notifications"])

    @app.get("/")
    async def root():
        from cygnus.observability import runtime_identity

        identity = runtime_identity()
        return {
            "name": "Cygnus",
            "description": "Support Knowledge Operating System",
            "version": identity["release"],
            "mcp_endpoint": "/mcp",
            "docs": "/docs",
            **identity,
        }

    @app.get("/health")
    async def health():
        services = {}
        overall = "healthy"

        # Database
        try:
            from sqlalchemy import text

            from cygnus.runtime.database import get_async_session_factory

            async_session_factory = get_async_session_factory()
            async with async_session_factory() as session:
                await session.execute(text("SELECT 1"))
            services["database"] = "healthy"
        except Exception as e:
            services["database"] = "error"
            overall = "degraded"
            logger.warning(f"Health check — database error: {e}")

        # Redis
        try:
            from cygnus.runtime.routers.sources import get_arq_pool

            pool = await get_arq_pool()
            await pool.ping()
            services["redis"] = "healthy"
        except Exception as e:
            services["redis"] = "error"
            overall = "degraded"
            logger.warning(f"Health check — redis error: {e}")

        # MinIO
        try:
            from cygnus.runtime.services.storage_service import storage_service

            await storage_service.ensure_bucket()
            services["minio"] = "healthy"
        except Exception as e:
            services["minio"] = "error"
            overall = "degraded"
            logger.warning(f"Health check — minio error: {e}")

        return {"status": overall, "services": services}

    @app.get("/api/health")
    async def api_health():
        """Detailed health check for API, database, and worker (Redis)."""
        from sqlalchemy import text

        from cygnus.runtime.database import get_async_session_factory

        result = {
            "api": "healthy",
            "database": "error",
            "worker": "error",
        }

        try:
            async_session_factory = get_async_session_factory()
            async with async_session_factory() as session:
                await session.execute(text("SELECT 1"))
            result["database"] = "healthy"
        except Exception as e:
            logger.warning(f"Health check: DB error — {e}")

        try:
            import redis.asyncio as aioredis

            r = aioredis.Redis(
                host=resolved_settings.redis_host,
                port=resolved_settings.redis_port,
                password=resolved_settings.redis_password or None,
                db=resolved_settings.redis_db,
                socket_connect_timeout=2,
            )
            await r.ping()
            await r.aclose()
            result["worker"] = "healthy"
        except Exception as e:
            logger.warning(f"Health check: Redis error — {e}")

        return result

    @app.get("/livez")
    async def livez():
        """Side-effect-free liveness: never probes database, Redis, or MinIO.

        Stays 200 while this process serves requests even when dependencies or
        workers fail; /readyz carries that truth as 503.
        """
        from cygnus.runtime.readiness import probe_liveness

        report = probe_liveness(
            startup_complete=bool(getattr(app.state, "startup_complete", False))
        )
        return JSONResponse(status_code=200, content=report.to_dict())

    @app.get("/readyz")
    async def readyz():
        """503 readiness: DB reachability + exact Alembic head, Redis, MinIO,
        configuration, and one fresh heartbeat per deployed worker role."""
        from cygnus.runtime.readiness import probe_readiness

        report = await probe_readiness(
            settings=app.state.settings,
            session_factory=app.state.session_factory,
            startup_complete=bool(getattr(app.state, "startup_complete", False)),
        )
        return JSONResponse(
            status_code=200 if report.ready else 503,
            content=report.to_dict(),
        )

    return app


settings = get_settings()
app = create_app(app_settings=settings)
